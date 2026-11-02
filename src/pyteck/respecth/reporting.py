"""Reusable Matplotlib templates and traceable CSV/media exports."""
from __future__ import annotations
from collections import defaultdict, Counter
from pathlib import Path
import csv
import json
import math
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .evaluation import comparison_rows
from .atomic_io import atomic_json
from .units import from_si, to_si


def summarize_run(manifest):
    """Physical case outcomes, independent of measurement basis and scoring."""
    cases = {c['id']: c for c in manifest['cases']}
    experiments = {e['id']: e['path'] for e in manifest['experiments']}
    failures, by_type, by_dataset = [], defaultdict(Counter), defaultdict(Counter)
    for result in manifest['results']:
        case = cases[result['case_id']]
        status = result['status']
        by_type[case['kind']][status] += 1
        by_dataset[experiments[case['experiment_id']]][status] += 1
        if status != 'success':
            failures.append({'case_id': case['id'], 'XML': experiments[case['experiment_id']],
                'dataGroup': case['group_id'], 'point_indices': case['point_indices'],
                'mechanism': case['mechanism']['id'], 'kind': case['kind'], **case['condition'],
                'status': status, 'reason': result.get('reason', '')})
    counts = dict(Counter(r['status'] for r in manifest['results']))
    return {'status': manifest['status'], 'total_cases': len(cases),
            'completed_cases': len(manifest['results']), 'status_counts': counts,
            'numerically_verified': sum(r['status'] == 'success' and r.get('validation', {}).get('passed') is True
                                      for r in manifest['results']),
            'by_type': [{'kind': k, 'total': sum(v.values()), **dict(v)} for k,v in by_type.items()],
            'by_dataset': [{'XML': k, 'total': sum(v.values()), **dict(v)} for k,v in by_dataset.items()],
            'failures': failures, 'output': manifest['config']['output']}


def export_run_summary(manifest):
    summary = summarize_run(manifest)
    directory = Path(summary['output'])
    atomic_json(directory/'run_summary.json', summary)
    _csv(directory/'failed_cases.csv', summary['failures'])
    _csv(directory/'dataset_status.csv', summary['by_dataset'])
    return summary


def _csv(path, rows):
    if not rows:
        Path(path).write_text("", encoding="utf-8-sig")
        return
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def export_results(run):
    directory = Path(run["output"])
    directory.mkdir(parents=True, exist_ok=True)
    evaluation = run["evaluation"]
    rows = []
    for original in evaluation["rows"]:
        row = dict(original)
        row["predicted_display"] = from_si(row["predicted"], row["units"]) if row["predicted"] is not None else None
        row["experimental_display"] = row["experimental_raw"]
        row["residual_display"] = from_si(row["residual"], row["units"]) if row["residual"] is not None else None
        rows.append(row)
    _csv(directory / "comparison.csv", rows)
    _csv(directory / "curve_scores.csv", evaluation["formal"]["curves"])
    _csv(directory / "mechanism_scores.csv", evaluation["formal"]["mechanisms"])
    _csv(directory / "common_success_scores.csv", evaluation["common_success"]["mechanisms"])
    _csv(directory / "cases.csv", [{"case_id": c.id, "mechanism": c.mechanism.id,
        "experiment_id": c.experiment_id, "group_id": c.group_id, "kind": c.kind,
        "role": c.role, "condition": c.condition.__dict__, "solver_config": c.config,
        "predecessor": c.predecessor, "issues": c.issues} for c in run["cases"]])
    return [str(p) for p in directory.glob("*.csv")]


def _x(values, scan, transformed):
    values = np.asarray(values, dtype=float)
    return 1000 / values if scan == "temperature" and transformed else values


