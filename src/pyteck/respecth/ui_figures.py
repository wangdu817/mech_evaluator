"""All saved figures by default, using bounded previews rather than full exports."""
from pathlib import Path
import streamlit as st
from .ui_artifacts import preview_image


def render_saved_figures(directory):
    images = sorted(Path(directory).glob('*.png'))
    if not images:
        st.info('暂无已保存图表。选择数据集后点击“保存设置并重绘”。')
        return
    st.subheader(f'已保存图表（共 {len(images)} 张）')
    mode = st.radio('图表展示方式', ['全部图表', '单张查看'], horizontal=True,
                    key='figure_display_mode', persist_state='session')
    if mode == '单张查看':
        if st.session_state.get('figure_preview_file') not in images:
            st.session_state['figure_preview_file'] = images[0]
        selected = st.selectbox('选择已保存图表', images, format_func=lambda p: p.name,
                                key='figure_preview_file', persist_state='session')
        images = [selected]
        columns = 1
    else:
        columns = st.number_input('每行图片数', min_value=1, max_value=3, value=1,
                                  key='figure_gallery_columns', persist_state='session')
        st.caption('全部图片在下方展示，向下滚动即可查看；可调整每行图片数。预览压缩不影响原 PNG、PDF、SVG 导出质量。')
    progress=st.progress(0.,text=f'正在载入图表预览：0/{len(images)} 张') if len(images)>1 else None
    panels = st.columns(columns)
    for index, path in enumerate(images):
        if progress is not None:
            progress.progress(index/len(images),text=f'正在载入预览 {index+1}/{len(images)} · {path.name}')
        with panels[index % columns]:
            try:
                # Only one source image is decoded at a time. Browser media is
                # bounded by preview resolution; no full-resolution image list.
                st.image(preview_image(path, max_side=1200 if mode == '全部图表' else 1400),
                         caption=path.name, alt=path.stem, width='stretch')
            except (OSError, ValueError) as error:
                st.warning(f'{path.name}：无法生成预览：{error}；原导出文件保留。')
    if progress is not None:
        progress.progress(1.,text=f'图表预览处理完成：{len(images)}/{len(images)} 张')
