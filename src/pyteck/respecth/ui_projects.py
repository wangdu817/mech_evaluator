"""Explicit project save/open controls; new GUI runs stay in temporary storage."""
from pathlib import Path
import json
import streamlit as st
from .project_storage import new_session,save_project
from .cache_maintenance import busy_reasons


def render_project_controls(root):
    with st.sidebar.expander('项目：保存 / 打开',key='project_controls',on_change='rerun') as panel:
        if not panel.open: return
        if st.session_state.get('opened_project_directory'):
            st.caption('已打开项目：'+Path(st.session_state['opened_project_directory']).name+'。后续新结果仍写入临时工作区，需另存项目才能保留更新。')
        else:
            st.caption('当前为未保存会话。新模拟、分析和图表先写入临时工作区，用于查看和恢复；只有点击保存才成为已保存项目。历史结果保留。')
        st.text_input('项目名称',key='project_save_name',persist_state='session')
        results=st.checkbox('保存模拟结果（绘图、评分与端点状态）',value=True,key='project_include_results',persist_state='session')
        analyses=st.checkbox('保存当前分析结果（敏感性 / ROP）',value=True,key='project_include_analysis',persist_state='session')
        figures=st.checkbox('保存图表',value=True,key='project_include_figures',persist_state='session')
        if st.button('保存项目'):
            try:
                source=st.session_state.get('loaded_output') or st.session_state.get('output')
                directories=list(st.session_state.get('analysis_directories',[]))
                if not directories and st.session_state.get('analysis_directory'):
                    directories=[st.session_state['analysis_directory']]
                expanded=[]
                for value in directories:
                    report_path=Path(value)/'report.json'
                    report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
                    expanded.extend(report.get('analysis_directories',[value]))
                comparison=st.session_state.get('analysis_comparison_view')
                from .yaml_io import load_yaml
                with st.spinner('正在保存项目及其结果依赖…'):
                    path=save_project(root,st.session_state.get('project_save_name',''),
                        run_output=source,analyses=expanded,comparison=comparison[0] if comparison else None,
                        postprocessing=st.session_state.get('loaded_work_output'),include_results=results,
                        include_analysis=analyses,include_figures=figures,
                        config=load_yaml(st.session_state.get('config_text','')) or {})
                st.session_state['project_notice']=f'项目保存成功：{path}。后续计算仍为临时结果，需另存项目才能保留更新。'
                st.success(st.session_state['project_notice']);st.toast('项目保存成功',icon='✅')
            except Exception as error: st.error(str(error))
        if st.session_state.get('project_notice'): st.caption(st.session_state['project_notice'])
        choices=sorted((root/'results/projects').glob('*/project.json'))
        if choices:
            selected=st.selectbox('已保存项目',choices,format_func=lambda p:p.parent.name,key='project_open_choice')
            if st.button('打开所选项目'):
                try:
                    if reasons:=busy_reasons(root): raise ValueError('任务运行中，不能切换项目：'+'；'.join(reasons))
                    directory=selected.parent
                    from .cache_maintenance import release_views
                    release_views(st.session_state)
                    if (directory/'simulation/manifest.json').is_file():
                        from .ui_loading import load_results_into_session
                        load_results_into_session(directory/'simulation')
                    st.session_state['opened_project_directory']=str(directory)
                    st.session_state['config_text']=(directory/'config.yaml').read_text(encoding='utf-8')
                    from .yaml_io import load_yaml
                    import yaml
                    config=load_yaml(st.session_state['config_text']) or {}
                    st.session_state.update(mechanism_entries=config.get('mechanisms',[]),
                        mechanism_list_yaml=yaml.safe_dump(config.get('mechanisms',[]),allow_unicode=True),
                        input_datasets=config.get('datasets',[]))
                    analyses_paths=[str(p.parent) for p in sorted((directory/'analysis').glob('*/report.json'))]
                    if analyses_paths:
                        st.session_state.update(analysis_directories=analyses_paths,analysis_directory=analyses_paths[0],analysis_process=None)
                        st.session_state['analysis_cache_plan_signature']=None
                    else:
                        for key in ('analysis_directories','analysis_directory','analysis_comparison_view'): st.session_state.pop(key,None)
                    st.session_state['project_notice']=f'项目已打开：{directory.name}；不重新计算。'
                    st.toast(st.session_state['project_notice'],icon='✅')
                    st.rerun()
                except Exception as error: st.error(str(error))
        if st.button('开始新的临时会话'):
            if reasons:=busy_reasons(root): st.warning('请先结束任务：'+'；'.join(reasons))
            else:
                from .cache_maintenance import release_views
                release_views(st.session_state)
                workspace=new_session(root)
                st.session_state.update(session_workspace=str(workspace),output=str(workspace/'simulation'),
                    project_notice='已开始新临时会话。旧临时文件尚未删除，可在缓存管理中选择清理。')
                st.session_state.pop('checked_text',None)
                from .project_storage import remember_session
                remember_session(root,st.session_state)
                st.rerun()


def render_project_figures():
    """A figures-only project can be viewed without a simulation manifest."""
    source=st.session_state.get('opened_project_directory')
    if not source: return False
    directory=Path(source)
    workspace=st.session_state.get('session_workspace')
    if workspace:
        import hashlib
        import shutil
        view=Path(workspace)/'project-figures'/hashlib.sha256(str(directory).encode()).hexdigest()[:12]
        if not view.exists():
            for path in directory.rglob('*.png'):
                if '.previews' in path.parts: continue
                target=view/path.relative_to(directory)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target)
        directory=view
    groups=sorted({p.parent for p in directory.rglob('*.png') if '.previews' not in p.parts})
    if not groups: return False
    selected=st.selectbox('项目图表组',groups,format_func=lambda p:str(p.relative_to(directory)),key='project_figure_group')
    from .ui_figures import render_saved_figures
    render_saved_figures(selected)
    return True
