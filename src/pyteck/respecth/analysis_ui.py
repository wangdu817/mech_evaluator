"""Compact case picker; diagnostics execute outside the Streamlit process."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import os
import subprocess
import sys

import numpy as np
import streamlit as st

from .analysis import history_coordinates, analysis_identity
from .atomic_io import atomic_json
from .evaluation import comparison_rows
from .gas_io import load_gas
from .runner import project_root,load_run
from .units import from_si


def diagnostic_candidates(experiments,cases,results,mechanism_id=None,experiment_id=None,include_grid=False):
    result_map={r.case_id:r for r in results}
    rows=comparison_rows(experiments,cases,results)
    deviations={}
    for row in rows:
        if row['residual'] is not None and row['experimental']:
            deviations[row['case_id']]=max(deviations.get(row['case_id'],0),abs(row['residual']/row['experimental']))
    valid=[c for c in cases if c.id in result_map and result_map[c.id].status=='success'
           and result_map[c.id].validation.get('passed') and Path(result_map[c.id].history_path).is_file()
           and (mechanism_id is None or c.mechanism.id==mechanism_id)
           and (experiment_id is None or c.experiment_id==experiment_id)
           and (include_grid or c.role=='scoring')]
    expanded=[]
    for case in valid:
        if case.kind not in {'profile','burner_profile'} or not any('coordinate' in t for t in case.targets):
            expanded.append(case)
            continue
        locations=sorted({(t['group_id'],t['coordinate']) for t in case.targets
                          if include_grid or t.get('role',case.role)=='scoring'})
        for group,coordinate in locations:
            selected=[t for t in case.targets if t['group_id']==group and t['coordinate']==coordinate]
            expanded.append(replace(case,group_id=group,
                condition=replace(case.condition,scan_value=coordinate),
                config={**case.config,'analysis_coordinate':coordinate},
                point_indices=sorted({p for t in selected for p in t['point_indices']}),
                targets=selected+[t for t in case.targets if t not in selected]))
    return sorted(expanded,key=lambda c:(-deviations.get(c.id,-1),c.condition.temperature or 0,c.id,c.condition.scan_value)),deviations,rows


def measurement_display(rows, datasets=None):
    displayed=[]
    for row in rows:
        values={'机理':row.get('mechanism','未记录'),
                'XML':(datasets or {}).get(row.get('experiment_id'),row.get('experiment_id','未记录')),
                'dataGroup':row.get('group_id','未记录'),
                '工况 ID':row.get('case_id','未记录'),
                '温度 (K)':row.get('temperature')}
        values.update({key:row[key] for key in ['species','quantity','instrument','units','status']})
        for key in ('experimental','predicted','residual'):
            values[key]=from_si(row[key],row['units']) if row[key] is not None else None
        displayed.append(values)
    return displayed


@st.fragment(run_every='3s')
def _analysis_poll():
    process=st.session_state.get('analysis_process')
    if process is None or process.poll() is not None:
        st.session_state['analysis_process']=None
        st.rerun()
    directory=Path(st.session_state['analysis_directory'])
    path=directory/'progress.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    st.info('单工况分析运行中 · '+data.get('message','启动独立分析进程'))
    if 'total' in data: st.progress(min(data['done']/max(data['total'],1),1.))
    if st.button('取消单工况分析'):
        (directory/'CANCEL').touch()
        st.caption('已请求取消；已提交结果保留。')


@st.fragment
def _analysis_status():
    directory=st.session_state.get('analysis_directory')
    if not directory: return
    process=st.session_state.get('analysis_process')
    if process is not None and process.poll() is None:
        _analysis_poll()
    elif process is not None and not (Path(directory)/'report.json').exists():
        st.error('分析进程未提交报告，请查看该目录的 analysis.log。')


@st.fragment
def _analysis_progress():
    directory=st.session_state.get('analysis_directory')
    if not directory: return
    process=st.session_state.get('analysis_process')
    if process is not None and process.poll() is None: return
    directory=Path(directory)
    report_path=directory/'report.json'
    if not report_path.exists(): return
    report=json.loads(report_path.read_text(encoding='utf-8'))
    directories=report['analysis_directories'] if 'analysis_directories' in report else st.session_state.get('analysis_directories',[])
    if 'analysis_directories' in report or len(directories)>1:
        if 'analysis_directories' in report:
            st.caption(f"分析任务：{report['status']}，完成 {len(directories)}/{report['total']}；失败/取消 {sum(j['status']!='completed' for j in report['jobs'])}；未开始 {report['pending']}。")
        from .analysis_comparison_ui import render_combined_analysis
        render_combined_analysis(directories)
        return
    st.caption(f"已保存分析：{report['case']['mechanism']['id']} · {report['case']['id'][:12]}；{directory}")
    if report['status']!='completed': st.warning(f"分析状态 {report['status']}：{report.get('reason','')}")
    from .analysis_comparison_ui import render_combined_analysis
    render_combined_analysis([directory])
    rop=report.get('rop',{})
    if rop.get('aggregation')=='domain_integral':
        st.caption('PFR ROP 使用全域积分 ∫omega(t)dt，单位 mol/m³；变密度时不等于出口与入口浓度差。')
        if not rop['quadrature']['passed']: st.warning('ROP 积分网格复核未通过，排名尚未验证。')
    sensitivity=report.get('sensitivity',{})
    if sensitivity:
        st.caption('S=(1/y₀)·∂y/∂ln(m)。正值表示加快反应使目标量增大，负值表示减小。近零目标只报告绝对导数。')
        if sensitivity.get('is_ignition_delay_proxy'): st.caption('温度敏感性是固定时刻的着火诊断代理，不是着火延迟敏感性系数。')
        st.caption('计算方法：'+sensitivity['method'])
        st.caption(f"已分析 {len(sensitivity['reaction_indices'])} 条反应；没有保存的反应不能认定不重要。")
    from .ui_artifacts import deferred_archive
    files=[path for path in directory.rglob('*') if path.is_file() and path.suffix in {'.json','.csv','.png','.pdf','.svg','.h5'}
           and '.previews' not in path.parts and ('views' in path.parts or path.parent==directory)]
    st.download_button('下载单工况分析（CSV、JSON、图表、全物种 HDF5）',deferred_archive(directory,files),
        'case-analysis.zip','application/zip',on_click='ignore')
    st.caption('仅点击下载时打包；超过 64 MiB 请从结果目录读取。')



@st.fragment
def render_analysis_page():
    from .ui_loading import load_results_into_session
    if st.session_state.get('analysis_load_notice'):
        st.success(st.session_state['analysis_load_notice'])
    loaded=st.session_state.get('loaded_run')
    st.caption('沿用已保存的 XML 工况与机理身份，独立保存分析；原机理、模拟缓存和评分不修改。')
    st.caption('新批次仅保留绘图/评分及端点状态。ROP 和点火温度诊断需要的完整历程会临时重建，分析完成后删除；已有兼容分析仍可复用。')
    with st.expander('载入已保存的单工况分析（无需重新计算）'):
        from .analysis_cache import analysis_reports
        archived=sorted(analysis_reports(),key=lambda p:p.stat().st_mtime,reverse=True)
        if archived:
            def archived_label(path):
                data=json.loads(path.read_text(encoding='utf-8'))
                c=data['case']; condition=c['condition']
                return f"{c['mechanism']['id']} · {c['experiment_id']} · T={condition['temperature']:g} K · {data['status']} · {path.parent.name[:8]}"
            selected_reports=st.multiselect('历史工况分析（可多选工况 / 机理）',archived,default=archived[:1],
                format_func=archived_label,max_selections=8,key='saved_analysis_reports',persist_state="session")
            process=st.session_state.get('analysis_process')
            if st.button('载入此分析',disabled=not selected_reports or (process is not None and process.poll() is None)):
                directories=[str(path.parent) for path in selected_reports]
                st.session_state.update(analysis_directory=directories[0],analysis_directories=directories,analysis_process=None)
                st.session_state['analysis_load_notice']=f"已载入 {len(directories)} 份工况分析，无需重新计算。"
                st.success(st.session_state['analysis_load_notice'])
        else:
            st.caption('暂无已保存分析。')
    with st.expander('载入分析用历史批次',expanded=not bool(loaded)):
        source=st.text_input('分析结果目录',value=st.session_state.get('loaded_output',st.session_state.get('output',str(project_root()/'results/ui-run'))),key='analysis_result_source', persist_state="session")
        if st.button('载入到单工况分析'):
            try:
                selected=Path(source).resolve()
                if not selected.is_relative_to(project_root()): raise ValueError('请选择项目内的已有结果目录')
                load_results_into_session(selected)
                st.session_state['analysis_load_notice']=st.session_state['result_load_notice']
                st.rerun()
            except Exception as error: st.error(str(error))
    if not loaded:
        st.info('先载入已有结果，再选择偏差工况。')
        _analysis_status()
        _analysis_progress()
        return
    manifest,experiments,cases,results=loaded
    def multi(label,options,key,default=None,format_func=str,max_selections=None):
        if key in st.session_state:
            previous=st.session_state[key]
            retained=[v for v in previous if v in options]
            st.session_state[key]=retained if retained or not previous else (options[:1] if default is None else default)
        return st.multiselect(label,options,default=None if key in st.session_state else (options[:1] if default is None else default),
            format_func=format_func,key=key,max_selections=max_selections,persist_state="session")
    def fallback(message):
        st.info(message);_analysis_status();_analysis_progress()
    datasets={e.id:Path(e.path).name for e in experiments}
    selected_datasets=multi('实验 set / mix（可多选）',list(datasets),'analysis_datasets_multi',format_func=datasets.get,max_selections=6)
    include_grid=st.checkbox('包含绘图加密工况',key='analysis_grid',persist_state="session")
    valid,deviations,rows=diagnostic_candidates(experiments,cases,results,include_grid=include_grid)
    valid=[c for c in valid if c.experiment_id in selected_datasets]
    if not valid: fallback('所选 set / mix 没有完整且通过验证的成功工况。');return
    groups=sorted({c.group_id for c in valid})
    selected_groups=multi('工况族 / dataGroup（可多选）',groups,'analysis_groups_multi',default=groups) if len(groups)>1 else groups
    valid=[c for c in valid if c.group_id in selected_groups]
    if not valid: fallback('请选择工况族。');return
    scan_labels={'temperature':'温度 T (K)','pressure':'压力 P (Pa)',
        'time':'时间 t (s)', 'distance':'燃烧器轴向位置 z (m)',
        'equivalence ratio':'当量比 phi','residence time':'停留时间 tau (s)'}
    variable=st.selectbox('扫描变量',sorted({c.condition.scan_name for c in valid}),format_func=lambda v:scan_labels.get(v,v),key='analysis_variable',persist_state="session")
    valid=[c for c in valid if c.condition.scan_name==variable]
    values=sorted({c.condition.scan_value for c in valid})
    selected_values=multi('具体变量值（可多选）',values,'analysis_values_multi',
        format_func=lambda v:f"{scan_labels.get(variable,variable)} = {v:.7g}",max_selections=8)
    valid=[c for c in valid if c.condition.scan_value in selected_values]
    mechanisms=sorted({c.mechanism.id for c in valid})
    selected_mechanisms=multi('分析机理（可多选）',mechanisms,'analysis_mechanisms_multi',max_selections=8)
    valid=[c for c in valid if c.mechanism.id in selected_mechanisms]
    if not valid: fallback('请选择变量值和机理。');return
    by_id={(f'{c.id}@{c.group_id}@{c.condition.scan_value!r}' if 'analysis_coordinate' in c.config else c.id):c for c in valid}
    def label(identity):
        c=by_id[identity];point=','.join(str(p+1) for p in c.point_indices) or '加密点'
        return f"{datasets[c.experiment_id]} / {c.mechanism.id} / {c.group_id} / 点 {point} / T={c.condition.temperature:g} K / {identity[:8]}"
    context=tuple(by_id)
    if st.session_state.get('analysis_cases_context')!=context:
        st.session_state.update(analysis_cases_context=context,analysis_cases_multi=list(by_id)[:32])
    selected_ids=multi('匹配工况（可多选，保留重复点）',list(by_id),'analysis_cases_multi',
        default=list(by_id)[:32],format_func=label,max_selections=32)
    selected_cases=[by_id[i] for i in selected_ids]
    if not selected_cases: fallback('请选择至少一个匹配工况。');return
    result_map={r.case_id:r for r in results}
    comparisons=[r for r in rows if any(r['case_id']==c.id and
        ('analysis_coordinate' not in c.config or (r['group_id']==c.group_id and r['scan_value']==c.condition.scan_value))
        for c in selected_cases)]
    st.dataframe(measurement_display(comparisons,datasets),hide_index=True,width='stretch')
    st.caption(f'已选 {len(selected_cases)} 个工况；已有相同分析设置的完成结果自动复用。每次只启动一个分析进程，依次处理。')
    with st.expander('工况、模型和原始身份'):
        st.json([{'case_id':c.id,'condition':asdict(c.condition),'model':c.config,'mechanism':c.mechanism.id} for c in selected_cases])
    mode=st.radio('分析内容',['仅敏感性','仅 ROP','敏感性与 ROP'],horizontal=True,key='analysis_mode',persist_state="session")
    rop_enabled=mode!='仅敏感性';sensitivity=mode!='仅 ROP'
    if sensitivity and any(c.kind=='burner_profile' for c in selected_cases):
        st.info('平焰物种伴随敏感性尚未实现；当前可绘制轴向物种分布，或选择“仅 ROP”分析局部反应速率。')
        return
    temperature_only=sensitivity and not rop_enabled and all(c.kind=='ignition' for c in selected_cases)
    species_names=sorted({name for c in selected_cases for name in c.mechanism.species})
    selected_species=[] if temperature_only else multi('分析物种（可多选，采用机理物种名称）',species_names,'analysis_species_multi',
        default=[next((t['species'] for c in selected_cases for t in c.targets if t.get('species') in species_names),'OH' if 'OH' in species_names else species_names[0])],max_selections=4)
    if any(c.kind=='ignition' for c in selected_cases):
        st.info('点火敏感性目标：Temperature（温度）。默认在各工况的模拟着火延迟时刻计算；这是固定时刻温度敏感性代理，不是着火延迟的导数。')
    if any(c.kind=='flame' for c in selected_cases): st.caption('火焰敏感性目标为火焰速度；ROP 使用选中物种。')
    if rop_enabled: st.caption('PFR ROP 积分整个计算域；JSR 使用稳态，点火使用原着火时刻附近，火焰使用末端状态。')
    top_n=st.number_input('图中显示前 N 条反应',1,30,15,key='analysis_top_n',persist_state="session")
    reaction_text='';floor=1e-20
    if sensitivity:
        st.session_state.setdefault('analysis_reactions','all')
        reaction_text=st.text_input('反应编号（从 1 开始，逗号分隔；全部请输入 all）',key='analysis_reactions',persist_state="session")
        st.caption('一次原生敏感性计算保存全部物种；多选展示物种不增加敏感性积分次数。各机理的反应编号独立解释。')
        if any(c.kind=='jsr' for c in selected_cases):
            st.caption('JSR 固定使用工况的首个观测目标检查敏感性稳态；切换展示物种不会改变该参考目标。其他物种显示同一稳态检查时刻的矩阵。')
        floor=st.number_input('近零目标阈值（目标 SI 单位）',min_value=1e-30,value=1e-20,format='%.2e',key='analysis_floor',persist_state="session")
    row_override=None;time_override=None
    if len(selected_cases)==1:
        chosen=selected_cases[0];chosen_result=result_map[chosen.id]
        try:
            kind,coordinates=history_coordinates(chosen,chosen_result)
            default_row=int(np.argmin(abs(coordinates-next(iter(chosen_result.predictions.values()))))) if chosen.kind=='ignition' else len(coordinates)-1
            if st.session_state.get('analysis_location_context')!=chosen.id:
                st.session_state.update(analysis_location_context=chosen.id,analysis_row=default_row,
                    analysis_time=float(next(iter(chosen_result.predictions.values()))))
            with st.expander('单工况分析位置与时刻（可选）'):
                if 'analysis_coordinate' in chosen.config:
                    st.caption(f"分析所选 {kind}={chosen.config['analysis_coordinate']:.7g}；需要时重建完整曲线。")
                elif rop_enabled and chosen.kind!='pfr':
                    row_override=st.slider('ROP 位置（已保存状态行；精简结果仅入口/出口）',0,len(coordinates)-1,key='analysis_row',persist_state="session")
                    st.caption(f'选中 {kind}={coordinates[row_override]:.7g}。')
                if chosen.kind=='pfr': st.caption(f'ROP 使用全部计算域 0–{coordinates[-1]:.7g} s。')
            if sensitivity and chosen.kind=='ignition':
                time_override=st.number_input('温度敏感性分析时刻 (s)',min_value=1e-15,max_value=float(coordinates[-1]),format='%.7g',key='analysis_time',persist_state="session")
        except Exception as error: st.error(str(error))
    tasks=[];errors=[]
    for c in selected_cases:
        r=result_map[c.id]
        missing=[name for name in selected_species if name not in c.mechanism.species] if rop_enabled or c.kind!='ignition' else []
        if missing: errors.append(f'{c.mechanism.id} 缺少物种：'+', '.join(missing));continue
        try:
            if sensitivity:
                if not reaction_text.strip(): raise ValueError('请填写有效反应编号或 all')
                gas=load_gas(c.mechanism.path,c.mechanism.phase)
                indices=list(range(gas.n_reactions)) if reaction_text.strip().lower()=='all' else list(dict.fromkeys(int(v.strip())-1 for v in reaction_text.split(',') if v.strip()))
                if not indices or any(i<0 or i>=gas.n_reactions for i in indices): raise ValueError('请填写有效反应编号或 all')
                del gas
            coordinate_kind,coordinates=history_coordinates(c,r)
            row=int(np.argmin(abs(coordinates-next(iter(r.predictions.values()))))) if c.kind=='ignition' else len(coordinates)-1
            if row_override is not None: row=row_override
            # Independent components can reuse separate earlier computations,
            # including either component of a previously combined report.
            components=([(None,True)] if sensitivity else []) + ([(name,False) for name in selected_species] if rop_enabled else [])
            for name,is_sensitivity in components:
                settings={'rop':not is_sensitivity,'species':name,'row':row,'top_n':top_n,'sensitivity':is_sensitivity,'zero_floor':floor}
                if settings['sensitivity']:
                    # Display species must not change numerical job identity or
                    # the JSR steady-state reference used by native_reactor.
                    target_key='temperature_at_fixed_time' if c.kind=='ignition' else c.targets[0]['key']
                    settings.update(target_key=target_key,reaction_indices=indices)
                    if c.kind=='ignition': settings['reference_time']=time_override if time_override is not None else float(next(iter(r.predictions.values())))
                tasks.append((c,r,settings))
        except Exception as error: errors.append(f'{c.mechanism.id} / {c.id[:8]}：{error}')
    for error in dict.fromkeys(errors):
        if sensitivity and not reaction_text.strip(): st.caption(error)
        else: st.error(error)
    process=st.session_state.get('analysis_process');busy=process is not None and process.poll() is None
    batch=st.session_state.get('worker');batch_busy=batch is not None and batch.is_alive()
    from .run_ownership import run_owner
    batch_busy=batch_busy or run_owner(st.session_state.get('output'))['active']
    with st.container(border=True):
        plan=[]
        if tasks and not errors and not busy:
            try:
                from .analysis_cache import reusable_directory, numeric_signature
                from .models import digest
                payloads=[{'case':asdict(c),'result':asdict(r),'settings':settings,
                           'source_run':st.session_state.get('loaded_output',''),
                           'comparison':[v for v in comparisons if v['case_id']==c.id]} for c,r,settings in tasks]
                from .analysis_cache import analysis_reports
                inventory=[(str(p),p.stat().st_mtime_ns,p.stat().st_size) for report in analysis_reports()
                           for p in (report,report.parent/'job.json',report.parent/'all_species_sensitivity.h5') if p.exists()]
                histories=[(r.history_path,Path(r.history_path).stat().st_mtime_ns,Path(r.history_path).stat().st_size) for _,r,_ in tasks]
                signature=digest({'payloads':payloads,'histories':histories,'inventory':inventory,'engine':numeric_signature()})
                if st.session_state.get('analysis_cache_plan_signature')!=signature:
                    plan=[{'payload':payload,'cached':reusable_directory(payload,component='sensitivity' if payload['settings']['sensitivity'] else 'rop')}
                          for payload in payloads]
                    st.session_state.update(analysis_cache_plan_signature=signature,analysis_cache_plan=plan)
                else:
                    plan=st.session_state['analysis_cache_plan']
                cached=list(dict.fromkeys(str(item['cached']) for item in plan if item['cached']))
                hits=sum(bool(item['cached']) for item in plan)
                st.caption(f'当前分析任务 {len(plan)} 个：已有缓存 {hits} 个，需新计算 {len(plan)-hits} 个。')
                if st.session_state.get('analysis_auto_selection')!=signature:
                    st.session_state['analysis_auto_selection']=signature
                    st.session_state.update(analysis_directory=cached[0] if cached else '',analysis_directories=cached,
                        analysis_compare_mode='sensitivity' if sensitivity else 'rop')
                    display_species=['Temperature'] if sensitivity and all(c.kind=='ignition' for c in selected_cases) else selected_species.copy()
                    st.session_state['analysis_compare_species_'+('sensitivity' if sensitivity else 'rop')]=display_species
                    st.session_state['analysis_load_notice']=f'已自动载入 {hits} 个匹配分析任务的缓存；无需重新积分。' if hits else ''
                if hits:
                    st.success(f'已自动载入匹配缓存（{hits}/{len(plan)}）；可直接查看下方图表。')
            except Exception as error:
                st.error(f'分析缓存检查失败：{error}')
        if st.button('分析选中工况',disabled=busy or batch_busy or bool(errors) or not tasks or (not selected_species and not temperature_only) or not plan or all(item['cached'] for item in plan)):
            try:
                jobs=[];directories=[]
                for c,r,settings in tasks:
                    payload={'case':asdict(c),'result':asdict(r),'settings':settings,
                        'source_run':st.session_state.get('loaded_output',''),'comparison':[v for v in comparisons if v['case_id']==c.id]}
                    from .analysis_cache import reusable_directory
                    reusable=reusable_directory(payload,component='sensitivity' if settings['sensitivity'] else 'rop')
                    from .project_storage import analysis_destination
                    directory=reusable or analysis_destination(project_root(),st.session_state,'analysis',analysis_identity(c,r,settings))
                    if not reusable and (directory/'report.json').exists():
                        # Never trust or overwrite a report rejected by the
                        # provenance/matrix checks just because its folder matches.
                        import uuid
                        directory=directory.with_name(directory.name+'-'+uuid.uuid4().hex[:12])
                    directory.mkdir(parents=True,exist_ok=True);directories.append(str(directory))
                    if not reusable: atomic_json(directory/'job.json',payload)
                    jobs.append({'job':str(directory/'job.json'),'label':f'{datasets[c.experiment_id]} / {c.mechanism.id} / T={c.condition.temperature:g} K / {settings["species"] or "sensitivity"}'})
                st.session_state['analysis_directories']=[]
                if len(jobs)==1:
                    directory=Path(directories[0]);module='pyteck.respecth.analysis_job';job_path=directory/'job.json'
                    saved=json.loads((directory/'report.json').read_text(encoding='utf-8')) if (directory/'report.json').exists() else {}
                    if saved.get('status')=='completed':
                        st.session_state.update(analysis_directory=str(directory),analysis_process=None)
                        st.session_state['analysis_load_notice']='已载入相同设置的已有分析，无需重新计算。'
                        st.rerun()
                else:
                    from .models import digest
                    directory=analysis_destination(project_root(),st.session_state,'analysis-batches',digest(jobs))
                    directory.mkdir(parents=True,exist_ok=True);module='pyteck.respecth.analysis_batch_job';job_path=directory/'jobs.json'
                    atomic_json(job_path,{'jobs':jobs})
                    (directory/'report.json').unlink(missing_ok=True)
                (directory/'CANCEL').unlink(missing_ok=True)
                st.session_state['analysis_directory']=str(directory)
                with (directory/'analysis.log').open('wb') as log:
                    st.session_state['analysis_process']=subprocess.Popen([sys.executable,'-m',module,str(job_path)],cwd=project_root(),stdout=log,stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                st.rerun()
            except Exception as error: st.error(str(error))
        _analysis_status()
    _analysis_progress()
