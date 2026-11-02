"""Local Streamlit research UI. Long calculations live outside rerun execution."""
from __future__ import annotations
from pathlib import Path
import json
import queue
import threading
import traceback
import os
import sys
import hashlib
from datetime import datetime, timezone
from collections import Counter

import streamlit as st
import yaml
import pandas as pd
import psutil
from pyteck.respecth.yaml_io import load_yaml

from pyteck.respecth import discover_experiments, load_experiment, RunConfig
from pyteck.respecth.runner import project_root, prepare_run, run_project, load_run
from pyteck.respecth.cases import dataset_config
from pyteck.respecth.evaluation import evaluate_results
from pyteck.respecth.reporting import render_figures, export_results, summarize_run, export_run_summary, plot_availability
from pyteck.respecth.atomic_io import atomic_json
from pyteck.respecth.ui_summary import scope_summary, score_chart_rows, case_status_rows
from pyteck.respecth.ui_loading import load_results_into_session, show_result_load_notice
from pyteck.respecth.ui_feedback import show_action_notice, action_success, clear_action_notice
from pyteck.respecth.mechanism_intake import validate_mechanism_input
from pyteck.respecth.run_ownership import run_owner, restore_run_state, cancel_run


def _worker(config, events, cancellation, force_rerun=False, discard_previous=False):
    try:
        manifest = run_project(config, lambda n, total, identity, status: events.put(("progress", n, total, status, identity)), cancellation, force_rerun=force_rerun, discard_previous=discard_previous)
        events.put(("done", manifest["status"]))
    except FileExistsError as error:
        if error.filename and Path(error.filename).name=='run.lock':
            events.put(('error', '该结果目录已有任务正在运行，请刷新查看现有任务；未启动重复计算，也未修改已有结果。'))
        else:
            events.put(('error',traceback.format_exc()))
    except Exception:
        events.put(("error", traceback.format_exc()))


def _uploaded_file(upload, root):
    """Content-addressed local copies; upload names cannot escape the project."""
    if upload is None:
        return ''
    content = upload.getvalue()
    name = Path(upload.name.replace('\\', '/')).name
    destination = root / 'inputs' / 'uploads' / hashlib.sha256(content).hexdigest() / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(content)
    return str(destination)


def _mechanism_picker(root, notice_slot=None):
    if 'pending_mechanisms' in st.session_state:
        st.session_state['mechanism_entries'] = st.session_state.pop('pending_mechanisms')
        st.session_state['mechanism_list_yaml'] = yaml.safe_dump(st.session_state['mechanism_entries'], allow_unicode=True, sort_keys=False)
    st.session_state.setdefault('mechanism_entries', [])
    st.session_state.setdefault('mechanism_list_yaml', '[]\n')
    st.subheader('添加反应机理')
    st.caption('CHEMKIN 转换默认启用 --permissive，转换警告写入日志；转换后仍执行 Cantera 加载校验。')
    mode = st.radio('机理文件来源', ['选择本地文件', '填写文件路径', '上传文件'], horizontal=True, key='mechanism_source', persist_state="session")
    path = ''; thermo = ''; transport = ''
    if mode == '选择本地文件':
        directory = st.text_input('机理文件夹', str(root.parent / 'mech'), key='mechanism_folder', persist_state="session")
        st.caption('机理文件直接放在该文件夹中，列表不递归子目录；YAML 可单独使用，CHEMKIN 的 .inp 需配套热力学文件，输运文件可选。配套文件也可通过完整路径选取。默认列表另含项目已转换的工作 YAML。')
        try:
            folder = Path(directory)
            files = sorted(p.resolve() for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {'.yaml', '.yml', '.inp'})
            if folder.resolve() == (root.parent/'mech').resolve():
                files += [p.resolve() for p in sorted((root/'results').glob('*/*cantera.yaml'))]
                files += [p.resolve() for p in sorted((root/'results').glob('*/inputs/*working.yaml'))]
            files = list(dict.fromkeys(files))
            options = [''] + [str(p) for p in files]
            path = st.selectbox('选择机理文件', options, format_func=lambda p: '请选择…' if not p else str(Path(p).relative_to(root)) if Path(p).is_relative_to(root) else Path(p).name, key='mechanism_file', persist_state="session")
            if path and Path(path).suffix.lower() == '.inp':
                st.caption('CHEMKIN 需要配套热力学文件；输运文件可选。请确认配套关系。')
                support = sorted(str(p.resolve()) for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {'.dat','.txt','.therm','.tran'})
                chosen_thermo = st.selectbox('选择热力学文件', ['']+support, format_func=lambda p: '请选择…' if not p else Path(p).name)
                thermo = st.text_input('热力学文件路径（可选其他目录）', key='mechanism_thermo_'+path, persist_state="session").strip().strip('"') or chosen_thermo
                chosen_transport = st.selectbox('选择输运文件（可选）', ['']+support, format_func=lambda p: '不使用输运文件' if not p else Path(p).name)
                transport = st.text_input('输运文件路径（可选）', key='mechanism_transport_'+path, persist_state="session").strip().strip('"') or chosen_transport
        except OSError as exc:
            st.error(f'无法读取机理文件夹：{exc}')
    elif mode == '填写文件路径':
        path = st.text_input('机理文件路径', key='mechanism_path', persist_state="session").strip().strip('"')
        if path and Path(path).suffix.lower()=='.inp':
            thermo=st.text_input('热力学文件路径', key='manual_thermo', persist_state="session").strip().strip('"')
            transport=st.text_input('输运文件路径（可选）', key='manual_transport', persist_state="session").strip().strip('"')
    else:
        upload=st.file_uploader('上传机理文件', type=['yaml','yml','inp'], key='upload_mechanism')
        path=_uploaded_file(upload,root)
        if path and Path(path).suffix.lower()=='.inp':
            thermo=_uploaded_file(st.file_uploader('上传配套热力学文件',type=['dat','txt','therm','inp'],key='upload_thermo'),root)
            transport=_uploaded_file(st.file_uploader('上传输运文件（可选）',type=['dat','txt','tran','inp'],key='upload_transport'),root)
        st.caption('上传文件保存在项目 inputs/uploads 内，同内容可复用。')
        if path and (Path(path).suffix.lower() != '.inp' or thermo):
            upload_entry = {'id':Path(path).stem, 'path':path}
            if thermo: upload_entry['thermo'] = thermo
            if transport: upload_entry['transport'] = transport
            signature = json.dumps(upload_entry, sort_keys=True)
            if st.session_state.get('upload_validation_signature') != signature:
                st.session_state['upload_validation_signature'] = signature
                try:
                    with st.spinner('上传文件已齐全，正在转换并校验…'):
                        _, audit = validate_mechanism_input(upload_entry, root/'inputs'/'prepared-mechanisms')
                    st.session_state['upload_validation'] = audit
                except Exception as exc:
                    st.session_state['upload_validation'] = {'status':'failed','error':str(exc)}
            audit = st.session_state['upload_validation']
            if audit['status'] == 'success':
                st.success(f'上传机理转换与校验成功：{audit["species"]} 个物种，气相 {audit["phase"]}。填写名称后可添加到列表。')
                if audit.get('warnings'):
                    st.warning(f'Cantera 产生 {len(audit["warnings"])} 条加载警告，详见 {audit["record_path"]}')
            else:
                st.error(f'上传机理转换 / 校验失败，请检查配套文件：{audit["error"]}')
        elif path:
            st.info('请上传配套热力学文件；文件齐全后自动执行 Cantera 转换与校验。')
    name=st.text_input('机理名称（留空使用文件名）', key='mechanism_name', persist_state="session")
    with st.expander('气相与物种名称映射（可选）'):
        phase=st.text_input('气相名称（留空使用默认气相）',key='mechanism_phase', persist_state="session")
        aliases=st.text_area('物种别名（每行 实验名称=机理名称）','Ar=AR',key='mechanism_aliases', persist_state="session")
    if st.button('添加到机理列表',type='primary'):
        clear_action_notice(notice_slot)
        try:
            if not path or Path(path).suffix.lower() not in {'.inp','.yaml','.yml'} or not Path(path).is_file():
                raise ValueError('请选择存在的 YAML 或 CHEMKIN 机理文件。')
            if Path(path).suffix.lower()=='.inp' and not thermo:
                raise ValueError('CHEMKIN 必须选择配套热力学文件。')
            entry={'id':name.strip() or Path(path).stem,'path':str(Path(path).resolve())}
            if any(e['id']==entry['id'] for e in st.session_state['mechanism_entries']):
                raise ValueError('机理名称已存在，请填写不同名称。')
            for key,value in [('thermo',thermo),('transport',transport)]:
                if value:
                    if not Path(value).is_file():raise ValueError(f'配套文件不存在：{value}')
                    entry[key]=str(Path(value).resolve())
            if phase.strip():entry['phase']=phase.strip()
            mapping={}
            for line in aliases.splitlines():
                if not line.strip():continue
                if '=' not in line:raise ValueError('物种别名需要按 实验名称=机理名称 填写。')
                a,b=(s.strip() for s in line.split('=',1))
                if not a or not b or a in mapping:raise ValueError('物种别名为空或重复。')
                mapping[a]=b
            entry['species_map']=mapping
            with st.spinner('正在转换并校验机理（Cantera 严格检查）…'):
                prepared, audit = validate_mechanism_input(entry, root/'inputs'/'prepared-mechanisms')
            if audit['warnings']:
                st.warning(f'Cantera 可加载，但产生 {len(audit["warnings"])} 条警告；请查看校验记录：{audit["record_path"]}')
            st.session_state['mechanism_entries'] += [entry]
            st.session_state['mechanism_list_yaml']=yaml.safe_dump(st.session_state['mechanism_entries'],allow_unicode=True,sort_keys=False)
            action_success(f'机理转换与校验成功，已添加 {entry["id"]}：气相 {prepared.phase}，{len(prepared.species)} 个物种；输运数据{"可用" if prepared.transport else "不可用（火焰计算受阻）"}。工作 YAML：{prepared.path}。', notice_slot)
        except Exception as exc:
            st.error(f'机理未添加：转换或校验失败，请检查机理及配套文件。{exc}')
            st.caption(f'CHEMKIN 转换日志目录：{root / "inputs" / "prepared-mechanisms"}。原始文件保留。')
    entries=st.session_state['mechanism_entries']
    st.caption(f'已选择 {len(entries)} 个机理；添加时立即转换并校验，运行前再次检查文件内容。每次可以只运行一个。')
    if entries:
        st.dataframe([{'名称':e['id'],'机理文件':e['path'],'热力学':e.get('thermo','内置于 YAML'),'输运':e.get('transport','未提供独立文件')} for e in entries],hide_index=True,width='stretch')
        remove=st.multiselect('移除已选机理',[e['id'] for e in entries],key='mechanisms_remove', persist_state="session")
        if st.button('移除选中机理',disabled=not remove):
            st.session_state['pending_mechanisms']=[e for e in entries if e['id'] not in remove]
            action_success(f'已从当前选择中移除 {len(remove)} 个机理，原机理文件保留。')
            st.rerun()
    with st.expander('高级：编辑机理列表 YAML'):
        mechanism_text=st.text_area('机理列表',key='mechanism_list_yaml',height=180, persist_state="session")
        if st.button('应用高级机理列表'):
            clear_action_notice(notice_slot)
            try:
                values=load_yaml(mechanism_text)
                if not isinstance(values,list) or any(not isinstance(e,dict) or not e.get('id') or not e.get('path') for e in values):
                    raise ValueError('需要机理列表，每个条目包含 id 和 path。')
                if len({e['id'] for e in values})!=len(values):raise ValueError('机理名称重复。')
                with st.spinner('正在转换并校验机理列表…'):
                    for entry in values:
                        validate_mechanism_input(entry, root/'inputs'/'prepared-mechanisms')
                st.session_state['pending_mechanisms']=values
                action_success(f'机理列表已载入并通过 Cantera 校验：{len(values)} 个机理。')
                st.rerun()
            except Exception as exc:st.error(str(exc))
    return mechanism_text