def condition_annotation(experiment, cases):
    """Describe actual scoring inputs; never infer an unrecorded feed or formula."""
    selected = [c for c in cases if c.experiment_id == experiment.id and c.role == 'scoring']
    conditions = [c.condition for c in selected]
    if not conditions:
        conditions = [c for group in experiment.groups for c in group.conditions]
    if not conditions:
        return 'Conditions: unavailable in XML'
    def interval(values, factor=1):
        values = [v*factor for v in values if v is not None and math.isfinite(v)]
        if not values:
            return 'not recorded'
        lo, hi = min(values), max(values)
        return f'{lo:.6g}' if math.isclose(lo, hi, rel_tol=1e-9, abs_tol=1e-12) else f'{lo:.6g}–{hi:.6g}'
    pressure = next((p for p in experiment.common_properties if p.name=='pressure'), None)
    parts = [f"P = {interval([c.pressure for c in conditions], 1/101325)} atm" +
             (' (estimated)' if pressure and pressure.source_type=='estimated' else '')]
    from .inlet_properties import inlet_equivalence_ratio
    try:
        phis=[inlet_equivalence_ratio(c.condition,getattr(c,'mechanism',None)) for c in selected] if selected else [inlet_equivalence_ratio(c) for c in conditions]
        parts.append(f'φ = {interval(phis)} (inlet elemental ratio)')
    except (ValueError,OSError,KeyError) as error:
        parts.append(f'φ unavailable: {error}')
    if experiment.kind != 'ignition':
        temperature_label = 'T_inlet' if experiment.kind == 'burner_profile' else 'T0' if experiment.kind == 'profile' else 'T'
        parts.append(f"{temperature_label} = {interval([c.temperature for c in conditions])} K")
    times = [c.residence_time for c in conditions if c.residence_time is not None]
    if times:
        rules = [c.config.get('grid_rules', {}).get('residence_time', {}) for c in selected]
        coefficients = {r.get('coefficient') for r in rules if r.get('kind')=='inverse_temperature'}
        coefficient = next(iter(coefficients)) if len(coefficients)==1 else None
        matches = coefficient is not None and len(rules)==len(conditions) and all(
            r.get('kind')=='inverse_temperature' for r in rules) and all(
            c.temperature and c.residence_time is not None and
            math.isclose(c.residence_time*c.temperature, coefficient, rel_tol=1e-7, abs_tol=1e-8) for c in conditions)
        parts.append(f'τ (s) = {coefficient:g} / T(K)' if matches else f"τ = {interval(times)} s")
    if experiment.kind=='jsr':
        parts.append(f"V = {interval([c.volume for c in conditions], 1e6)} cm³")
    if experiment.kind == 'profile': parts.append('adiabatic constant-volume shock-tube time profile')
    if experiment.kind == 'burner_profile': parts.append('burner-stabilized flame; imposed measured T(z)')
    if experiment.kind == 'burner_profile' and selected:
        cfg = selected[0].config
        parts.append(f"T(z) = {interval(cfg['temperature_profile']['temperature'])} K")
        if 'burner_mass_flux' in cfg: parts.append(f"mass flux = {cfg['burner_mass_flux']:g} kg/m²/s")
    if any(c.config.get('ignition_substitution') for c in selected):
        parts.append('IDT surrogate: time of maximum dT/dt; original literature definition retained in results')
    species = list(dict.fromkeys(s for c in conditions for s in c.composition))
    varying = any(not all(math.isclose(c.composition.get(s, 0), conditions[0].composition.get(s, 0),
                          rel_tol=1e-9, abs_tol=1e-12) for c in conditions) for s in species)
    feed, balance = [], []
    for name in species:
        values = [c.composition.get(name, 0) for c in conditions]
        unit, factor = ('%',100) if max(values) >= .01 else ('ppm',1e6)
        amount = f'{interval(values, factor)} {unit} {name}'
        if name.upper() in {'N2','AR','HE'} and min(values) > .5:
            balance.append(f'balance {name} ({interval(values,100)}%)')
        else:
            if name=='H2O' and max(values)==0 and any('trace' in comment.lower() for comment in experiment.comments):
                amount += ' (XML represents trace as zero)'
            feed.append(amount)
    initial = next((p for p in experiment.common_properties if p.name=='initial composition'), None)
    qualifier = ' (varies across points)' if varying else ''
    if initial and initial.source_type=='estimated':
        qualifier += ' (XML estimated)'
    lines = ['Conditions: '+ '; '.join(parts), 'Inlet composition'+qualifier+': '+ ', '.join(feed+balance)]
    return '\n'.join(lines)


