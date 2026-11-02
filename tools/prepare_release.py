"""Prepare a public source tree; purge local computations only with an explicit flag."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import zipfile
from pyteck.respecth.cache_maintenance import contained,files_under,busy_reasons

ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT.parent/'pyteck-respecth-release'
TOOLS=('launch_ui.py','restart_idle_ui.py','cleanup_project.py','manage_cache.py',
       'clean_stale_logs.py','acceptance_smoke.py','make_examples.py')
FILES=('LICENSE','CITATION.md','CITATION.cff','CHANGELOG.md','CODE_OF_CONDUCT.md',
       'CONTRIBUTING.md','pyproject.toml','setup.ps1','start.ps1','一键启动.bat','.gitignore','.coveragerc')
README='''# PyTeCK–ReSpecTh 机理评估与后处理

基于 PyTeCK 的 MIT 许可扩展，支持原生 ReSpecTh XML 读取、Cantera 四类求解器、多机理对比、误差评分、绘图及敏感性/ROP 分析。上游出处见 UPSTREAM.json 与 CITATION.md。

## 安装与启动

需要 Python 3.10 或更新版本，Cantera 3.2 和 Streamlit 1.65 或更新版本（依赖由安装命令解析）。Windows 首次运行 `powershell -ExecutionPolicy Bypass -File setup.ps1`，再双击 `一键启动.bat`。也可在自己的虚拟环境中运行：

```shell
python -m pip install .
python -m streamlit run src/pyteck/respecth/app.py --server.address 127.0.0.1
```

首次页面没有历史结果。自行选择实验 XML 与 YAML / CHEMKIN 机理，预检查条件后运行。新结果默认暂存会话，需要时通过“保存项目”明确保存。批量结果只保留预测值、验证信息及入口/出口状态；需要完整计算域的单点诊断临时重建并清理。详见 docs/guides。

## 可复现示例

```shell
pyteck-respecth check examples/respecth/demo.yaml
pyteck-respecth run examples/respecth/demo.yaml
```

示例使用合成数据和 Cantera 的公开氢气/GRI-Mech 机理，只验证软件流程，不代表甲胺实验预测验证。实际实验数据与用户机理不随本发布包分发；复现实验预测需要自行提供输入和模型假设。

物种图默认每个物种一个子图；实验用点、模拟用线。同工况线点同色，多机理可对比；宏观工况可叠加或分子图。工况说明和当量比从实际条件计算。所有组分采用实际摩尔分数，不做除水归一化。

## 验证与限制

`python -m pip install pytest` 后可执行 `python -m pytest tests/test_atomic_io.py tests/test_analysis_cache.py tests/test_compact_storage.py tests/test_project_storage.py`。部分测试需要可选的本地实际数据，不提供这些数据时应跳过。原 PyTeCK 整体评估测试可能耗时较长。

PFR 为等温定压停留时间积分，JSR 为等温开放稳态反应器，点火为绝热定容，火焰为自由传播预混火焰。点火温度敏感性是固定时刻温度的代理，不是点火延迟导数。数值验证、运行覆盖率和实验预测误差分别报告；合成示例通过不能证明某实际机理准确。

本目录可用于源码上传。它不包含用户输入、计算结果、分析缓存、保存项目、会话状态、本机虚拟环境、Git 历史或历史截图。运行时按需生成的 results/、inputs/、.cache/ 不应上传。源项目的上游说明另见 README_UPSTREAM.md。
'''


def prepare():
    if RELEASE.exists(): raise ValueError('Release directory already exists; refusing overwrite')
    RELEASE.mkdir()
    ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo','.pytest_cache','.DS_Store')
    for name in ('src','tests','logo','.github'):
        if (ROOT/name).exists(): shutil.copytree(ROOT/name,RELEASE/name,ignore=ignore)
    for name in FILES: shutil.copy2(ROOT/name,RELEASE/name)
    (RELEASE/'.streamlit').mkdir()
    shutil.copy2(ROOT/'.streamlit/config.toml',RELEASE/'.streamlit/config.toml')
    (RELEASE/'tools').mkdir()
    for name in TOOLS: shutil.copy2(ROOT/'tools'/name,RELEASE/'tools'/name)
    shutil.copytree(ROOT/'docs/guides',RELEASE/'docs/guides',ignore=ignore)
    for name in ('h2o2-shocktube',):
        if (ROOT/'examples'/name).exists(): shutil.copytree(ROOT/'examples'/name,RELEASE/'examples'/name,ignore=ignore)
    example=RELEASE/'examples/respecth';example.mkdir(parents=True,exist_ok=True)
    for path in (ROOT/'examples/respecth').iterdir():
        if path.name=='mechanisms': shutil.copytree(path,example/path.name,ignore=ignore)
        elif path.name=='demo.yaml' or path.name.startswith('synthetic-'): shutil.copy2(path,example/path.name)
    shutil.copy2(ROOT/'README.md',RELEASE/'README_UPSTREAM.md')
    for name in ('README.md','README_ReSpecTh.md'): (RELEASE/name).write_text(README,encoding='utf-8')
    (RELEASE/'DELIVERY.md').write_text('# 发布版\n\n本目录不含用户数据、机理副本、计算产物、开发缓存或本机环境。安装、使用及限制见 README.md。发布核验见 RELEASE_CHECKS.json。\n',encoding='utf-8')
    (RELEASE/'SPEC.md').write_text('# 功能范围\n\nReSpecTh v2.6 读取、Cantera 机理校验及 PFR/JSR/点火/层流火焰计算、多机理评分绘图、可取消与恢复的进程任务、显式项目保存、单点原生敏感性及全域 PFR ROP。\n\n默认仅保留绘图评分所需预测及端点状态，完整域按需重建。实验 XML 只读。模型假设、错误状态、数值验证与输入来源必须可追溯。首版不提供自动机理优化与 XML 写入。\n',encoding='utf-8')
    upstream=json.loads((ROOT/'UPSTREAM.json').read_text(encoding='utf-8'))
    upstream['retrieval']='Source derived from the specified GitHub commit; original MIT license and citations retained'
    (RELEASE/'UPSTREAM.json').write_text(json.dumps(upstream,ensure_ascii=False,indent=2),encoding='utf-8')
    for path in (RELEASE/'docs/guides').glob('*.md'):
        text=path.read_text(encoding='utf-8')
        text=text.replace('`docs/delivery/project-storage-verification.json`','发布核验记录')
        text=text.replace('2026-10-20 起，','')
        path.write_text(text,encoding='utf-8')
    # Public documentation and code only; no private input paths may survive.
    findings=[]
    for path in files_under(RELEASE):
        if path.suffix.lower() not in {'.py','.md','.json','.yaml','.yml','.toml','.ps1','.txt'}: continue
        text=path.read_text(encoding='utf-8-sig')
        if any(token.casefold() in text.casefold() for token in ('BaiduSyncdisk','C:/Users/17915','C:\\Users\\17915')):
            findings.append(str(path.relative_to(RELEASE)))
    if findings: raise ValueError('Local paths remain in release: '+str(findings))
    distribution=importlib.metadata.distribution('cantera')
    licenses=[p for p in distribution.files or [] if 'license' in str(p).lower() and str(p).lower().endswith(('.txt','.md'))]
    notices='Cantera example mechanism data are redistributed for demonstration. Cantera: https://cantera.org, BSD-3-Clause.\n\n'
    for path in licenses: notices+=distribution.locate_file(path).read_text(encoding='utf-8')+'\n'
    if not licenses: raise ValueError('Cantera redistribution license not found')
    (RELEASE/'THIRD_PARTY_NOTICES.md').write_text(notices,encoding='utf-8')
    print(json.dumps({'release_directory':str(RELEASE),'files':len(list(files_under(RELEASE)))}))


def purge():
    if reasons:=busy_reasons(ROOT): raise ValueError('Active computation; purge refused: '+str(reasons))
    import psutil
    app=(ROOT/'src/pyteck/respecth/app.py').resolve()
    listeners={c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN'}
    for process in psutil.process_iter(['pid','cmdline','cwd']):
        try:
            if process.pid not in listeners: continue
            args=process.info['cmdline'] or []
            if 'streamlit' not in args or 'run' not in args: continue
            index=args.index('run');target=Path(args[index+1])
            target=(Path(process.info['cwd'])/target).resolve() if not target.is_absolute() else target.resolve()
            if target!=app: continue
            if process.children(recursive=True): raise ValueError('UI has child tasks; refusing shutdown')
            process.terminate();process.wait(timeout=15)
        except (psutil.NoSuchProcess,psutil.AccessDenied,IndexError): continue
    selected=[ROOT/name for name in ('results','.cache','.pytest_cache','dist','inputs/prepared-mechanisms')]
    for path in selected:
        contained(ROOT,path)
        for folder,dirs,_ in os.walk(path,followlinks=False):
            for name in dirs:
                candidate=Path(folder)/name
                if candidate.is_symlink() or candidate.is_junction(): raise ValueError('Linked directory; purge aborted')
    count=0;size=0
    for directory in selected:
        for path in files_under(directory): count+=1;size+=path.stat().st_size
        if directory.exists(): shutil.rmtree(directory)
    print(json.dumps({'removed_files':count,'removed_apparent_bytes':size,'computational_state_cleared':True}))


def finalize():
    assert RELEASE.is_dir()
    for name in ('results','.cache','.pytest_cache','inputs'):
        target=contained(RELEASE,RELEASE/name)
        if target.exists():
            for folder,dirs,_ in os.walk(target,followlinks=False):
                if any((Path(folder)/d).is_symlink() or (Path(folder)/d).is_junction() for d in dirs): raise ValueError('Linked release artifact')
            shutil.rmtree(target)
    for folder,dirs,_ in os.walk(RELEASE,topdown=False,followlinks=False):
        if Path(folder).name=='__pycache__':
            path=contained(RELEASE,Path(folder));shutil.rmtree(path)
    entries=[]
    for path in sorted(files_under(RELEASE)):
        if path.name=='RELEASE_MANIFEST.json': continue
        entries.append({'file':path.relative_to(RELEASE).as_posix(),'bytes':path.stat().st_size,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (RELEASE/'RELEASE_MANIFEST.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=RELEASE.with_suffix('.zip')
    if archive.exists(): raise ValueError('Release ZIP already exists; refusing overwrite')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
        for path in sorted(files_under(RELEASE)): output.write(path,RELEASE.name+'/'+path.relative_to(RELEASE).as_posix())
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','purge','finalize'])
    {'prepare':prepare,'purge':purge,'finalize':finalize}[parser.parse_args().action]()
