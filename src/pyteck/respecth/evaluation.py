"""Strict E/D, new NRMSE metrics, and coverage-aware rankings."""
from __future__ import annotations
from collections import Counter, defaultdict

import numpy as np
from .units import from_si

from ..eval_model import estimate_std_dev


def _mean(values):
    return float(np.mean(values)) if values else None


def _weighted(values):
    if any(not np.isfinite(weight) or weight < 0 for _, weight in values):
        raise ValueError("Weights must be finite and nonnegative")
    denominator = sum(weight for _, weight in values)
    return sum(value*weight for value, weight in values)/denominator if denominator else None


def comparison_rows(experiments, cases, results):
    result_map = {r.case_id: r for r in results}
    series_map = {s.id: s for e in experiments for s in e.observations}
    rows = []
    for case in cases:
        result = result_map.get(case.id)
        for target in case.targets:
            series = series_map[target.get('series_id', target["key"])]
            role = target.get('role', case.role)
            for point in target["point_indices"] if role == "scoring" else [-1]:
                index = series.point_indices.index(point) if point >= 0 else None
                expected = series.y[index] if index is not None else None
                predicted = result.predictions.get(target['key']) if result else None
                scan_attribute = {"temperature": "temperature", "pressure": "pressure",
                                  "residence time": "residence_time", "volume": "volume"}.get(series.scan_name)
                coordinate = getattr(case.condition, scan_attribute) if scan_attribute else (
                    series.x[index] if index is not None else target.get('coordinate', case.condition.scan_value))
                status = result.status if result else "cancelled"
                reason = result.reason if result else "Not computed"
                if status == "success" and result.validation.get("passed") is not True:
                    status, reason = "unverified", "Result lacks a passed numerical verification record"
                if status == "success" and (predicted is None or not np.isfinite(predicted)
                        or (series.quantity in {"ignition delay", "laminar burning velocity"} and predicted <= 0)):
                    status, reason = "solver_failed", "Missing, nonfinite or invalid positive prediction"
                rows.append({"experiment_id": case.experiment_id, "group_id": target["group_id"],
                    "ignition_target_original": case.config.get('ignition_substitution', {}).get('original', case.config.get('ignition_type', {})).get('target', ''),
                    "ignition_type_original": case.config.get('ignition_substitution', {}).get('original', case.config.get('ignition_type', {})).get('type', ''),
                    "ignition_target_used": case.config.get('ignition_type', {}).get('target', ''),
                    "ignition_type_used": case.config.get('ignition_type', {}).get('type', ''),
                    "ignition_substituted": bool(case.config.get('ignition_substitution')),
                    "ignition_substitution_reason": case.config.get('ignition_substitution', {}).get('reason', ''),
                    "profile_model": case.config.get('profile_model', ''),
                    "series_id": series.id, "property_id": series.property_id,
                    "point_index": point, "mechanism": case.mechanism.id, "case_id": case.id,
                    "kind": case.kind, "role": role, "quantity": series.quantity,
                    "species": series.species, "instrument": series.instrument,
                    "units": series.units, "source_type": series.source_type,
                    "scan_name": series.scan_name, "scan_value": coordinate,
                    "temperature": case.condition.temperature, "pressure": case.condition.pressure,
                    "experimental": expected, "experimental_raw": series.raw_values[index] if index is not None else None,
                    "uncertainty": series.uncertainty[index] if index is not None else None,
                    "predicted": predicted, "residual": predicted-expected if predicted is not None and expected is not None else None,
                    "status": status, "reason": reason})
    return rows


def _score_curve(series, rows, config):
    successful = [r for r in rows if r["status"] == "success" and r["predicted"] is not None]
    if not successful:
        return {"score": None, "reason": "No verified predictions"}
    y = np.array([r["experimental"] for r in successful])
    prediction = np.array([r["predicted"] for r in successful])
    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(prediction)):
        return {"score": None, "reason": "Nonfinite experiment or prediction"}
    rmse = float(np.sqrt(np.mean((prediction-y)**2)))
    if series.quantity == "ignition delay":
        if any(v <= 0 for v in series.y) or np.any(prediction <= 0):
            return {"score": None, "reason": "IDT must be positive"}
        try:
            scale = float(estimate_std_dev(np.array(series.x).copy(), np.log(np.array(series.y)).copy()))
            if not np.isfinite(scale) or scale <= 0:
                raise ValueError("Invalid empirical scale")
            residual = np.log(prediction/y) / scale
            return {"score": float(np.mean(residual**2)), "E": float(np.mean(residual**2)),
                    "D": float(np.mean(residual)), "empirical_log_scale": scale,
                    "RMSE_SI": rmse, "definition_substituted": any(r.get('ignition_substituted') for r in successful),
                    "method": "PyTeCK E/D; max dT/dt surrogate" if any(r.get('ignition_substituted') for r in successful) else "PyTeCK E/D"}
        except (ValueError, TypeError) as exc:
            return {"score": None, "reason": f"Empirical scale estimation failed: {exc}"}
    scale = max(abs(v) for v in series.y)
    if scale == 0:
        scales = config.get("scales", {})
        scale = scales.get(series.id, scales.get(series.species, scales.get(series.quantity, 0)))
    if not np.isfinite(scale) or scale <= 0:
        return {"score": None, "RMSE_SI": rmse, "reason": "Zero curve needs explicit positive normalization scale"}
    nrmse = rmse / scale
    return {"score": nrmse**2, "RMSE_SI": rmse, "NRMSE": nrmse,
            "normalization_scale_SI": float(scale), "method": "Extension NRMSE"}