def _annotate_conditions(fig, texts, config, top=.96):
    if not config.get('conditions', True):
        fig.tight_layout(rect=(0,.025,1,top))
        return
    fontsize = float(config.get('conditions_fontsize', 8))
    if not math.isfinite(fontsize) or not 5 <= fontsize <= 20:
        raise ValueError('conditions_fontsize must be between 5 and 20')
    position = config.get('conditions_position', 'bottom')
    if position not in {'bottom','top','upper right','upper left'}:
        raise ValueError('Unsupported conditions_position')
    width, height = fig.get_size_inches()
    if position in {'upper right','upper left'}:
        width *= fig.axes[0].get_position().width
    columns = max(25, int(width*72/(fontsize*.52)))
    wrapped = '\n'.join('\n'.join(textwrap.wrap(line, width=columns, break_long_words=False, break_on_hyphens=False))
                        for text in texts for line in text.splitlines())
    if position in {'upper right','upper left'}:
        ax = fig.axes[0]
        ax.text(.98 if position=='upper right' else .02, .98, wrapped,
                ha='right' if position=='upper right' else 'left', va='top', transform=ax.transAxes,
                fontsize=fontsize, bbox={'facecolor':'white','alpha':.85,'edgecolor':'none'})
        fig.tight_layout(rect=(0,.025,1,top))
        return
    reserved = (wrapped.count('\n')+1)*fontsize*1.5/72+.2
    fig.set_size_inches(width,height+reserved)
    fraction = reserved/(height+reserved)
    if position=='bottom':
        fig.text(.02,.02,wrapped,va='bottom',ha='left',fontsize=fontsize)
        fig.tight_layout(rect=(0,fraction,1,top))
    else:
        fig.text(.02,top-.01,wrapped,va='top',ha='left',fontsize=fontsize)
        fig.tight_layout(rect=(0,.025,1,top-fraction))


def _style_axis(ax, quantity, scan, config):
    xlabel = "1000/T (K⁻¹)" if scan == "temperature" and quantity == "ignition delay" and config.get("reciprocal_temperature", True) else {
        "temperature": "Temperature (K)", "pressure": "Pressure (Pa)",
        "equivalence ratio": "Equivalence ratio", "residence time": "Residence time (s)",
        "time": "Time (s)", "distance": "Distance above burner (m)"}.get(scan, scan)
    ax.set_xlabel(xlabel)
    ax.grid(alpha=.2)
    if quantity == "ignition delay" or config.get("yscale") == "log":
        ax.set_yscale("log")
    if config.get("yscale") == "linear":
        ax.set_yscale("linear")
    if config.get("xscale"):
        ax.set_xscale(config["xscale"])
    if config.get("xlim"):
        ax.set_xlim(config["xlim"])
    if config.get("ylim"):
        ax.set_ylim(config["ylim"])


