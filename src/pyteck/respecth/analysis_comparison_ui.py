"""Combined saved-analysis view inside the existing case analysis page."""
from pathlib import Path
import json
import streamlit as st
from .analysis_comparison import available_species, export_comparison, comparison_series, comparison_figure
from .models import digest, file_hash
from .runner import project_root
from .ui_artifacts import preview_image


@st.fragment
def render_combined_analysis(directories):
    reports=[]
    for directory in directories:
        path=Path(directory)/'report.json'
        if path.is_file():
            report=json.loads(path.read_text(encoding='utf-8'))
            if report.get('status')=='completed' and report.get('case'):
                reports.append((path,report))
    if not reports:
        st.info('尚无已完成的工况分析可展示。');return
    st.caption(f'已载入 {len(reports)} 份工况分析；只读取已有结果。同机理同目标合并工况，不同机理或物种分别显示子图。')
    modes=[m for m in ['sensitivity','rop'] if any(r.get(m) for _,r in reports)]
    if not modes: return
    mode=st.radio('展示分析结果',modes,format_func=lambda m:{'sensitivity':'敏感性','rop':'ROP'}[m],
        horizontal=True,key='analysis_compare_mode',persist_state='session')
    names=sorted({s for _,r in reports for s in available_species(r,mode)})
    if not names: st.info('未保存所选类型的结果。');return
    preferred='Temperature' if mode=='sensitivity' and any(r.get('sensitivity',{}).get('is_ignition_delay_proxy') for _,r in reports) else next((t.get('species') for _,r in reports for t in r['case'].get('targets',[])
                    if t.get('species') in names),names[0])
    key='analysis_compare_species_'+mode
    if key in st.session_state: st.session_state[key]=[s for s in st.session_state[key] if s in names]
    species=st.multiselect('展示物种 / 目标（可多选）',names,default=None if key in st.session_state else [preferred],max_selections=4,
        key=key,persist_state='session')
    quantity='X';metric='net'
    if mode=='sensitivity':
        st.caption('已分析反应数：'+'；'.join(f"{r['case']['mechanism']['id']} / {r['case']['id'][:8]}：{len(r['sensitivity'].get('reaction_indices',r['sensitivity']['rows']))}" for _,r in reports if r.get('sensitivity'))+'。各来源反应覆盖可能不同，未分析反应不能认定不重要。')
        if species and all(name=='Temperature' for name in species):
            quantity='temperature'
            st.caption('当前目标为温度 T（K），显示归一化温度敏感性 S_T。')
        else:
            quantity=st.selectbox('对比敏感性变量',['X','C','Y'],format_func=lambda v:{'X':'实际摩尔分数','C':'摩尔浓度','Y':'质量分数'}[v],
                                 key='analysis_compare_quantity',persist_state='session')
    else:
        metric=st.selectbox('ROP 对比量',['net','formation','destruction'],
            format_func=lambda v:{'net':'净生成速率','formation':'生成速率','destruction':'消耗速率（绘制为负）'}[v],
            key='analysis_compare_metric',persist_state='session')
        st.caption('PFR 使用全域积分值；其他反应器使用保存的局部状态。不同单位或积分方式分成子图。只能选择已保存的 ROP 物种。')
    limit=st.number_input('对比图显示前 N 条反应',1,30,15,key='analysis_compare_limit',persist_state='session')
    columns=st.number_input('对比图每行子图数',1,2,2,key='analysis_compare_columns',persist_state='session')
    config={'sources':[{ 'path':str(p),'sha256':file_hash(p)} for p,_ in reports],
            'mode':mode,'species':species,'quantity':quantity,'rop_metric':metric,'limit':limit,'columns':columns}
    identity=digest(config)
    if st.button('绘制与导出分析对比（无需计算）',disabled=not species):
        try:
            from .project_storage import analysis_destination
            directory=analysis_destination(project_root(),st.session_state,'analysis-comparisons',identity)
            omitted=export_comparison(reports,directory,mode,species,quantity,metric,limit,columns)
            st.session_state['analysis_comparison_view']=(str(directory),identity)
            from .ui_feedback import action_success
            action_success(f'分析对比图及 CSV、JSON 已导出至 {directory}；没有重新求解。')
            st.success(f'分析对比图已保存：{directory}')
            for message in omitted: st.warning(message)
        except Exception as error: st.error(str(error))
    if species:
        import matplotlib.pyplot as plt
        try:
            series,omitted=comparison_series(reports,mode,species,quantity,metric)
            figure,rows=comparison_figure(series,limit,columns)
            try: st.pyplot(figure,width='stretch')
            finally: plt.close(figure)
            for message in omitted: st.warning(message)
            if any(e['mode']=='rop' and e['data'].get('aggregation')=='domain_integral'
                   and not e['data'].get('quadrature',{}).get('passed',False) for e in series):
                st.warning('部分 PFR 积分网格复核未通过，当前 ROP 排名尚未验证。')
            st.caption('同子图按各工况最大绝对值排序，颜色和填充表示工况；× 表示没有保存该反应的值，不能解释为零。')
            with st.expander('图中数据表（含工况与反应身份）'): st.dataframe(rows,hide_index=True,width='stretch')
        except Exception as error: st.error(str(error))
    saved=st.session_state.get('analysis_comparison_view')
    if saved and saved[1]==identity:
        with st.expander('导出文件位置'):
            st.write(saved[0]);st.caption('comparison.png / .pdf / .svg / .csv / .json')