def evaluate_results(experiments, results, scoring_config=None, cases=None):
    """Return all rows, diagnostics, common-set scores, and a strict formal ranking."""
    config = scoring_config or {}
    if isinstance(results, dict):
        cases = cases if cases is not None else results["cases"]
        results = results["results"]
    if cases is None:
        raise ValueError("cases are required to preserve result/measurement identities")
    rows = comparison_rows(experiments, cases, results)
    scoring_rows = [r for r in rows if r["role"] == "scoring"]
    grouped = defaultdict(list)
    for row in scoring_rows:
        grouped[(row["mechanism"], row["series_id"])].append(row)
    mechanisms = sorted({c.mechanism.id for c in cases})
    required = {(r["experiment_id"], r["series_id"], r["point_index"]) for r in scoring_rows}
    covered = {m: {(r["experiment_id"], r["series_id"], r["point_index"]) for r in scoring_rows
                   if r["mechanism"] == m and r["status"] == "success"} for m in mechanisms}
    common = set.intersection(*(covered[m] for m in mechanisms)) if mechanisms else set()
    series_map = {s.id: (e, s) for e in experiments for s in e.observations}

    def aggregate(use_common):
        curves, type_values = [], defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        missing_scales = defaultdict(bool)
        for (mechanism, series_id), records in grouped.items():
            experiment, series = series_map[series_id]
            selected = ([r for r in records if (r["experiment_id"], r["series_id"], r["point_index"]) in common]
                        if use_common else records)
            metric = _score_curve(series, selected, config)
            record = {"mechanism": mechanism, "experiment_id": experiment.id,
                      "kind": experiment.kind, "series_id": series_id, "species": series.species,
                      "instrument": series.instrument, "property_id": series.property_id,
                      "group_id": series.group_id, "label": series.label,
                      "successful_points": sum(r["status"] == "success" for r in selected),
                      "selected_points": len(selected), "original_points": len(records), **metric}
            record["units"] = series.units
            if "RMSE_SI" in metric:
                record["RMSE"] = from_si(metric["RMSE_SI"], series.units)
            curves.append(record)
            if metric["score"] is None:
                missing_scales[mechanism] = True
            else:
                # All instruments/source curves of one species get one equal species weight.
                observable = series.species or series.quantity
                type_values[mechanism][experiment.kind][(experiment.id, observable)].append(metric["score"])
        totals = []
        for mechanism in mechanisms:
            contributions = {}
            for kind, entries in type_values[mechanism].items():
                conditions = defaultdict(list)
                for (exp_id, observable), values in entries.items():
                    weight = float(config.get("species_weights", {}).get(observable, 1.))
                    conditions[exp_id].append((_mean(values), weight))
                experiment_scores = [(_weighted(v), float(config.get("experiment_weights", {}).get(exp_id, 1.)))
                                     for exp_id, v in conditions.items()]
                valid_scores = [(v, weight) for v, weight in experiment_scores if v is not None]
                combined_type = _weighted(valid_scores)
                if combined_type is not None:
                    contributions[kind] = combined_type
            weights = {kind: float(config.get("type_weights", {}).get(kind, 1.)) for kind in contributions}
            if any(not np.isfinite(w) or w < 0 for w in weights.values()):
                raise ValueError("Type weights must be finite and nonnegative")
            denominator = sum(weights.values())
            combined = (sum(contributions[k]*weights[k] for k in contributions)/denominator
                        if denominator else None)
            coverage = len(covered[mechanism])/len(required) if required else 0
            eligible = (bool(required) and covered[mechanism] == required and not missing_scales[mechanism]
                        and combined is not None)
            local_eligible = bool(common) and not missing_scales[mechanism] and combined is not None
            totals.append({"mechanism": mechanism, "coverage": coverage,
                           "eligible": local_eligible if use_common else eligible,
                           "score": combined, "type_contributions": contributions, "weights": weights,
                           "label": "扩展组合指标",
                           "species_weights": config.get("species_weights", {}),
                           "experiment_weights": config.get("experiment_weights", {}),
                           "status_counts": dict(Counter(r["status"] for r in scoring_rows if r["mechanism"] == mechanism))})
        ranking = sorted((r for r in totals if r["eligible"]), key=lambda r: r["score"])
        for i, entry in enumerate(ranking, 1):
            entry["rank"] = i
        return {"curves": curves, "mechanisms": totals, "ranking": ranking}

    formal = aggregate(False)
    local = aggregate(True)
    return {"rows": rows, "formal": formal, "common_success": local,
            "common_points": len(common), "excluded_points": len(required-common),
            "common_set": [list(v) for v in sorted(common)],
            "notes": ["Empirical log scale is not measured uncertainty",
                      "Cross-type combination is a new extension indicator, not original PyTeCK E"]}
