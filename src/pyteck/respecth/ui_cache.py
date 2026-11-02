"""On-demand cache controls; scanning never runs on live progress ticks."""
import streamlit as st
from pathlib import Path
from .cache_maintenance import LABELS,inventory,cleanup,busy_reasons,release_views


def summary(data):
    return [{'类型':label,'文件数':sum(i['category']==key for i in data['items']),
             '大小 (MiB)':round(sum(i['bytes'] for i in data['items'] if i['category']==key)/2**20,2)}
            for key,label in LABELS.items()]


def render_cache_controls(root):
    with st.sidebar.expander('缓存与内存管理',key='cache_controls',on_change='rerun') as panel:
        if not panel.open: return
        st.caption('保留模拟结果、HDF5 历程、敏感性/ROP、快照、机理与配置。运行中暂停清理。')
        notice=st.session_state.get('cache_cleanup_notice')
        if notice: st.info(notice)
        if st.button('检查缓存占用'):
            data=inventory(root)
            st.session_state['cache_usage_rows']=summary(data)
            st.session_state['cache_scan_errors']=data['errors'][:5]
            st.success('缓存检查完成。大小按文件逻辑大小统计；硬链接不等于实际占用。')
        if st.session_state.get('cache_usage_rows'):
            st.dataframe(st.session_state['cache_usage_rows'],hide_index=True,width='stretch')
        for error in st.session_state.get('cache_scan_errors',[]): st.warning(error)
        selected=st.multiselect('选择可重新生成的缓存',list(LABELS),default=['obsolete'],
            format_func=LABELS.get,key='cache_cleanup_types',persist_state='session')
        st.caption('清理预览会在下次查看时重新生成；清理 ZIP 不删除其中的原文件。开发缓存可能需要重新构建。')
        if st.button('清理所选缓存',disabled=not selected):
            report=cleanup(root,selected)
            if report['blocked']:
                st.warning('当前任务仍在运行，未清理：'+'；'.join(report['blocked']))
            else:
                message=f"清理完成：{report['deleted']} 个文件，移除约 {report['bytes']/2**20:.2f} MiB（实际磁盘释放可能不同）。"
                st.session_state['cache_cleanup_notice']=message
                st.session_state.pop('cache_usage_rows',None)
                st.success(message);st.toast(message,icon='✅')
            for error in report['errors'][:5]: st.warning(error)
        if st.button('释放当前载入结果的内存'):
            reasons=busy_reasons(root)
            if reasons: st.warning('计算中未释放视图：'+'；'.join(reasons))
            else:
                try:
                    count=release_views(st.session_state)
                    st.cache_data.clear()
                    st.session_state['cache_cleanup_notice']=f'已卸载 {count} 项结果与计划引用，并清理数据缓存；磁盘结果保留，需要时重新载入。进程内存不一定立即下降。'
                    st.rerun()
                except ValueError as error: st.warning(str(error))
        if st.button('检查未保存的临时会话'):
            from .project_storage import temporary_sessions
            st.session_state['temporary_session_choices']=temporary_sessions(root)
            st.success('临时会话检查完成。已保存项目不在清理范围内。')
        sessions=st.session_state.get('temporary_session_choices',[])
        if sessions:
            options={s['directory']:s for s in sessions}
            chosen=st.multiselect('待删除的未保存会话',list(options),
                format_func=lambda p:f"{options[p]['created']} · {options[p]['bytes']/2**20:.1f} MiB · {Path(p).name[:8]}",key='discard_session_selection')
            confirmed=st.checkbox('确认舍弃所选未保存结果（不可恢复）',key='discard_session_confirm')
            if st.button('删除所选临时会话',disabled=not chosen or not confirmed):
                from .project_storage import discard_sessions
                try:
                    count=discard_sessions(root,chosen,protected=[st.session_state.get(k) for k in ('session_workspace','loaded_output','analysis_directory')])
                    st.success(f'已移除 {count} 个临时目录；已保存项目保留。')
                    st.session_state.pop('temporary_session_choices',None)
                except ValueError as error: st.error(str(error))
