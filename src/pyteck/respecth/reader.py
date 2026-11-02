"""Native read-only RKD parser. Original XML and numeric records remain intact."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import math
import os
import re
import xml.etree.ElementTree as ET

from .models import (Condition, DataGroup, Experiment, ObservationSeries, Property,
                     OBSERVABLES, file_hash)
from .units import to_si
from ..path_io import absolute_path

CONDITIONS = {"temperature", "pressure", "residence time", "volume", "equivalence ratio", "time", "distance"}


def _property(node, default_id=""):
    link = node.find("speciesLink")
    species = link.get("preferredKey") if link is not None else None
    value = node.findtext("value")
    components = {}
    for component in node.findall("component"):
        s, amount = component.find("speciesLink"), component.find("amount")
        if s is None or amount is None:
            raise ValueError("Incomplete composition component")
        key = s.get("preferredKey")
        if not key or key in components:
            raise ValueError("Missing or duplicate inlet species")
        components[key] = {"value": float(amount.text), "units": amount.get("units", ""),
                           "species_link": dict(s.attrib)}
    u = node.find("uncertainty")
    uncertainty = ({**u.attrib, "value": float(u.text)}
                   if u is not None and u.text and u.text.strip() else {})
    return Property(node.get("id", default_id), node.get("name", ""),
                    node.get("units", ""), species, node.get("label", ""),
                    node.get("sourcetype", ""), dict(node.attrib),
                    float(value) if value is not None else None, components, uncertainty)


def _put(mapping, key, value, issues):
    if key in mapping and not math.isclose(mapping[key], value, rel_tol=1e-8, abs_tol=1e-12):
        issues.append(f"Conflicting common/point value: {key}")
    else:
        mapping[key] = value


def _condition(common, props, row, scan, inherited):
    values, composition, issues, sources = {}, {}, list(inherited), {}
    for p in [*common, *props]:
        raw = row.get(p.id) if p in props else p.value
        try:
            if p.name == "initial composition":
                for species, amount in p.components.items():
                    _put(composition, species, to_si(amount["value"], amount["units"], p.name), issues)
                if p.species and raw is not None:
                    _put(composition, p.species, to_si(raw, p.units, p.name), issues)
            elif p.name in CONDITIONS and raw is not None:
                _put(values, p.name, to_si(raw, p.units, p.name), issues)
            if p.name in CONDITIONS or p.name == "initial composition":
                sources[p.id or p.name] = p.source_type
        except ValueError as exc:
            issues.append(str(exc))
    if scan not in values:
        issues.append(f"Missing scan coordinate: {scan}")
    return Condition(scan, values.get(scan, 0.), values.get("temperature"),
                     values.get("pressure"), composition, values.get("residence time"),
                     values.get("volume"), {"properties": values, "sources": sources}, issues)


def _uncertainty(observation, common, properties, row, y):
    candidates = []
    if observation.uncertainty:
        candidates.append((observation.uncertainty, observation.units, observation.uncertainty["value"]))
    for prop in common + properties:
        if prop.name not in {"evaluated standard deviation", "uncertainty"}:
            continue
        reference = prop.attrs.get("reference", "")
        if reference not in {observation.id, observation.name}:
            continue
        if prop.species != observation.species:
            continue
        raw = row.get(prop.id, prop.value)
        if raw is not None:
            candidates.append((prop.attrs, prop.units, raw))
    if not candidates:
        return None
    attrs, unit, value = candidates[0]
    if attrs.get("kind", "absolute") == "relative":
        factor = value / 100 if unit in {"percent", "%"} else value
        return abs(y) * factor
    return to_si(value, unit, observation.name)


def load_experiment(path):
    path = absolute_path(path)
    text = path.read_text(encoding="utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DTD and entities are not allowed")
    root = ET.fromstring(text)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    if root.tag != "experiment":
        raise ValueError(f"Unsupported XML root: {root.tag}")
    issues = []
    version = root.find("ReSpecThVersion")
    version_text = (f"{version.findtext('major')}.{version.findtext('minor')}"
                    if version is not None else "unknown")
    if version_text not in {"2.6", "2.3"}:
        issues.append(f"Unsupported ReSpecTh version: {version_text}")
    common = [_property(n, f"common{i}") for i, n in enumerate(root.findall("commonProperties/property"))]
    experiment_id = file_hash(path)[:16] + "-" + path.stem
    groups, observations = [], []
    file_issues = list(issues)
    seen_groups = set()
    for group_number, node in enumerate(root.findall("dataGroup")):
        group_id = node.get("id", f"group{group_number}")
        if group_id in seen_groups:
            issues.append(f"Duplicate dataGroup ID: {group_id}")
        seen_groups.add(group_id)
        props = [_property(n) for n in node.findall("property")]
        ids = [p.id for p in props]
        group_issues = []
        if not all(ids) or len(ids) != len(set(ids)):
            group_issues.append("Missing/duplicate property ID")
        points, point_issues = [], []
        for index, point in enumerate(node.findall("dataPoint")):
            row = {}
            row_issues = []
            for field in point:
                if field.tag in row:
                    row_issues.append(f"Duplicate dataPoint field {field.tag}")
                row[field.tag] = float(field.text)
            if set(row) != set(ids):
                row_issues.append("Incomplete/unknown fields")
            if not all(math.isfinite(v) for v in row.values()):
                row_issues.append("Nonfinite measurement")
            points.append(row)
            point_issues.append(row_issues)
        candidates = [p.name for p in props if p.name in CONDITIONS
                      and len({r.get(p.id) for r in points}) > 1]
        experiment_type = root.findtext('experimentType', '')
        profile_scan = {'concentration time profile measurement': 'time',
                        'burner stabilized flame speciation measurement': 'distance'}.get(experiment_type)
        priority = ([profile_scan] if profile_scan else []) + ["equivalence ratio", "temperature", "pressure", "residence time"]
        scan = next((p for p in priority if p in candidates), None)
        if scan is None:
            scan = next((name for name in priority if any(p.name == name for p in props)), "temperature")
        # The imposed T(z) is an input field, not a different inlet temperature at each z.
        condition_props = [p for p in props if p.name != 'temperature'] if profile_scan == 'distance' else props
        conditions = [_condition(common, condition_props, row, scan, file_issues + group_issues + point_issues[i])
                      for i, row in enumerate(points)]
        group = DataGroup(group_id, node.get("label", ""), props, points, conditions, scan)
        groups.append(group)
        issues.extend(f"{group_id}:*: {message}" for message in group_issues)
        issues.extend(f"{group_id}:{i}: {message}" for i, errors in enumerate(point_issues) for message in errors)
        for p in props:
            if p.name not in OBSERVABLES:
                continue
            x, y, raw, indices, uncertainties = [], [], [], [], []
            for index, (row, condition) in enumerate(zip(points, conditions)):
                if p.id not in row:
                    continue
                value = row[p.id]
                try:
                    converted = to_si(value, p.units, p.name)
                    uncertainty = _uncertainty(p, common, props, row, converted)
                except ValueError as exc:
                    issues.append(f"{group_id}:{index}: {exc}")
                    converted, uncertainty = value, None
                x.append(condition.scan_value)
                y.append(converted)
                raw.append(value)
                indices.append(index)
                uncertainties.append(uncertainty)
            instrument = p.attrs.get("instrument", "")
            if not instrument:
                match = re.search(r"(FTIR|microGC|analyzer)", p.label, re.I)
                instrument = match.group(1) if match else ""
            observations.append(ObservationSeries(
                f"{experiment_id}:{group_id}:{p.id}", group_id, p.id, p.name, p.species,
                instrument, p.units, p.source_type, p.label, scan, x, y, raw, indices, uncertainties))
    apparatus = root.find("apparatus")
    apparatus_data = ({n.tag: n.text for n in apparatus} if apparatus is not None else {})
    link = root.find("bibliographyLink")
    bibliography = ({"xml": ET.tostring(link, encoding="unicode"),
                     "description": link.findtext("description", ""),
                     "doi": link.findtext("referenceDOI", "")} if link is not None else {})
    ignition = root.find("ignitionType")
    if not groups or not observations:
        issues.append("No supported observations")
    return Experiment(experiment_id, str(path), file_hash(path), version_text,
        root.findtext("experimentType", ""), apparatus_data, bibliography, common, groups,
        observations, dict(ignition.attrib) if ignition is not None else {},
        [n.text or "" for n in root.findall("comment")], list(dict.fromkeys(issues)), text)


def resolve_condition(condition, config):
    """Fill explicitly supplied missing conditions; preserve source conflicts."""
    resolved = replace(condition, composition=dict(condition.composition),
                       extras=dict(condition.extras), issues=list(condition.issues))
    physical = config.get("conditions", {})
    dimensions = {"temperature": "temperature", "pressure": "pressure", "volume": "volume",
                  "residence_time": "residence time"}
    for name, supplied in physical.items():
        if name == "composition":
            for species, value in supplied.items():
                converted = to_si(value['value'], value['units'], 'initial composition') if isinstance(value, dict) else float(value)
                _put(resolved.composition, species, converted, resolved.issues)
            continue
        if name not in dimensions:
            raise ValueError(f"Unsupported supplemental condition: {name}")
        converted = to_si(supplied['value'], supplied['units'], dimensions[name]) if isinstance(supplied, dict) else float(supplied)
        current = getattr(resolved, name)
        if current is not None and not math.isclose(current, converted, rel_tol=1e-8, abs_tol=1e-12):
            resolved.issues.append(f"Conflicting XML/config value: {name}")
        elif current is None:
            setattr(resolved, name, converted)
            if resolved.scan_name == dimensions[name]:
                resolved.scan_value = converted
                resolved.issues = [i for i in resolved.issues if i != f"Missing scan coordinate: {resolved.scan_name}"]
    if physical:
        resolved.extras["supplemental_conditions"] = physical
        resolved.extras["supplemental_source"] = config.get("condition_source", "explicit user configuration")
    return resolved


def validate_experiment(experiment, model_config=None):
    config = model_config or {}
    issues = list(experiment.issues)
    if experiment.kind == "unsupported":
        issues.append(f"Unsupported experiment type: {experiment.experiment_type}")
    if experiment.kind in {"pfr", "jsr"}:
        if config.get("energy", "off") != "off":
            issues.append("Only isothermal FR/JSR is supported in v1")
    if experiment.kind == "ignition" and not experiment.ignition_type and config.get('ignition_fallback', 'temperature_gradient') == 'none':
        issues.append("Missing ignitionType")
    if experiment.kind == 'ignition' and config.get('ignition_fallback', 'temperature_gradient') not in {'temperature_gradient', 'none'}:
        issues.append('Invalid ignition_fallback: choose temperature_gradient or none')
    if experiment.kind == 'profile' and experiment.apparatus.get('kind', '').lower() != 'shock tube':
        issues.append('Unsupported apparatus for concentration time profile: expected shock tube')
    if experiment.kind == 'burner_profile':
        from .profile_inputs import validate_burner_inputs
        issues.extend(validate_burner_inputs(experiment, config))
    for group in experiment.groups:
        for i, condition in enumerate(group.conditions):
            condition = resolve_condition(condition, config)
            errors = list(condition.issues)
            if experiment.kind in {'profile', 'burner_profile'}:
                expected_scan = 'time' if experiment.kind == 'profile' else 'distance'
                if condition.scan_name != expected_scan or not math.isfinite(condition.scan_value) or condition.scan_value < 0:
                    errors.append(f'Missing/invalid nonnegative {expected_scan} coordinate')
            for name in ("temperature", "pressure"):
                value = getattr(condition, name)
                if value is None or not math.isfinite(value) or value <= 0:
                    errors.append(f"Missing/invalid {name}")
            inlet = condition.composition
            if (not inlet or any(not math.isfinite(v) or v < 0 for v in inlet.values())
                    or abs(sum(inlet.values()) - 1) > 1e-6):
                errors.append("Incomplete/invalid inlet mole fractions; sum must be 1 ± 1e-6")
            for name in (("residence_time", "volume") if experiment.kind == "jsr"
                         else ("residence_time",) if experiment.kind == "pfr" else ()):
                value = getattr(condition, name)
                if value is None or not math.isfinite(value) or value <= 0:
                    errors.append(f"Missing/invalid {name}")
            issues.extend(f"{group.id}:{i}: {e}" for e in errors)
    for series in experiment.observations:
        if series.quantity in {"composition", "concentration"} and not series.species:
            issues.append(f"Missing observed speciesLink: {series.id}")
        for i, value in zip(series.point_indices, series.y):
            if not math.isfinite(value) or value < 0:
                issues.append(f"{series.group_id}:{i}: Invalid measurement: {series.id}")
            if series.quantity in {"ignition delay", "laminar burning velocity"} and value <= 0:
                issues.append(f"{series.group_id}:{i}: Nonpositive {series.quantity}: {series.id}")
    return list(dict.fromkeys(issues))


def discover_experiments(root):
    """Find XML in arbitrary data folders, excluding archives and generated state."""
    root = absolute_path(root)
    if not root.is_dir():
        raise NotADirectoryError(f'实验目录不存在或不是文件夹：{root}')
    excluded = {'results', 'node_modules', '__pycache__', 'archive', 'archives',
                'archived', 'backup', 'backups', 'history', '历史归档', '归档', '备份'}

    def skip(directory):
        name = directory.name.casefold()
        return (name.startswith('.') or name in excluded
                or name.startswith(('archive-', 'archive_', 'backup-', 'backup_'))
                or directory.is_symlink()
                or getattr(directory, 'is_junction', lambda: False)()
                or (directory / 'UPSTREAM.json').is_file()
                or (directory / 'project.json').is_file())

    def failed(error):
        raise error

    files = []
    for folder, directories, names in os.walk(root, followlinks=False, onerror=failed):
        directories[:] = sorted(d for d in directories if not skip(Path(folder) / d))
        for name in names:
            lowered = name.casefold()
            path = Path(folder) / name
            if (lowered.endswith('.xml') and not lowered.startswith('.')
                    and '.draft.' not in lowered and '.new.' not in lowered
                    and not path.is_symlink()):
                files.append(path)
    return sorted(files)