def _plot_series(ax, experiment, series, rows, colors, config, condition_style="-", condition_label="", condition_color=None):
    if '_rows_by_series' in config:
        rows=config['_rows_by_series'].get(series.id,[])
    quantity = series.quantity
    unit = config.get("composition_unit", "ppm") if quantity in {"composition", "concentration"} and series.units not in {"mol/m3", "mol/cm3"} else {
        "ignition delay": "us", "laminar burning velocity": "cm/s"}.get(quantity, series.units)
    unit = config.get("units", {}).get(quantity, unit)
    reciprocal = quantity == "ignition delay" and config.get("reciprocal_temperature", True)
    resolved_coordinates = {r["point_index"]: r["scan_value"] for r in rows
                            if r["series_id"] == series.id and r["role"] == "scoring"}
    x = _x([resolved_coordinates.get(i, value) for i, value in zip(series.point_indices, series.x)],
           series.scan_name, reciprocal)
    try:
        to_si(1., series.units, quantity)
        to_si(1., unit, quantity)
        measured = np.array([from_si(v, unit) for v in series.y])
    except ValueError:
        ax.text(.5, .5, f"Cannot display {series.species or quantity}: unsupported unit {unit!r}",
                transform=ax.transAxes, ha="center", wrap=True)
        return
    uncertainty = np.array([from_si(v, unit) if v is not None else 0 for v in series.uncertainty])
    marker_map = config.get("markers", {})
    all_series = [s.id for e in config.get("_experiments", [experiment]) for s in e.observations]
    marker = marker_map.get(series.id, ["o", "s", "^", "D", "v", "P", "X"][all_series.index(series.id) % 7])
    label = condition_label + (" " + series.instrument if series.instrument else "")
    ax.errorbar(x, measured, yerr=uncertainty if np.any(uncertainty) else None,
                fmt=marker, markersize=4, linestyle="none", color=condition_color if condition_color is not None else "black",
                alpha=.65, capsize=2, label=(label.strip() or "Experiment"))
    styles = ["-", "--", "-.", ":", (0, (5, 1)), (0, (3, 1, 1, 1, 1, 1))]
    for mechanism_index, (mechanism, color) in enumerate(colors.items()):
        records = [r for r in rows if r["series_id"] == series.id and r["mechanism"] == mechanism]
        # Both scoring and dense points are present; consolidate identical coordinates without
        # deleting a failed endpoint, which must break the predicted line.
        coordinates = defaultdict(list)
        for record in records:
            coordinates[record["scan_value"]].append(record)
        xs, ys = [], []
        for coordinate, batch in coordinates.items():
            accepted = all(r["status"] == "success" for r in batch)
            value = batch[0]["predicted"] if accepted else None
            xs.append(coordinate)
            ys.append(from_si(value, unit) if value is not None else np.nan)
        if not xs:
            continue
        xs = _x(xs, series.scan_name, reciprocal)
        order = np.argsort(xs)
        legend = mechanism + (" / " + condition_label if condition_label else "")
        # Repeated instruments have the same physical prediction, but distinct grids can differ.
        if not np.any(np.isfinite(ys)):
            continue
        ax.plot(xs[order], np.asarray(ys)[order], color=condition_color if condition_color is not None else color,
                linestyle=styles[config.get("_mechanism_indices", {}).get(mechanism, mechanism_index) % len(styles)] if condition_color is not None else condition_style, marker="None",
                linewidth=config.get("linewidth", 1.5), label=legend)
    unit_label = {"us": "µs", "percent": "%"}.get(unit, unit)
    ax.set_ylabel(f"{series.species or quantity} ({unit_label})")
    _style_axis(ax, quantity, series.scan_name, config)
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    if config.get("legend", True):
        ax.legend(unique.values(), unique.keys(), fontsize=7, frameon=False,
                  loc=config.get("legend_location", "best"))


def plot_availability(experiments, cases, results, datasets, mechanisms, selected_series, *, rows=None):
    """Describe exactly which selected curves have usable saved predictions."""
    experiment_ids={e.id for e in experiments}
    if rows is None:
        rows=comparison_rows(experiments,[c for c in cases if c.experiment_id in experiment_ids],results)
    selected=set(selected_series)
    grouped=defaultdict(list)
    for row in rows:
        if row['series_id'] in selected and row['mechanism'] in mechanisms:
            grouped[(row['experiment_id'],row['mechanism'],row['series_id'])].append(row)
    output=[]
    for experiment in experiments:
        if experiment.id not in datasets: continue
        for mechanism in mechanisms:
            records=[]; points=0; lines=0
            for series in experiment.observations:
                if series.id not in selected: continue
                curve=grouped[(experiment.id,mechanism,series.id)]
                records.extend(curve)
                coordinates=defaultdict(list)
                for row in curve: coordinates[row['scan_value']].append(row)
                usable=[]
                for coordinate,batch in sorted(coordinates.items(),key=lambda item:float('inf') if item[0] is None else item[0]):
                    value=batch[0]['predicted']
                    usable.append(all(r['status'] == 'success' for r in batch)
                        and coordinate is not None and math.isfinite(coordinate)
                        and value is not None and math.isfinite(value))
                points+=sum(usable)
                lines+=any(a and b for a,b in zip(usable,usable[1:]))
            reasons=Counter(r['reason'] for r in records if r['status'] != 'success')
            reason='；'.join(reasons) if records else '该批次没有这个 XML 的机理计算记录'
            if points and not lines: reason='仅有孤立成功点，不能跨失败区间连线；'+reason
            output.append({'XML':Path(experiment.path).stem,'机理':mechanism,
                '可绘制预测点':points,'可连线曲线':lines,'说明':reason or '已有可绘制模拟结果'})
    return output


