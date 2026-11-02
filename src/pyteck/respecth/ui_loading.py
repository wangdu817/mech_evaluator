"""Shared immediate loading and visible confirmation for every result entry point."""
from pathlib import Path
import streamlit as st
import yaml
from .result_access import load_result_view
from .yaml_io import load_yaml
from .reporting import export_run_summary


def load_results_into_session(output, *, completed_snapshot=False):
    source = str(Path(output).resolve())
    output, loaded = load_result_view(output, completed_snapshot=completed_snapshot)
    work=Path(output)
    if st.session_state.get('session_workspace'):
        import hashlib
        import shutil
        work=Path(st.session_state['session_workspace'])/'views'/hashlib.sha256(str(output).encode()).hexdigest()[:12]
        work.mkdir(parents=True,exist_ok=True)
        for name in ('figure.yaml','scoring.yaml'):
            if (Path(output)/name).is_file() and not (work/name).exists(): shutil.copy2(Path(output)/name,work/name)
        # Saved project media remains read-only; seed the temporary view once.
        if (Path(output)/'figures').is_dir() and not (work/'figures').exists():
            shutil.copytree(Path(output)/'figures',work/'figures',ignore=shutil.ignore_patterns('.previews'))
        manifest=dict(loaded[0]);manifest['config']={**manifest['config'],'output':str(work)}
        loaded=(manifest,*loaded[1:])
    st.session_state['loaded_work_output']=str(work)
    st.session_state["loaded_run"] = loaded
    st.session_state["loaded_output"] = str(output)
    # Apply this widget value before it is rendered on the next rerun, not
    # after the result-directory textbox has already been instantiated.
    st.session_state["pending_saved_result_output"] = source
    from pyteck.respecth.result_library import save_result_view
    save_result_view(output)
    st.session_state.pop("mechanisms_initialized_output",None)
    directory = work
    manifest = st.session_state["loaded_run"][0]
    export_run_summary(manifest)
    scoring = load_yaml((directory / "scoring.yaml").read_text(encoding="utf-8")) if (directory / "scoring.yaml").exists() else manifest["config"].get("scoring", {})
    st.session_state["score_text"] = yaml.safe_dump(scoring, allow_unicode=True)
    figure = load_yaml((directory / "figure.yaml").read_text(encoding="utf-8")) if (directory / "figure.yaml").exists() else manifest["config"].get("figure", {})
    series = [s.id for e in st.session_state["loaded_run"][1] for s in e.observations]
    st.session_state.update(figure_series=[s for s in figure.get("series", series) if s in series],
        figure_macro_layout=figure.get('macro_layout','overlay'),
        figure_columns=figure.get("columns", 3), figure_unit=figure.get("composition_unit", "ppm"),
        figure_reciprocal=figure.get("reciprocal_temperature", True), figure_legend=figure.get("legend", True),
        figure_conditions=figure.get('conditions', True), figure_conditions_position=figure.get('conditions_position','bottom'),
        figure_conditions_fontsize=float(figure.get('conditions_fontsize',8)),
        figure_linewidth=float(figure.get("linewidth", 1.5)), figure_extra=yaml.safe_dump({k:v for k,v in figure.items() if k not in {"series", "columns", "composition_unit", "reciprocal_temperature", "legend", "linewidth", "conditions", "conditions_position", "conditions_fontsize", "mechanisms"}}, allow_unicode=True))
    selected_series = set(figure.get('series', series))
    st.session_state['figure_datasets'] = figure.get('experiments', [e.id for e in st.session_state['loaded_run'][1]
        if any(s.id in selected_series for s in e.observations)])
    st.session_state['figure_specific'] = figure.get('specific_series', False)
    st.session_state['conditions_initialized_output'] = output

    manifest, experiments, cases, results = st.session_state['loaded_run']
    verified=sum(r.status=='success' and r.validation.get('passed') is True for r in results)
    message=(f"载入成功：{len(experiments)} 份 XML · {len(cases)} 个工况 · "
             f"数值验证通过 {verified}，其他或待完成 {len(cases)-verified}；"
             f"机理：{', '.join(sorted({c.mechanism.id for c in cases}))}。")
    if manifest.get('snapshot'):
        info = manifest['snapshot']
        activity = '原任务继续运行；' if info.get('source_status') == 'running' else f"来源任务状态：{info.get('source_status', '未知')}；"
        message = (f"载入成功（已完成结果快照）：已提交 {info['committed_cases']}/{len(cases)} · "
                   f"数值验证通过 {verified} · 待完成 {info['pending_cases']}。"
                   f"{activity}可用于部分结果评分、绘图和单工况分析。正式总榜需完整结果；点击“载入 / 刷新计算结果”刷新新增结果。")
    st.session_state['result_load_notice']=message
    st.session_state['result_load_directory']=str(Path(output).resolve())
    st.toast(message,icon='✅')
    return st.session_state['loaded_run']


def show_result_load_notice():
    if st.session_state.get('result_load_notice'):
        st.success(st.session_state['result_load_notice'])