def _loaded_scope(manifest, configured):
    selected = st.session_state.get('run_mechanism_ids', [])
    scope = scope_summary(manifest, configured, selected)
    st.info(f"当前载入：{scope['xml_count']} 份 XML、{len(manifest['cases'])} 个工况；"
            f"机理：{', '.join(scope['mechanisms'])}。")
    st.caption(f"评分和绘图只使用这个已载入批次：{st.session_state.get('loaded_output', '')}")
    if scope['missing_xml'] or scope['missing_mechanisms']:
        st.warning(f"与当前运行选择相比，此批次缺少 {len(scope['missing_xml'])} 份 XML；"
                   f"未包含机理：{', '.join(scope['missing_mechanisms']) or '无'}。"
                   "选择更多实验不会自动生成模拟结果，需要运行相应批次后载入。")
        with st.expander('当前选择中未载入的 XML'):
            st.write([Path(p).name for p in scope['missing_xml']])
    with st.expander('已载入机理各自的数据范围'):
        st.dataframe([{'机理': mechanism,
                       'XML 数': len({c['experiment_id'] for c in manifest['cases'] if c['mechanism']['id'] == mechanism}),
                       '工况数': sum(c['mechanism']['id'] == mechanism for c in manifest['cases'])}
                      for mechanism in scope['mechanisms']], hide_index=True, width='stretch')


def _score_definitions():
    st.subheader('分数怎么读')
    st.markdown('**误差分数越低越好，理想值为 0；覆盖率越高越好。D 的绝对值越接近 0 越好。**')
    st.dataframe([
        {'指标': '点火 E', '定义': 'mean([ln(τ模拟/τ实验) / s]²)', '方向': '越低越好，0 为无偏差'},
        {'指标': '点火 D', '定义': 'mean(ln(τ模拟/τ实验) / s)', '方向': '接近 0 好；正值：模拟延迟偏长；负值：偏短'},
        {'指标': 'RMSE', '定义': 'sqrt(mean((模拟 − 实验)²))，保留量纲', '方向': '越低越好；不同单位不能直接比较'},
        {'指标': 'NRMSE', '定义': 'RMSE / max|实验值|', '方向': '越低越好；0.1 表示 RMSE 为实验最大值的 10%'},
        {'指标': '扩展组合指标 / score', '定义': '各类型平均 E 或 NRMSE² 的加权平均', '方向': '越低越好；只在相同数据、尺度和权重下比较'},
        {'指标': '评分覆盖率 / coverage', '定义': '通过数值验证且预测有效的原始测量点 / 选定测量点', '方向': '越高越好；代表完整性，不代表准确度'},
    ], hide_index=True, width='stretch')
    with st.expander('经验尺度、权重与排名条件'):
        st.write('s 是点火实验 ln(τ) 拟合残差的经验尺度，下限 0.10；它不是 XML 中的测量标准差。XML 不确定度用于实验误差条。全零组分需要明确正尺度才计算 NRMSE。')
        st.write('默认先平均同物种多仪器评分，再对物种、数据集及实验类型等权汇总。实际类型贡献、type weights、species weights 和 experiment weights 在下方明细中保留。')
        st.write('正式总榜要求所有选定工况均成功、通过数值验证且评分尺度完整。共同成功集合用于局部诊断，排除未成功或缺失的测量点；不能据此宣称全库排名。')


def _score_charts(manifest, evaluation):
    coverage, scores, types = score_chart_rows(evaluation)
    st.subheader('结果概览')
    columns = st.columns(2)
    with columns[0]:
        st.write('评分覆盖率（越高越完整）')
        if coverage:
            st.bar_chart(pd.DataFrame(coverage), x='机理', y='评分覆盖率 (%)', color='机理', horizontal=True, height=240,
                         alt='各机理评分覆盖率，越高表示可评分测量点越完整')
    with columns[1]:
        st.write('工况完成状态（包含绘图加密工况）')
        statuses = case_status_rows(manifest)
        if statuses:
            st.bar_chart(pd.DataFrame(statuses), x='机理', y='工况数', color='状态', horizontal=True, height=240,
                         alt='各机理数值验证通过及失败、输入受阻和待完成工况分布')
    st.caption(f"以下误差图仅比较共同成功的 {evaluation['common_points']} 个原始测量点；"
               f"排除 {evaluation['excluded_points']} 个，属于局部诊断。覆盖率图仍以完整选定测量点为分母。")
    if scores:
        if any(not r['eligible'] for r in evaluation['common_success']['mechanisms']):
            st.caption('部分曲线没有可评分点或完整尺度；以下仅展示可评分曲线的诊断指标，不构成正式排名。')
        st.write('共同成功集合：扩展组合指标（越低越好）')
        st.bar_chart(pd.DataFrame(scores), x='机理', y='扩展组合指标（越低越好）', color='机理', horizontal=True, height=240,
                     alt='在相同共同成功测量点上比较各机理扩展组合误差，越低越好')
        st.write('共同成功集合：分类型误差（E 与 NRMSE² 定义不同）')
        panels = st.columns(2)
        for index, kind in enumerate(sorted({r['实验类型'] for r in types})):
            with panels[index % 2]:
                st.write(kind)
                st.bar_chart(pd.DataFrame([r for r in types if r['实验类型'] == kind]),
                             x='机理', y='类型误差（越低越好）', color='机理', horizontal=True,
                             height=240, alt=f'{kind} 各机理局部诊断误差，越低越好')
        st.caption('各类型使用独立数值尺度，便于看清组分误差；E 与 NRMSE² 不直接比较大小。')
    else:
        st.info('没有尺度完整的共同成功集合，暂不绘制组合误差比较。')


