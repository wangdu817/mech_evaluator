"""Explicit scan grids and their Streamlit configuration controls."""
import heapq
import math
import numpy as np


def scan_grid(xs, options, kind, scan_name):
    xs = np.unique(xs)
    mode = options.get('mode', 'legacy')
    if mode == 'step':
        step = options.get('steps', {}).get(scan_name, options.get('step'))
        if not isinstance(step, (int, float)) or isinstance(step, bool) or not math.isfinite(step) or step <= 0:
            raise ValueError(f'{scan_name}: 请设置大于零的有限变量间隔（内部单位）')
        ratio = (xs[-1] - xs[0]) / step
        if not math.isfinite(ratio) or ratio > 10000:
            raise ValueError('变量间隔过小：每组最多 10000 个工况')
        count = int(math.floor(ratio)) + 1
        if count + len(xs) > 10000:
            raise ValueError('变量间隔过小：每组最多 10000 个工况')
        return np.unique(np.r_[xs, xs[0] + np.arange(count) * step])
    count = options.get('points', 25 if kind == 'flame' else 100)
    if not isinstance(count, int) or isinstance(count, bool) or not 2 <= count <= 10000:
        raise ValueError('grid.points must be an integer from 2 to 10000')
    if mode == 'legacy':
        return np.unique(np.r_[xs, np.linspace(xs[0], xs[-1], count)])
    if mode != 'count':
        raise ValueError(f'Unknown grid.mode: {mode}')
    # Preserve every original coordinate; repeatedly divide the largest gap.
    points = list(xs)
    gaps = [(-(b-a), a, b) for a, b in zip(xs[:-1], xs[1:])]
    heapq.heapify(gaps)
    while len(points) < count and gaps:
        _, a, b = heapq.heappop(gaps)
        mid = (a+b)/2
        if not a < mid < b:
            continue
        points.append(mid)
        heapq.heappush(gaps, (-(mid-a), a, mid))
        heapq.heappush(gaps, (-(b-mid), mid, b))
    return np.sort(points)


def render_grid_controls(data, root):
    import streamlit as st
    import yaml
    from .reader import load_experiment
    options = data.get('grid', {})
    entries = data.get('mechanisms', [])
    choices = ['全部机理（统一设置）'] + [entry['id'] for entry in entries]
    target = st.selectbox('加密设置应用范围', choices, key='grid_mechanism_target', persist_state='session')
    if target != choices[0]:
        selected_entry = next(entry for entry in entries if entry['id'] == target)
        options = selected_entry.get('grid', options)
    st.caption('可为新机理单独设置网格；其他机理的设置与已有结果保留。相同工况直接复用，新增网格点才需要求解。')
    signature = target + yaml.safe_dump(options, sort_keys=True)
    if st.session_state.get('grid_controls_source') != signature:
        st.session_state['grid_controls_source'] = signature
        st.session_state['grid_enabled_input'] = options.get('enabled', False)
        st.session_state['grid_mode_input'] = '变量间隔' if options.get('mode') == 'step' else '总点数'
        st.session_state['grid_count_input'] = int(options.get('points', 100))
        for name, _, factor, default in SCANS:
            st.session_state['grid_step_' + name] = float(options.get('steps', {}).get(name, options.get('step', default * factor))) / factor
    st.subheader('绘图加密工况')
    st.caption('默认无加密：仅模拟 XML 中的实验工况点，绘图时连接这些计算点。需要更密集的模拟曲线时，再启用下方选项。')
    enabled = st.checkbox('增加绘图模拟点', key='grid_enabled_input', persist_state="session")
    mode = st.radio('加密方式', ['总点数', '变量间隔'], horizontal=True, key='grid_mode_input', disabled=not enabled, persist_state="session")
    if mode == '总点数':
        st.number_input('每组总点数（包含原始实验坐标）', min_value=2, max_value=10000, step=1, key='grid_count_input', disabled=not enabled, persist_state="session")
        st.caption('原始坐标全部保留；原始坐标数超过设定总量时，仅使用原始坐标。')
    else:
        names = set()
        for path in data.get('datasets', []):
            try:
                names.update(g.scan_name for g in load_experiment(root / path).groups)
            except (OSError, ValueError):
                pass
        for name, label, factor, default in SCANS:
            if name in names or not names:
                st.number_input(label, min_value=0.000001, format='%g', key='grid_step_' + name, disabled=not enabled, persist_state="session")
        st.caption('从各组最小值开始按间隔生成，保留原始坐标和终点，不外推。例如温度填 20 表示 20 K，当量比填 0.1。')
    st.caption('只影响绘图工况；评分仍使用原始实验点。变化的入口组成、停留时间等仍需明确生成规则。')
    if st.button('应用加密设置'):
        grid = {**options, 'enabled': enabled, 'mode': 'count' if mode == '总点数' else 'step'}
        if mode == '总点数':
            grid['points'] = st.session_state['grid_count_input']
        else:
            grid['steps'] = {name: st.session_state.get('grid_step_' + name, options.get('steps', {}).get(name, default * factor) / factor) * factor for name, _, factor, default in SCANS}
        if target == choices[0]:
            data['grid'] = grid
            for entry in entries:
                entry.pop('grid', None)
        else:
            selected_entry['grid'] = grid
        st.session_state['config_text'] = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        from .ui_feedback import action_success
        detail = ('每组总点数 ' + str(grid['points'])) if mode == '总点数' else '按变量间隔生成'
        if not enabled:
            detail = '已关闭绘图加密，仅使用原始实验工况'
        action_success(f'加密设置已应用到 {target}：{detail}。已更新当前运行配置；点击“预检查并保存配置”写入文件。')
        st.rerun()


SCANS = [('temperature', '温度间隔（K）', 1., 20.),
         ('time', '时间间隔（s）', 1., 1e-5),
         ('distance', '轴向距离间隔（mm）', .001, .1),
         ('equivalence ratio', '当量比间隔', 1., .1),
         ('pressure', '压力间隔（atm）', 101325., .1),
         ('residence time', '停留时间间隔（s）', 1., .01)]