def render_figures(experiments, results, figure_config=None, *, progress=None):
    from .runner import project_root
    config = dict(figure_config or {})
    if config.get('macro_layout','overlay') not in {'overlay','subplots'}:
        raise ValueError('macro_layout must be overlay or subplots')
    directory = Path(config.pop("output", project_root()/"results/figures"))
    directory.mkdir(parents=True, exist_ok=True)
    selected=config.get('series')
    allowed_experiments=config.get('experiments')
    eligible=[e for e in experiments if (allowed_experiments is None or e.id in allowed_experiments)
              and any(selected is None or s.id in selected for s in e.observations)]
    macro_jobs={kind:list(dict.fromkeys(s.scan_name for e in eligible if e.kind==kind
                for s in e.observations if selected is None or s.id in selected)) for kind in ('ignition','flame')}
    total=sum(e.kind in {'pfr','jsr','profile','burner_profile'} for e in eligible)+sum(map(len,macro_jobs.values()))
    done=0
    def notify(message):
        if progress is not None: progress(done,total,message)
    notify('正在整理实验—模拟对应数据…')
    config["_experiments"] = experiments
    cases, case_results = results["cases"], results["results"]
    rows = comparison_rows(experiments, cases, case_results)
    indexed=defaultdict(list)
    for row in rows: indexed[row['series_id']].append(row)
    config['_rows_by_series']=indexed
    mechanisms = sorted({c.mechanism.id for c in cases})
    config["_mechanism_indices"] = {m:i for i,m in enumerate(mechanisms)}
    palette = plt.get_cmap("tab10")
    allowed_mechanisms = config.get("mechanisms")
    if allowed_mechanisms is not None and set(allowed_mechanisms) - set(mechanisms):
        raise ValueError("Unknown mechanism selected for plotting")
    colors = {m: config.get("colors", {}).get(m, palette(i % 10)) for i, m in enumerate(mechanisms)
              if allowed_mechanisms is None or m in allowed_mechanisms}
    selected = config.get("series")
    allowed_experiments = config.get("experiments")
    paths = []
    metadata = []
    with plt.rc_context({"font.family": "DejaVu Sans", "axes.spines.top": True,
                         "axes.spines.right": True, "xtick.direction": "in", "ytick.direction": "in",
                         "xtick.top": True, "ytick.right": True, "svg.fonttype": "none"}):
        for experiment in experiments:
            if experiment.kind not in {"pfr", "jsr", "profile", "burner_profile"}:
                continue
            if allowed_experiments is not None and experiment.id not in allowed_experiments:
                continue
            series_list = [s for s in experiment.observations if selected is None or s.id in selected]
            panels = list(dict.fromkeys((s.species, s.scan_name, "molar" if s.units in {"mol/m3", "mol/cm3"} else "fraction") for s in series_list))
            species_order = config.get("species_order", [])
            panels.sort(key=lambda p: species_order.index(p[0]) if p[0] in species_order else len(species_order))
            if not panels:
                continue
            title=Path(experiment.path).name
            notify(f'正在绘制 {title}（{len(panels)} 个物种子图）')
            columns = max(1, min(int(config.get("columns", 3)), len(panels)))
            nrows = math.ceil(len(panels)/columns)
            fig, axes = plt.subplots(nrows, columns, figsize=config.get("figsize", [4*columns, 3*nrows]), squeeze=False)
            for ax, panel in zip(axes.flat, panels):
                notify(f'正在绘制 {title} / {panel[0] or panel[1]}')
                for s in series_list:
                    if (s.species, s.scan_name, "molar" if s.units in {"mol/m3", "mol/cm3"} else "fraction") == panel:
                        _plot_series(ax, experiment, s, rows, colors, config)
            for ax in list(axes.flat)[len(panels):]:
                ax.set_visible(False)
            availability=plot_availability([experiment],cases,case_results,[experiment.id],list(colors),[s.id for s in series_list],rows=rows)
            experiment_only=not any(r['可绘制预测点'] for r in availability)
            fig.suptitle(Path(experiment.path).stem + ('\nExperimental data only — no valid saved simulation results' if experiment_only else ''))
            annotation = condition_annotation(experiment, cases)
            _annotate_conditions(fig, [annotation], config)
            stem = f"species-{experiment.id}"
            config['_export_progress']=lambda extension:notify(f'正在导出 {title} / {extension.upper()}')
            paths.extend(_save_figure(fig, directory, stem, config))
            metadata.append({"figure": stem, "experiment": experiment.id, "source": experiment.path,
                             "series": [s.id for s in series_list], "conditions": [annotation], "mechanisms": list(colors)})
            plt.close(fig)
            done+=1
            notify(f'已完成 {title}')
        for kind in ("ignition", "flame"):
            groups = defaultdict(list)
            for experiment in experiments:
                if experiment.kind != kind or (allowed_experiments is not None and experiment.id not in allowed_experiments):
                    continue
                for s in experiment.observations:
                    if selected is None or s.id in selected:
                        groups[s.scan_name].append((experiment, s))
            for scan, entries in groups.items():
                title=f'{kind} / {scan}'
                notify(f'正在绘制 {title}（{len(entries)} 条实验曲线）')
                split=config.get('macro_layout','overlay')=='subplots'
                panel_keys=list(dict.fromkeys((e.id,s.group_id) for e,s in entries)) if split else [None]
                columns=min(max(1,int(config.get('columns',3))),len(panel_keys))
                nrows=math.ceil(len(panel_keys)/columns)
                fig, axes = plt.subplots(nrows,columns,figsize=config.get('macro_figsize',[7*columns,5*nrows]),squeeze=False)
                for i, (experiment, series) in enumerate(entries):
                    notify(f'正在绘制 {title} / {Path(experiment.path).name} / {series.group_id}')
                    ax=axes.flat[panel_keys.index((experiment.id,series.group_id)) if split else 0]
                    label = Path(experiment.path).stem + (" / " + series.group_id if len(experiment.groups) > 1 else "")
                    _plot_series(ax, experiment, series, rows, colors, config,
                                 condition_label=label,
                                 condition_color=config.get("condition_colors", {}).get(experiment.id, palette(i % 10)))
                    if split: ax.set_title(label)
                for ax in list(axes.flat)[len(panel_keys):]: ax.set_visible(False)
                annotations = list(dict.fromkeys(Path(e.path).stem+' — '+condition_annotation(e,cases) for e,_ in entries))
                _annotate_conditions(fig, annotations, config, top=1)
                stem = f"{kind}-{scan.replace(' ', '-')}"
                config['_export_progress']=lambda extension:notify(f'正在导出 {title} / {extension.upper()}')
                paths.extend(_save_figure(fig, directory, stem, config))
                metadata.append({"figure": stem, "series": [s.id for _, s in entries], "conditions": annotations, "mechanisms": list(colors),
                                 "macro_layout":'subplots' if split else 'overlay','panels':[list(p) for p in panel_keys if p is not None]})
                plt.close(fig)
                done+=1
                notify(f'已完成 {title}')
    # Remove only files tracked by the previous render, after a successful new
    # render. Deselected curves must not leave stale figures in the UI/export.
    previous = directory / "figure_sources.json"
    if previous.exists():
        old_stems = {item["figure"] for item in json.loads(previous.read_text(encoding="utf-8"))}
        current = {Path(p).name for p in paths}
        for stem in old_stems:
            for extension in ("png", "pdf", "svg"):
                old = directory / f"{stem}.{extension}"
                if old.name not in current and old.resolve().parent == directory.resolve():
                    old.unlink(missing_ok=True)
    atomic_json(previous, metadata)
    notify('图表绘制与导出完成' if total else '没有可绘制的曲线')
    return paths


def _save_figure(fig, directory, stem, config):
    paths = []
    width,height=fig.get_size_inches()
    if width*height*300**2>25_000_000:
        plt.close(fig)
        raise ValueError('300 dpi 图像超过 2500 万像素，请增加子图列数或减小 figsize。')
    for extension in config.get("formats", ["png", "pdf", "svg"]):
        if extension not in {"png", "pdf", "svg"}:
            raise ValueError("Only PNG/PDF/SVG export is supported")
        path = directory / f"{stem}.{extension}"
        if config.get('_export_progress'): config['_export_progress'](extension)
        fig.savefig(path, dpi=300, bbox_inches="tight")
        paths.append(str(path))
    return paths