def main():
    st.set_page_config(page_title="ReSpecTh 机理评估", layout="wide")
    st.title("ReSpecTh 机理评估与实验对比")
    st.caption("PyTeCK 扩展 · 实验 XML 只读 · 预测、数值验证与实验误差分别报告")
    from pyteck.respecth.ui_workspace import select_workspace
    root = select_workspace()
    with st.sidebar.expander('运行环境（排查版本）'):
        from pyteck.respecth import reader as reader_module, cases as cases_module
        st.code(f'服务 PID：{os.getpid()}\nPython：{sys.executable}\n界面：{Path(__file__).resolve()}\nXML 读取：{reader_module.__file__}\n机理转换：{cases_module.__file__}', language='text')
    if 'obsolete_cache_checked' not in st.session_state:
        from pyteck.respecth.cache_maintenance import cleanup
        maintenance=cleanup(root)
        st.session_state['obsolete_cache_checked']=True
        if not maintenance['blocked']:
            if maintenance['deleted']:
                st.session_state['cache_cleanup_notice']=f"已自动清理 {maintenance['deleted']} 个失效缓存文件，约 {maintenance['bytes']/2**20:.2f} MiB；计算结果保留。"
    if 'pending_saved_result_output' in st.session_state:
        st.session_state['saved_result_output'] = st.session_state.pop('pending_saved_result_output')
    startup = root/'.cache/ui-session.json'
    if not startup.exists(): startup=root/'results/ui-state.json'
    if 'config_text' not in st.session_state and startup.exists():
        saved = json.loads(startup.read_text(encoding='utf-8'))
        st.session_state.update(saved)
    from pyteck.respecth.project_storage import new_session
    if not st.session_state.get('session_workspace') or not Path(st.session_state['session_workspace']).is_dir():
        st.session_state['session_workspace']=str(new_session(root))
    workspace=Path(st.session_state['session_workspace'])
    session_output=str(workspace/'simulation')
    # A legacy active run remains attached; new computations use the session.
    old_output=st.session_state.get('output')
    if not old_output or not run_owner(old_output)['active']:
        st.session_state['output']=session_output
    if st.session_state.get('config_text'):
        from pyteck.respecth.models import clean_obsolete_options
        value=load_yaml(st.session_state['config_text'])
        cleaned=clean_obsolete_options(value)
        if cleaned!=value:
            st.session_state['config_text']=yaml.safe_dump(cleaned,allow_unicode=True,sort_keys=False)
    from pyteck.respecth.ui_cache import render_cache_controls
    render_cache_controls(root)
    from pyteck.respecth.ui_projects import render_project_controls
    render_project_controls(root)
    st.session_state['result_view_restored']=True
    if "pending_result_output" in st.session_state:
        pending = st.session_state.pop("pending_result_output")
        try:
            load_results_into_session(pending)
        except Exception as exc:
            st.error(f"载入失败：{exc}")
    show_result_load_notice()
    notice_slot = show_action_notice()
    if st.session_state.get("input_load_notice"):
        st.success(st.session_state["input_load_notice"])
    output_name = "results/ui-run"
    config_text = st.session_state.get("config_text", "")
    tabs = st.tabs(["1 数据与机理", "2 条件检查", "3 运行任务", "4 误差与覆盖率", "5 图表与导出", "6 单工况分析"], key="main_page", on_change="rerun")
    if not tabs[2].open:
        # A terminal progress manifest duplicates the loaded result library;
        # only the run page needs it, and can reload it on demand.
        for key in ('progress_manifest','progress_manifest_stamp','latest_case_result'):
            st.session_state.pop(key,None)
    with tabs[0]:
        if tabs[0].open:
            st.session_state.setdefault('data_root', str(root.parent))
            data_root = st.text_input("实验目录", key="data_root", persist_state="session")
            st.caption('读取本目录及各级普通子目录内的 XML，文件夹可自由命名（如 Li_2015、Shi_2018、pw 或 exp1）。自动排除隐藏目录（含 .respecth）、归档、备份、计算结果、程序项目目录及 .draft.xml / .new.xml 草稿；也可在下方填写单份 XML 完整路径。')
            with st.expander('文件存放结构示例'):
                st.code('实验总目录/\n  experiment.xml           # 可直接放在总目录\n  Li_2015/*.xml             # 子目录可自由命名\n  Shi_2018/set1/*.xml       # 支持多级子目录\n  pw/*.xml\n  .respecth/               # 内部记录和归档，不扫描\n\n项目保存位置/               # 可与实验目录独立\n  inputs/                  # 上传与机理转换\n  .cache/                  # 临时会话\n  results/                 # 分析、保存项目和导出', language='text')
            try:
                available = discover_experiments(data_root)
            except OSError as exc:
                st.error(str(exc))
                available = []
            if available:
                st.caption(f'已找到 {len(available)} 份实验 XML；选择后生成配置，预检查将进一步验证内容与模拟条件。')
            else:
                st.warning('未找到可选 XML。请检查路径和文件后缀；归档或隐藏目录中的单份文件可通过下方完整路径手动读取。')
            selected = st.multiselect("实验 XML", [str(p) for p in available],
                                      format_func=lambda p: str(Path(p).relative_to(Path(data_root).expanduser().resolve())), key="input_datasets", persist_state="session")
            extra = st.text_area("其他 XML 路径（每行一份，可读取 v2.3 示例）", key="input_extra", persist_state="session")
            selected += [s.strip() for s in extra.splitlines() if s.strip()]
            mechanism_text = _mechanism_picker(root, notice_slot)
            output_name = st.session_state.get('output_name','results/ui-run')
            st.caption(f'新计算默认不保存为项目；临时工作区：{session_output}。需要保留时使用左侧“项目：保存 / 打开”。')
            if st.button("生成运行配置", type="primary"):
                clear_action_notice(notice_slot)
                try:
                    if not selected:
                        raise ValueError('请先选择至少一份实验 XML。')
                    if not load_yaml(mechanism_text):
                        raise ValueError('请先添加至少一个反应机理。')
                    data = {"schema_version": 1, "datasets": selected,
                            "mechanisms": load_yaml(mechanism_text), "output": session_output,
                            "dataset_configs": {}, "solver": {"verify": True},
                            "grid": {"enabled": False}, "scoring": {}, "figure": {}, "workers": 0}
                    for p in selected:
                        experiment = load_experiment(p)
                        override = {"energy": "off"}
                        coefficient = {"exp1": 195, "exp5": 203, "exp6": 93.3, "exp7": 195}.get(Path(p).parent.name)
                        if coefficient:
                            override["grid_rules"] = {"residence_time": {"kind": "inverse_temperature", "coefficient": coefficient}}
                        data["dataset_configs"][str(Path(p).resolve())] = override
                    st.session_state["config_text"] = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
                    action_success(f'运行配置已生成：{len(selected)} 份 XML、{len(data["mechanisms"])} 个机理。可在“2 条件检查”编辑；点击“预检查并保存配置”写入文件。', notice_slot)
                except Exception as exc:
                    st.error(str(exc))
            imported = st.file_uploader("导入运行配置", type=["yaml", "yml", "json"])
            import_base = st.text_input("导入配置的相对路径基准目录", str(root))
            if imported and st.button("使用导入配置"):
                clear_action_notice(notice_slot)
                try:
                    imported_config = RunConfig.from_dict(load_yaml(imported.getvalue().decode("utf-8-sig")), Path(import_base))
                    st.session_state["config_text"] = yaml.safe_dump(imported_config.to_dict(), allow_unicode=True, sort_keys=False)
                    st.session_state['pending_mechanisms'] = imported_config.mechanisms
                    action_success(f'配置导入成功：{len(imported_config.datasets)} 份 XML、{len(imported_config.mechanisms)} 个机理。')
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    try:
        configured_data = load_yaml(st.session_state.get('config_text', '')) or {}
        mechanism_ids = [m['id'] for m in configured_data.get('mechanisms', [])]
    except (ValueError, TypeError, KeyError, AttributeError):
        configured_data, mechanism_ids = {}, []
    if configured_data:
        configured_data['output']=st.session_state.get('output',session_output)
    if st.session_state.get('run_mechanism_options') != mechanism_ids:
        st.session_state['run_mechanism_options'] = mechanism_ids
        st.session_state['run_mechanism_ids'] = mechanism_ids.copy()
    if st.session_state.get('reuse_config_text') != st.session_state.get('config_text', ''):
        st.session_state['reuse_config_text'] = st.session_state.get('config_text', '')
        st.session_state['run_reuse_directories'] = '\n'.join(configured_data.get('reuse_results', []))
    def selected_config():
        data = load_yaml(st.session_state.get('config_text', ''))
        selected_ids = st.session_state.get('run_mechanism_ids', [])
        if not selected_ids:
            raise ValueError('请在“3 运行任务”选择至少一个本次运行机理。')
        data['mechanisms'] = [m for m in data['mechanisms'] if m['id'] in selected_ids]
        data['output']=session_output
        return RunConfig.from_dict(data, root)
    def precheck_selected():
        config = selected_config()
        experiments, cases, notes = prepare_run(config)
        st.session_state["run_config"] = config.to_dict()
        st.session_state["prepared_count"] = len(cases)
        st.session_state['prepared_cases'] = cases
        st.session_state.pop('workload_signature', None)
        st.session_state["checked_text"] = st.session_state.get("config_text", "")
        st.session_state['checked_mechanisms'] = st.session_state['run_mechanism_ids'].copy()
        preview = [{"实验": Path(e.path).name, "类型": e.kind,
                    "原始点数": sum(len(g.points) for g in e.groups),
                    "观测值数": sum(len(s.y) for s in e.observations),
                    "求解任务数": sum(c.experiment_id==e.id for c in cases),
                    "测量曲线": len(e.observations), "解析问题": "; ".join(e.issues)} for e in experiments]
        invalid = [{"工况": c.id[:12], "机理": c.mechanism.id,
                    "问题": "; ".join(c.issues)} for c in cases if c.issues]
        st.session_state["precheck_report"] = {"preview": preview, "settings": {e.path: dataset_config(e, config) for e in experiments}, "invalid": invalid, "notes": notes}
        (Path(config.output) / "precheck-config.yaml").write_text(yaml.safe_dump(config.to_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    with tabs[1]:
        if tabs[1].open:
            st.info("组分统一按实际摩尔分数计算；入口条件取 XML。加密工况中变化的入口组成或其他条件，需要配置明确的生成规则。")
            from pyteck.respecth.grid_controls import render_grid_controls
            render_grid_controls(configured_data, root)
            from pyteck.respecth.profile_inputs import render_profile_controls
            render_profile_controls(configured_data)
            config_text = st.text_area("完整配置（可编辑）", key="config_text", height=380, persist_state="session")
            if st.button("预检查并保存配置"):
                clear_action_notice(notice_slot)
                try:
                    precheck_selected()
                    report = st.session_state['precheck_report']
                    destination = Path(st.session_state['run_config']['output']) / 'precheck-config.yaml'
                    action_success(f'预检查完成，配置已保存：{destination}。共 {st.session_state["prepared_count"]} 个工况，其中 {len(report["invalid"])} 个有输入问题；详见下方报告。', notice_slot)
                except Exception as exc:
                    st.session_state.pop("checked_text", None)
                    st.error(str(exc))
            report = st.session_state.get("precheck_report")
            if report and st.session_state.get("checked_text") == config_text and st.session_state.get('checked_mechanisms') == st.session_state.get('run_mechanism_ids'):
                st.dataframe(report["preview"], width="stretch")
                with st.expander("实际模型设置"):
                    st.json(report["settings"])
                st.write(f"{st.session_state['prepared_count']} 个工况，{len(report['invalid'])} 个阻止计算。")
                if report["invalid"]:
                    st.dataframe(report["invalid"], width="stretch")
                for note in report["notes"]:
                    st.warning(note)
            try:
                downloadable = yaml.safe_dump(RunConfig.from_dict(load_yaml(config_text), root).to_dict(), allow_unicode=True, sort_keys=False)
            except Exception:
                downloadable = config_text
            st.download_button("下载配置", downloadable, file_name="config.yaml")
    with tabs[2]:
        if tabs[2].open:
            task_output = configured_data.get('output') or st.session_state.get('output')
            active = restore_run_state(st.session_state, task_output)
            st.session_state['run_controls_active']=active
            st.multiselect('本次运行机理', mechanism_ids, key='run_mechanism_ids', disabled=active,
                           help='只运行选中的机理；切换选择后，到条件检查页预检查选中机理。', persist_state="session")
            st.caption('批次报告仅包含本次选中的机理。普通运行保留未选机理的缓存；全部重算时，按确认提示决定是否清理整个输出目录的已有结果。')
            grid_modes = [f"{m['id']}：{'加密' if m.get('grid', configured_data.get('grid', {})).get('enabled', False) else '无加密（仅实验工况点）'}"
                          for m in configured_data.get('mechanisms', []) if m['id'] in st.session_state.get('run_mechanism_ids', [])]
            if grid_modes:
                st.caption('本次工况模式：' + '；'.join(grid_modes))
            st.write(f"当前准备运行：{len(configured_data.get('datasets', []))} 份 XML；机理：{', '.join(st.session_state.get('run_mechanism_ids', [])) or '尚未选择'}。")
            st.caption(f"当前配置输出目录：{configured_data.get('output', '尚未生成配置')}。下方历史结果不会随机理选择自动变成新批次。")
            st.caption('默认仅保留绘图、评分、验证记录及入口/出口状态，不保留完整积分步和火焰场；需要完整计算域的单点分析会临时重建。')
            if st.button('预检查本次选择', disabled=active or not st.session_state.get('run_mechanism_ids')):
                clear_action_notice(notice_slot)
                try:
                    precheck_selected()
                    action_success(f"预检查完成：{st.session_state['prepared_count']} 个工况，{len(st.session_state['precheck_report']['invalid'])} 个输入受阻；配置已保存至 {Path(st.session_state['run_config']['output']) / 'precheck-config.yaml'}。", notice_slot)
                except Exception as exc:
                    st.session_state.pop('checked_text', None)
                    st.error(str(exc))
            force_rerun = st.checkbox('全部重新运行（本次选中的机理与工况）',key='force_rerun',disabled=active, persist_state="session")
            reuse_text = st.text_area('复用其他结果目录（可选，每行一个）', disabled=active or force_rerun, key='run_reuse_directories', persist_state="session")
            if force_rerun:
                st.info('本次全部重新求解，不使用缓存。启动前会询问是否删除本次输出目录的已有结果，默认删除；取消勾选则先备份旧结果。')
            else:
                st.info('自动跳过当前结果目录中身份一致、已通过数值验证的成功工况。其他目录可在上方指定；机理、工况或求解设置改变时会重新计算。')
            st.checkbox("已检查模型假设和加密规则", key="confirmed", persist_state="session")
            checked = st.session_state.get("checked_text") == config_text and bool(config_text) and st.session_state.get('checked_mechanisms') == st.session_state.get('run_mechanism_ids')
            if not checked:
                st.info("运行按钮暂不可用：当前配置或所选机理尚未预检查。点击本页上方“预检查本次选择”，并确认模型假设。")
            elif not st.session_state.get("confirmed"):
                st.info("运行按钮暂不可用：请勾选上方模型假设确认项。")
            if active:
                st.info("已连接后台运行任务（刷新页面不会停止计算）；结束或取消后可启动下一批次。")
            if checked:
                report = st.session_state.get('precheck_report', {})
                st.write(f"本次预检查：{st.session_state.get('prepared_count', 0)} 个工况；{len(report.get('invalid', []))} 个输入受阻。")
                if report.get('invalid'):
                    st.warning('输入受阻工况会记录为 invalid_input，并不执行求解。请到条件检查页查看完整原因。')
                    with st.expander('受阻原因汇总'):
                        st.dataframe([{'原因': reason, '工况数': count} for reason, count in Counter(r['问题'] for r in report['invalid']).items()], hide_index=True, width='stretch')
            retry_failed = st.checkbox("重试失败工况（保留成功缓存）", key="retry_failed",disabled=active or force_rerun, persist_state="session")
            plan_ready = False
            if checked:
                st.subheader('本次任务预览（当前选择）')
                refresh_plan = st.button('刷新本次缓存统计', disabled=active)
                progress_path = Path(st.session_state['run_config']['output'])/'progress.json'
                stamp = progress_path.stat().st_mtime_ns if progress_path.exists() else 0
                signature = (st.session_state['checked_text'], tuple(st.session_state['checked_mechanisms']),
                             force_rerun, retry_failed, reuse_text, stamp)
                try:
                    if refresh_plan or st.session_state.get('workload_signature') != signature:
                        from pyteck.respecth.workload import preview_workload
                        plan_config = selected_config()
                        if 'prepared_cases' not in st.session_state:
                            _, prepared_cases, _ = prepare_run(plan_config)
                            st.session_state['prepared_cases'] = prepared_cases
                        plan_config.retry_failed = retry_failed
                        plan_config.reuse_results = [str((root/Path(p.strip().strip('"'))).resolve()) for p in reuse_text.splitlines() if p.strip()]
                        with st.spinner('正在核对本次工况与已有完整结果…'):
                            st.session_state['workload_preview'] = preview_workload(st.session_state['prepared_cases'], plan_config, force=force_rerun)
                        st.session_state['workload_signature'] = signature
                    plan = st.session_state['workload_preview']
                    plan_ready = True
                    totals = plan['totals']
                    columns = st.columns(4)
                    for col, label, field in zip(columns, ['总工况', '已处理 / 可复用', '待处理', '预计新求解（最多）'], ['total','processed','pending','new_solves']):
                        col.metric(label, totals.get(field, 0))
                    labels = {'mechanism':'机理','total':'总工况','processed':'已处理 / 可复用','success':'已有验证成功',
                              'retained_failed':'保留失败记录','pending':'待处理','blocked':'待记录输入受阻','new_solves':'预计新求解（最多）',
                              'scoring':'实验评分工况','dense':'绘图加密工况'}
                    st.dataframe([{labels[k]:v for k,v in row.items()} for row in plan['mechanisms']], hide_index=True, width='stretch')
                    st.caption('总工况 = 已处理 / 可复用 + 待处理。已处理仅统计与本次条件及求解设置匹配的完整缓存；失败记录不等于验证成功。输入受阻只记录状态，不调用求解器；延续前驱失败可能减少实际新求解数量。旧网格中不属于本次计划的结果仍保留，不计入本次总数。')
                except Exception as exc:
                    st.error(f'本次任务统计失败：{exc}')
            cpu_count = os.cpu_count() or 1
            try:
                configured_workers = int((load_yaml(config_text) or {}).get("workers", 0))
            except (ValueError, TypeError, AttributeError):
                configured_workers = 0
            workers = st.number_input("并行进程数", min_value=1, max_value=cpu_count,
                                      value=min(cpu_count, configured_workers or min(4, max(1, cpu_count-1))),
                                      disabled=active, help="独立工况在不同进程中同时求解；延续模式按前驱顺序运行。")
            st.caption(f"本机 {cpu_count} 个逻辑处理器。火焰并发另受 flame_workers 限制（默认 2）。运行中的批次保持启动时的并行设置。")
            launch = st.button("运行 / 恢复", disabled=active or not checked or not plan_ready or not st.session_state.get("confirmed") or not st.session_state.get('run_mechanism_ids'))
            discard_previous = False
            if launch and force_rerun:
                st.session_state['rerun_confirmation'] = True
                st.session_state['discard_previous_results'] = True
                launch = False
            if st.session_state.get('rerun_confirmation') and force_rerun and not active:
                with st.container(border=True):
                    st.warning('全部重算前，是否删除之前的结果？删除后无法恢复。')
                    st.caption(f'清理范围：{st.session_state.get("output", "")} 中所有机理的模拟缓存、图表、历史批次，以及关联快照。实验源文件、机理和配置保留。仅重新计算本次选中的机理。')
                    discard_previous = st.checkbox('删除之前已有的全部结果（默认删除）', key='discard_previous_results')
                    analysis = st.session_state.get('analysis_process')
                    busy_analysis = analysis is not None and analysis.poll() is None
                    if busy_analysis: st.info('单工况分析仍在运行，请结束后再确认重算。')
                    confirm, cancel = st.columns(2)
                    if confirm.button('确认并开始全部重算', type='primary', disabled=busy_analysis or not checked or not plan_ready or not st.session_state.get('confirmed')):
                        launch = True
                        st.session_state.pop('rerun_confirmation', None)
                        if discard_previous:
                            for field in ('loaded_run','loaded_output','result_load_notice','result_load_directory'):
                                st.session_state.pop(field, None)
                    if cancel.button('取消重算'):
                        st.session_state.pop('rerun_confirmation', None)
                        st.rerun()
            if not force_rerun:
                st.session_state.pop('rerun_confirmation', None)
            if launch:
                try:
                    config = selected_config()
                    config.reuse_results = [str((root/Path(p.strip().strip('"'))).resolve()) for p in reuse_text.splitlines() if p.strip()]
                    config.retry_failed = retry_failed
                    config.workers = int(workers)
                    if restore_run_state(st.session_state, config.output):
                        st.warning('该结果目录已有后台任务，已阻止重复启动。请查看当前批次实时状态。')
                        st.rerun()
                    events, cancellation = queue.Queue(), threading.Event()
                    worker = threading.Thread(target=_worker, args=(config, events, cancellation, force_rerun, discard_previous), daemon=True)
                    st.session_state.update(worker=worker, events=events, cancellation=cancellation,
                                            output=config.output, progress=(0, 1, "开始"), error="", completion="")
                    atomic_json(root/'.cache/ui-session.json', {'config_text':config_text,
                        'mechanism_entries':configured_data.get('mechanisms', []),
                        'mechanism_list_yaml':yaml.safe_dump(configured_data.get('mechanisms', []),allow_unicode=True),
                        'output':config.output, 'saved_result_output':config.output,'session_workspace':str(workspace)})
                    st.session_state["launched_selection"] = {"text": config_text, "mechanisms": st.session_state["run_mechanism_ids"].copy()}
                    worker.start()
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
            if st.button("取消运行", disabled=not active):
                cancellation=st.session_state.get('cancellation')
                if cancellation is not None: cancellation.set()
                if cancel_run(task_output):
                    st.success('已提交取消请求，正在等待当前求解器安全退出；已完成结果保留。')
            snapshot_source = st.session_state.get('output') or configured_data.get('output')
            if st.button('载入 / 刷新计算结果', disabled=not snapshot_source,
                         help='运行中自动载入已完成结果快照；结束后载入完整批次。可用于评分、绘图和工况分析，再次点击刷新新增结果。'):
                try:
                    with st.spinner('正在载入可用的计算结果…'):
                        load_results_into_session(snapshot_source)
                    show_result_load_notice()
                except Exception as exc:
                    st.error(f'载入失败：{exc}')
            st.caption('运行中读取已完成部分，结束后读取完整批次；点击后显示载入范围和完成数量。刷新不会重新计算。')
            _progress_panel()
    with tabs[3]:
        if tabs[3].open:
            with st.expander('选择已有评估结果（可合并不同机理，无需重算）', key="result_catalog_panel", on_change="rerun") as details:
                if details.open:
                    from pyteck.respecth.result_library import discover_saved_results
                    @st.cache_data(ttl=30)
                    def result_catalog(): return discover_saved_results()
                    catalog=result_catalog(); catalog_map={r['path']:r for r in catalog}
                    def result_label(path):
                        item=catalog_map[path]
                        return f"{' + '.join(item['mechanisms'])} · {item['xml_count']} XML · 验证通过 {item['success']}/{item['total']} · {Path(path).relative_to(root)}"
                    chosen=st.multiselect('已保存评估批次（可同时选择多个）',list(catalog_map),format_func=result_label,key='result_library_selection', persist_state="session")
                    policy=st.selectbox('合并数据集范围',['intersection','union'],format_func=lambda v:'共有 XML' if v=='intersection' else '全部 XML（缺失预测保留缺失状态）',key='result_library_policy', persist_state="session")
                    if st.button('载入选中的已有结果',disabled=not chosen):
                        try:
                            if len(chosen)==1:
                                selected_output=chosen[0]
                            else:
                                from pyteck.respecth.saved_runs import combine_saved_runs
                                selected_output=str(workspace/('comparison-library-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
                                combine_saved_runs(chosen,selected_output,policy)
                            load_results_into_session(selected_output)
                            show_result_load_notice()
                        except Exception as exc: st.error(str(exc))
                    st.caption('列表显示历史批次和已保存项目的真实范围。选择多个后在临时工作区合并；需点击“保存项目”才能保留新的比较结果。')
            merge = False
            additional = ""
            comparison_output = str(workspace/'comparison')
            with st.expander("载入其他机理的历史结果并比较（不重新计算）", key="result_merge_panel", on_change="rerun") as details:
                if details.open:
                    additional = st.text_area("追加结果目录（每行一个，可来自单机理批次）")
                    st.caption("将当前结果与追加目录合并；默认仅比较共有 XML。比较结果暂存于当前临时会话，完整历程引用原文件。")
                    merge = st.button("合并历史结果并载入")
            automatic_load = False
            if 'pending_result_output' in st.session_state:
                st.session_state['saved_result_output'] = st.session_state.pop('pending_result_output')
                automatic_load = True
            if merge:
                try:
                    from pyteck.respecth.saved_runs import combine_saved_runs
                    first = st.session_state.get('saved_result_output', st.session_state.get('loaded_output',str(root/st.session_state.get("output_name",output_name))))
                    combine_saved_runs([first]+[s.strip() for s in additional.splitlines() if s.strip()],comparison_output)
                    st.session_state['saved_result_output'] = comparison_output
                    automatic_load = True
                    st.success("历史结果已合并，没有重新模拟。")
                except Exception as exc:
                    st.error(str(exc))
            output = st.text_input("已保存结果目录", st.session_state.get("output", str(root / st.session_state.get("output_name",output_name))), key='saved_result_output', persist_state="session")
            if st.button("载入结果") or automatic_load:
                try:
                    with st.spinner('正在载入已提交结果；运行中的批次自动生成部分结果视图…'):
                        load_results_into_session(output)
                    show_result_load_notice()
                except Exception as exc:
                    st.error(str(exc))
            st.caption('可载入正在运行的结果目录：自动读取已完整提交的工况，不中断计算；再次点击“载入结果”刷新。部分结果用于诊断评分和绘图，正式总榜仍要求完整覆盖。')
            loaded = st.session_state.get("loaded_run")
            if loaded:
                manifest, experiments, cases, results = loaded
                _loaded_scope(manifest, configured_data)
                _result_summary(manifest, "loaded")
                from pyteck.respecth.coverage import dataset_coverage
                with st.expander('XML × 机理覆盖分类（仅原始实验点）', key="score_coverage_panel", on_change="rerun") as details:
                    if details.open:
                        st.dataframe(dataset_coverage(experiments,cases,results),hide_index=True,width='stretch')
                _score_definitions()
                default_score = yaml.safe_dump(manifest["config"].get("scoring", {}), allow_unicode=True)
                st.session_state.setdefault("score_text", default_score)
                score_text = st.text_area("评分权重与全零曲线归一化尺度（SI）", key="score_text", persist_state="session")
                try:
                    evaluation = evaluate_results(experiments, results, load_yaml(score_text) or {}, cases)
                    _score_charts(manifest, evaluation)
                    st.subheader("评分明细与正式总榜")
                    st.dataframe(evaluation["formal"]["mechanisms"], width="stretch")
                    st.caption("评分覆盖率按原始测量点计算，与上面的数值工况成功率不同。组分按实际摩尔分数比较。")
                    if not evaluation["formal"]["ranking"]:
                        st.warning("本次未满足正式总榜要求。下面的成功部分评分仅用于诊断，不能作为完整机理排名。")
                    st.write("正式总榜", evaluation["formal"]["ranking"])
                    st.write(f"共同成功测量点：{evaluation['common_points']}；排除：{evaluation['excluded_points']}")
                    st.dataframe(evaluation["common_success"]["mechanisms"], width="stretch")
                    st.dataframe(evaluation["formal"]["curves"], width="stretch")
                    if st.button("保存新评分（不重新模拟）"):
                        clear_action_notice(notice_slot)
                        directory = st.session_state.get('loaded_work_output',st.session_state['loaded_output'])
                        atomic_json(Path(directory) / "evaluation.json", evaluation)
                        export_results({"output": directory, "evaluation": evaluation, "cases": cases})
                        (Path(directory)/"scoring.yaml").write_text(score_text, encoding="utf-8")
                        action_success(f'评分及配置已保存至 {directory}（evaluation.json、scoring.yaml 与评分表格）；未重新模拟。', notice_slot)
                except Exception as exc:
                    st.error(str(exc))
    with tabs[4]:
        if tabs[4].open:
            loaded = st.session_state.get("loaded_run")
            if loaded:
                manifest, experiments, cases, results = loaded
                _loaded_scope(manifest, configured_data)
                if st.button("选择本批次全部数据集和机理"):
                    st.session_state["figure_datasets"] = [e.id for e in experiments]
                    st.session_state["figure_mechanisms"] = sorted({c.mechanism.id for c in cases})
                    st.session_state["figure_specific"] = False
                    st.session_state["mechanisms_initialized_output"] = st.session_state["loaded_output"]
                    action_success(f'已选择本批次全部 {len(experiments)} 个数据集和 {len(st.session_state["figure_mechanisms"])} 个机理；点击“保存设置并重绘”更新图表。', notice_slot)
                st.caption("模拟用线、实验用点；每个 set 默认展示全部物种。")
                st.caption("下方为已保存图表，修改选择后点击“保存设置并重绘”更新。")
                available_mechanisms = sorted({c.mechanism.id for c in cases})
                if st.session_state.get("mechanisms_initialized_output") != st.session_state["loaded_output"]:
                    directory = Path(st.session_state.get('loaded_work_output',st.session_state['loaded_output']))
                    saved = load_yaml((directory/"figure.yaml").read_text(encoding="utf-8")) if (directory/"figure.yaml").exists() else {}
                    st.session_state["figure_mechanisms"] = [m for m in saved.get("mechanisms",available_mechanisms) if m in available_mechanisms]
                    st.session_state["mechanisms_initialized_output"] = st.session_state["loaded_output"]
                chosen_mechanisms = st.multiselect("绘图机理（默认全部，可选择一个或多个）", available_mechanisms, key="figure_mechanisms", persist_state="session")
                all_series = {s.id: f"{Path(e.path).stem} / {s.species or s.quantity} / {s.instrument or s.group_id}"
                              for e in experiments for s in e.observations}
                from pyteck.respecth.coverage import dataset_options
                coverage_options,coverage_records=dataset_options(experiments,cases,results,chosen_mechanisms)
                filter_mode=st.selectbox('按 XML 模拟覆盖情况筛选',['全部','有模拟曲线','全部完成','部分完成','未运行','计算失败或不可用'],key='figure_coverage_filter', persist_state="session")
                eligible=[e.id for e in experiments if filter_mode=='全部' or
                    (filter_mode=='有模拟曲线' and coverage_options[e.id]['available']) or coverage_options[e.id]['category']==filter_mode]
                st.session_state['figure_datasets']=[identity for identity in st.session_state.get('figure_datasets',eligible) if identity in eligible]
                dataset_names = {identity:coverage_options[identity]['label'] for identity in eligible}
                st.caption('筛选按所选机理的模拟覆盖情况；详细数量可在下方展开查看。')
                with st.expander('模拟覆盖明细', key='figure_coverage_details', on_change='rerun') as details:
                    if details.open:
                        st.dataframe(coverage_records,hide_index=True,width='stretch')
                chosen_datasets = st.multiselect("绘图数据集（每个 set 默认全部物种）", list(dataset_names),
                                                key="figure_datasets", format_func=dataset_names.get, persist_state="session")
                eligible_series = [s.id for e in experiments if e.id in chosen_datasets for s in e.observations]
                specific = st.checkbox("只绘制指定物种 / 曲线", key="figure_specific", persist_state="session")
                if specific:
                    st.session_state['figure_series'] = [s for s in st.session_state.get('figure_series', eligible_series) if s in eligible_series]
                    chosen = st.multiselect("绘制曲线", eligible_series, key="figure_series", format_func=all_series.get, persist_state="session")
                else:
                    chosen = eligible_series
                    st.caption(f"已选择 {len(chosen_datasets)} 个数据集，将绘制其全部 {len(chosen)} 条测量曲线；同物种多仪器合在同一子图。")
                availability=plot_availability(experiments,cases,results,chosen_datasets,chosen_mechanisms,chosen)
                absent=[r for r in availability if not r['可绘制预测点']]
                if absent:
                    st.warning('所选数据存在没有模拟预测的 XML / 机理组合；对应图片只有实验点，不能作为完整机理对比。')
                if availability:
                    with st.expander('所选数据的缺失原因',key='figure_missing_details',on_change='rerun') as details:
                        if details.open:
                            st.dataframe(availability,hide_index=True,width='stretch')
                    if any('旧版本输入限制' in r['说明'] for r in absent):
                        st.info('旧版本输入限制已移除。此前未计算的工况需要重新运行；重绘不会补算缺失工况。')
                if not chosen or not chosen_mechanisms:
                    st.warning("请选择至少一个数据集 / 曲线和一个机理后再重绘。")
                with st.form("figure_style_form"):
                    columns = st.number_input("子图列数", 1, 8, key="figure_columns", persist_state="session")
                    if 'figure_macro_layout' not in st.session_state:
                        style_root=Path(st.session_state.get('loaded_work_output',st.session_state['loaded_output']))
                        saved_style=load_yaml((style_root/'figure.yaml').read_text(encoding='utf-8')) if (style_root/'figure.yaml').exists() else {}
                        st.session_state['figure_macro_layout']=saved_style.get('macro_layout','overlay')
                    macro_layout=st.selectbox('宏观工况绘图方式',['overlay','subplots'],
                        format_func=lambda v:{'overlay':'不同 set / mix 叠加在同一坐标系','subplots':'不同 set / mix 分别放入子图'}[v],
                        key='figure_macro_layout',persist_state='session')
                    unit = st.selectbox("摩尔组成显示单位", ["ppm", "mole fraction", "percent"], key="figure_unit", persist_state="session")
                    with st.expander("坐标、图例与工况说明设置"):
                        reciprocal = st.checkbox("点火横轴使用 1000/T", key="figure_reciprocal", persist_state="session")
                        legend = st.checkbox("显示图例", key="figure_legend", persist_state="session")
                        linewidth = st.slider("线宽", .5, 4., key="figure_linewidth", persist_state="session")
                        if st.session_state.get('conditions_initialized_output') != st.session_state['loaded_output']:
                            directory = Path(st.session_state.get('loaded_work_output',st.session_state['loaded_output']))
                            saved = load_yaml((directory/'figure.yaml').read_text(encoding='utf-8')) if (directory/'figure.yaml').exists() else {}
                            st.session_state.update(figure_conditions=saved.get('conditions',True),
                                figure_conditions_position=saved.get('conditions_position','bottom'),
                                figure_conditions_fontsize=float(saved.get('conditions_fontsize',8)),
                                conditions_initialized_output=st.session_state['loaded_output'])
                        conditions = st.checkbox("显示实验工况说明（从 XML 与实际运行条件读取）", key='figure_conditions', persist_state="session")
                        conditions_position = st.selectbox("工况说明位置", ['bottom','top','upper right','upper left'],
                            format_func=lambda v: {'bottom':'图底部','top':'图顶部','upper right':'首个子图右上角','upper left':'首个子图左上角'}[v],
                            key='figure_conditions_position', persist_state="session")
                        conditions_fontsize = st.number_input("工况说明字号", 5.,20.,key='figure_conditions_fontsize', persist_state="session")
                        st.caption("组分采用实际摩尔分数，含水组分保留；入口条件按 XML。")
                        extra_style = st.text_area("其他图表设置（YAML：species_order、xlim、ylim、figsize、colors、markers 等）", key="figure_extra", persist_state="session")
                    if st.form_submit_button("保存设置并重绘", disabled=not chosen or not chosen_mechanisms):
                        clear_action_notice(notice_slot)
                        try:
                            options = {**(load_yaml(extra_style) or {}), "series": chosen, "mechanisms": chosen_mechanisms,
                                       "experiments": chosen_datasets, "specific_series": specific,
                                       "columns": columns, "composition_unit": unit,
                                       "macro_layout":macro_layout,
                                       "reciprocal_temperature": reciprocal, "legend": legend, "linewidth": linewidth}
                            options.update(conditions=conditions, conditions_position=conditions_position,
                                           conditions_fontsize=conditions_fontsize)
                            directory = Path(st.session_state.get('loaded_work_output',st.session_state['loaded_output']))
                            drawing_progress=st.progress(0.,text='准备绘制图表…')
                            def update_drawing(done,total,message):
                                drawing_progress.progress(done/max(total,1),text=f'绘图 {done}/{total} 张 · {message}')
                            generated = render_figures(experiments, {"cases": cases, "results": results},
                                           {**options, "output": str(directory / "figures")},progress=update_drawing)
                            (directory / "figure.yaml").write_text(yaml.safe_dump(options, allow_unicode=True), encoding="utf-8")
                            if generated:
                                action_success(f'图表已重绘：生成 {len(generated)} 个图表文件，保存于 {directory / "figures"}；设置已保存至 figure.yaml。', notice_slot)
                            else:
                                st.warning('设置已保存至 figure.yaml，但未生成图表；请检查所选数据与曲线。')
                        except Exception as exc:
                            if 'drawing_progress' in locals(): drawing_progress.empty()
                            st.error(str(exc))
                directory = Path(st.session_state.get('loaded_work_output',st.session_state['loaded_output']))
                from pyteck.respecth.ui_figures import render_saved_figures
                render_saved_figures(directory / 'figures')
                exported = [p for p in directory.iterdir() if p.suffix in {".csv", ".json", ".yaml"}]
                exported += list((directory / "figures").glob("*"))
                from pyteck.respecth.ui_artifacts import deferred_archive
                st.download_button("下载表格、配置和图表",deferred_archive(directory,exported),"results.zip","application/zip",on_click='ignore')
                st.caption("新批次 cache/*.h5 仅保留入口/出口状态；绘图和评分使用已保存预测值。旧批次可能仍含完整历程。")
            else:
                from pyteck.respecth.ui_projects import render_project_figures
                if not render_project_figures():
                    st.info("先在“误差与覆盖率”载入结果，或打开已保存的图表项目。")
    with tabs[5]:
        if tabs[5].open:
            from pyteck.respecth.analysis_ui import render_analysis_page
            render_analysis_page()


@st.fragment(run_every="3s")
def _progress_panel():
    events = st.session_state.get("events")
    if events:
        while True:
            try:
                item = events.get_nowait()
            except queue.Empty:
                break
            if item[0] == "progress":
                st.session_state["progress"] = item[1:4]
            elif item[0] == "done":
                st.session_state["completion"] = item[1]
                st.session_state["pending_result_output"] = st.session_state["output"]
                st.rerun()
            else:
                st.session_state["error"] = item[1]
                st.rerun()
    n, total, status = st.session_state.get("progress", (0, 1, "尚未运行"))
    # A terminal event describes one case, not the success of the whole batch.
    output = st.session_state.get("output")
    if st.session_state.get('run_controls_active') and output:
        worker=st.session_state.get('worker')
        if not run_owner(output)['active'] and not (worker and worker.is_alive()):
            st.session_state['run_controls_active']=False
            st.rerun()
    # Live updates read a few KB rather than decoding the entire input library
    # (tens of MB) and rebuilding case dictionaries every second.
    if output and (Path(output)/'progress.json').exists():
        try:
            live = json.loads((Path(output)/'progress.json').read_text(encoding='utf-8'))
            worker = st.session_state.get('worker')
            owned=run_owner(output)['active'] or bool(worker and worker.is_alive())
            if owned:
                st.subheader('当前批次实时状态')
                st.caption(f"{live['xml_count']} 份 XML · {', '.join(live['mechanisms'])}")
                st.progress(live['completed_cases']/max(live['total_cases'],1),
                    text=f"已处理 {live['completed_cases']}/{live['total_cases']} · 数值验证通过 {live['status_counts'].get('success',0)}")
                columns=st.columns(3)
                columns[0].metric('正在求解',len(live['active']))
                columns[1].metric('待运行',live['pending_cases'])
                columns[2].metric('系统可用内存',f"{psutil.virtual_memory().available/2**30:.1f} GB")
                with st.expander('运行统计与保存位置',key='live_details',on_change='rerun') as details:
                    if details.open:
                        st.write('完成状态',live['status_counts'])
                        st.caption(f"缓存跳过 {live['cache_hits']} · 新提交 {live['submitted_cases']} · {output}")
                if live['active']:
                    st.dataframe([{'XML':Path(c['XML']).name,'机理':c['mechanism'],'dataGroup':c['group_id'],
                        '类型':c['kind'],'温度 (K)':c['condition']['temperature'],
                        '原始点':str(c['point_indices'])} for c in live['active']],hide_index=True,width='stretch')
                if st.session_state.get('error'):
                    st.error(st.session_state['error'])
                return
            if live['status']=='running':
                st.warning('后台运行进程已停止；以下是最后保存的进度。可载入已完成结果或恢复待运行工况。')
        except (OSError,ValueError,KeyError):
            pass
    if output:
        try:
            path = Path(output) / "manifest.json"
            stamp = path.stat().st_mtime_ns
            if st.session_state.get("progress_manifest_stamp") != (str(path), stamp):
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                st.session_state["progress_manifest"] = snapshot
                st.session_state["progress_manifest_stamp"] = (str(path), stamp)
                cache_dir = Path(output)/'cache'
                st.session_state["latest_case_result"] = max(snapshot.get('results', []), default=None,
                    key=lambda r: (cache_dir/f"{r['case_id']}.json").stat().st_mtime_ns
                    if (cache_dir/f"{r['case_id']}.json").exists() else 0)
            record = st.session_state["progress_manifest"]
            configured = load_yaml(st.session_state.get('config_text', '')) or {}
            scope = scope_summary(record, configured, st.session_state.get('run_mechanism_ids', []))
            launch = st.session_state.get('launched_selection', {})
            current = (scope['same_scope'] and launch.get('text') == st.session_state.get('config_text')
                       and launch.get('mechanisms') == st.session_state.get('run_mechanism_ids'))
            st.subheader('本次启动的批次结果' if current else '历史批次结果（独立于当前选择）')
            st.write(f"记录机理：{', '.join(scope['mechanisms'])}；{scope['xml_count']} 份 XML。")
            if not current:
                counts = Counter(r['status'] for r in record.get('results', []))
                st.caption(f"历史记录：{len(record.get('results', []))}/{len(record['cases'])}；验证成功 {counts['success']}，其他状态 {dict((k,v) for k,v in counts.items() if k != 'success')}。这不是本次计划的处理进度；本次数量见上方任务预览。")
                return
            completed = record.get("results", [])
            cancelled_count = sum(r['status']=='cancelled' for r in completed)
            processed_count = len(completed)-cancelled_count
            st.progress(processed_count/max(len(record['cases']), 1), text=f"任务处理进度 {processed_count}/{len(record['cases'])}（包含失败工况）")
            if cancelled_count:
                st.warning(f"批次已取消；{cancelled_count} 个工况尚未完成，可恢复运行。已提交的完整成功结果保留。")
            passed=sum(r['status']=='success' for r in completed)
            failed=sum(r['status'] not in {'success','cancelled'} for r in completed)
            if record['status'] != 'running':
                message=f"任务已结束：数值验证通过 {passed}/{len(record['cases'])} · 未成功 {failed} · 待恢复 {cancelled_count}。"
                if failed or cancelled_count: st.warning(message)
                else: st.success(message)
            active_ids = record.get("active_cases")
            end_time = datetime.fromisoformat(record['finished_utc']) if record.get('finished_utc') else datetime.now(timezone.utc) if record['status']=='running' else None
            elapsed = (end_time-datetime.fromisoformat(record["created_utc"])).total_seconds() if end_time else None
            columns = st.columns(4)
            columns[0].metric("已处理工况（不含取消）", f"{processed_count}/{len(record['cases'])}")
            columns[1].metric("正在求解", len(active_ids) if active_ids is not None else "旧批次未记录")
            columns[2].metric("待运行 / 恢复工况", cancelled_count if cancelled_count else record.get("pending_cases", "旧批次未记录"))
            columns[3].metric("运行耗时", f"{elapsed/60:.1f} 分钟" if elapsed is not None else "旧记录无结束时间")
            st.caption(f"本批次并行进程：{record.get('workers', record['config'].get('workers', 0))}；结果目录：{output}")
            if 'cache_hits' in record and 'submitted_cases' in record:
                success_hits = sum(item.get('status')=='success' for item in record['cache_hits'])
                st.write(f"启动时复用记录：{len(record['cache_hits'])}（成功 {success_hits}，其他状态 {len(record['cache_hits'])-success_hits}）；新提交求解：{len(record['submitted_cases'])}。")
            else:
                st.caption('旧批次未记录缓存跳过和新提交数量；新运行会显示这些统计。')
            experiments = {e['id']: e['path'] for e in record['experiments']}
            by_id = {c['id']: c for c in record['cases']}
            def describe(identity):
                case = by_id[identity]
                condition = case['condition']
                return {"XML": Path(experiments[case['experiment_id']]).name,
                        "dataGroup": case['group_id'], "原始点": str(case['point_indices']),
                        "机理": case['mechanism']['id'], "类型": case['kind'],
                        "温度 (K)": condition['temperature'], "压力 (Pa)": condition['pressure'],
                        "停留时间 (s)": condition.get('residence_time'),
                        "扫描变量": condition['scan_name'], "扫描值 (SI)": condition['scan_value'],
                        "工况 ID": identity[:12]}
            if active_ids:
                st.write("正在求解的 XML 工况")
                st.dataframe([describe(identity) for identity in active_ids], width="stretch", hide_index=True)
                with st.expander("运行中工况的完整入口组成与模型配置"):
                    st.json([{ "XML": experiments[by_id[i]['experiment_id']],
                              "condition": by_id[i]['condition'], "model": by_id[i]['config']}
                             for i in active_ids])
            elif active_ids is None:
                st.info("当前批次在进度功能更新前启动，未记录运行中工况；下面显示最近完成工况。新启动批次将显示实时运行列表。")
            if completed:
                st.write("完成状态", dict(Counter(r['status'] for r in completed)))
                # Manifest result order follows input order, not completion time.
                latest = st.session_state["latest_case_result"]
                st.write("最近完成工况")
                st.dataframe([{**describe(latest['case_id']), "状态": latest['status'], "原因": latest.get('reason', '')}], width="stretch", hide_index=True)
        except (OSError, ValueError, KeyError, TypeError):
            st.caption("正在准备输入或刷新运行清单。")
    if st.session_state.get("error"):
        st.error(st.session_state["error"])
    if st.session_state.get("completion"):
        st.info('最近启动的任务已结束；处理完成不等于全部成功，请以批次汇总为准。')
    record = st.session_state.get("progress_manifest")
    if record and record['status'] != 'running':
        _result_summary(record, "finished")


def _result_summary(manifest, key):
    summary = summarize_run(manifest)
    st.subheader("运行成果与失败汇总")
    cancelled_count = sum(r['status']=='cancelled' for r in manifest.get('results', []))
    st.write(f"已处理 {summary['completed_cases']-cancelled_count}/{summary['total_cases']} 个工况；"
             f"数值验证通过 {summary['numerically_verified']} 个；未成功 {len(summary['failures'])} 个。")
    if cancelled_count:
        st.caption(f"未成功中包含 {cancelled_count} 个取消待恢复工况；取消状态不代表求解器失败。")
    kinds = {'pfr': '管式反应器', 'jsr': 'JSR', 'ignition': '点火延迟', 'flame': '火焰速度',
             'profile': '激波管组分时间历程', 'burner_profile': '平焰物种轴向剖面'}
    st.dataframe([{'实验类型': kinds.get(r['kind'], r['kind']), '工况数': r['total'],
                   '数值验证通过': r.get('success', 0), '求解失败': r.get('solver_failed', 0),
                   '输入不完整': r.get('invalid_input', 0),
                   '其他未成功': r['total']-r.get('success', 0)-r.get('solver_failed', 0)-r.get('invalid_input', 0)}
                  for r in summary['by_type']], width="stretch", hide_index=True)
    st.caption("success 表示数值验证通过。实验预测是否准确还需看误差评分。")
    if summary['failures']:
        st.warning("本次存在未成功工况，可展开查看原因。")
        with st.expander("失败工况明细", key="failure_details_"+key, on_change="rerun") as details:
            if details.open:
                st.dataframe([{'XML': Path(r['XML']).name, '类型': kinds.get(r['kind'], r['kind']),
                               '温度 (K)': r['temperature'], '压力 (Pa)': r['pressure'],
                               '停留时间 (s)': r['residence_time'], '状态': r['status'], '原因': r['reason'],
                               'dataGroup': r['dataGroup'], '原始点': str(r['point_indices']),
                               '机理': r['mechanism'], '工况 ID': r['case_id']}
                              for r in summary['failures']], width="stretch", hide_index=True)
        failure_file = Path(summary['output'])/'failed_cases.csv'
        if failure_file.exists():
            st.download_button("下载失败明细 CSV", failure_file.read_bytes(), 'failed_cases.csv',
                               key=f"failure_download_{key}")
    with st.expander("各 XML 完成情况及结果位置"):
        st.dataframe(summary['by_dataset'], width="stretch", hide_index=True)
        st.write(summary['output'])
        st.caption("comparison.csv：实验与模拟；curve_scores.csv：分曲线误差；cache/*.h5：完整历程；figures/：PNG、PDF、SVG。")
    st.download_button("下载运行汇总 JSON", json.dumps(summary, ensure_ascii=False, indent=2),
                       "run_summary.json", key=f"summary_download_{key}")


if __name__ == "__main__":
    main()
