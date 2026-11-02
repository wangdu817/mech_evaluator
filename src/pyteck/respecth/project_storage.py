"""Unsaved session workspaces and explicit, self-contained project snapshots."""
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import re
import shutil
import uuid
import yaml
from .atomic_io import atomic_json
from .cache_maintenance import contained,files_under,busy_reasons


def new_session(root):
    directory=Path(root).resolve()/'.cache/sessions'/uuid.uuid4().hex
    directory.mkdir(parents=True)
    atomic_json(directory/'session.json',{'schema_version':1,'temporary':True,
        'created_utc':datetime.now(timezone.utc).isoformat(),'components':[]})
    return directory


def remember_session(root,state):
    path=Path(root)/'.cache/ui-session.json'
    path.parent.mkdir(exist_ok=True)
    atomic_json(path,{key:state[key] for key in ('config_text','mechanism_entries','mechanism_list_yaml',
        'input_datasets','output','session_workspace') if key in state})


def record_component(workspace,directory):
    workspace=Path(workspace);path=workspace/'session.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    value=str(Path(directory).resolve())
    if value not in data['components']:
        data['components'].append(value);atomic_json(path,data)


def temporary_sessions(root):
    root=Path(root).resolve();output=[]
    for path in (root/'.cache/sessions').glob('*/session.json'):
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            if not data.get('temporary'): continue
            components=[path.parent]
            for value in data.get('components',[]):
                directory=contained(root,Path(value))
                allowed=[root/'results'/name for name in ('analysis','analysis-batches','analysis-comparisons')]
                if directory.parent in allowed and directory.name.startswith('temporary-'+path.parent.name+'-'):
                    components.append(directory)
                else: raise ValueError('Unexpected temporary component')
            size=sum(p.stat().st_size for d in components for p in files_under(d))
            output.append({'directory':str(path.parent),'created':data['created_utc'],'bytes':size,
                           'components':list(map(str,components))})
        except (OSError,ValueError,KeyError): continue
    return output


def discard_sessions(root,selected,*,protected=()):
    root=Path(root).resolve()
    if reasons:=busy_reasons(root): raise ValueError('任务运行中，未删除临时会话：'+'；'.join(reasons))
    chosen=[s for s in temporary_sessions(root) if s['directory'] in set(map(str,selected))]
    targets=[Path(c) for s in chosen for c in s['components']]
    for current in protected:
        if current and any(Path(current).resolve().is_relative_to(t) for t in targets):
            raise ValueError('当前仍在使用该临时会话，请先开始新临时会话并卸载结果视图')
    # Other reports may have reused the old temporary numerical histories.
    for base in (root/'results',root/'.cache/sessions'):
        for path in files_under(base):
            if path.suffix!='.json' or any(path.is_relative_to(t) for t in targets): continue
            try: data=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError): continue
            def references(value):
                if isinstance(value,dict):
                    for key,item in value.items():
                        if key in {'history_path','all_species_path'} and isinstance(item,str) and item: yield item
                        if key=='mechanism' and isinstance(item,dict) and item.get('path'): yield item['path']
                        yield from references(item)
                elif isinstance(value,list):
                    for item in value: yield from references(item)
            if any(Path(ref).resolve().is_relative_to(t) for ref in references(data) for t in targets):
                raise ValueError(f'其他结果仍引用该会话，未删除：{path}')
    for directory in targets:
        contained(root,directory)
        # Validate every directory before deleting any member of the selection.
        for folder,dirs,_ in os.walk(directory,followlinks=False):
            if any((Path(folder)/name).is_symlink() or (Path(folder)/name).is_junction() for name in dirs):
                raise ValueError('临时目录含链接，未自动删除')
    count=0
    for directory in targets:
        if directory.exists(): shutil.rmtree(directory);count+=1
    return count


def analysis_destination(root,state,kind,identity):
    base=Path(root)/'results'/kind
    workspace=state.get('session_workspace')
    if workspace:
        directory=base/f'temporary-{Path(workspace).name}-{identity}'
        record_component(workspace,directory)
        return directory
    return base/identity


def _rewrite(value,mappings):
    if isinstance(value,dict): return {_rewrite(k,mappings):_rewrite(v,mappings) for k,v in value.items()}
    if isinstance(value,list): return [_rewrite(v,mappings) for v in value]
    if isinstance(value,str):
        for source,target in mappings:
            # Path prefixes only; no substitution inside reaction equations or IDs.
            if value==source or value.startswith(source+'\\') or value.startswith(source+'/'):
                return target+value[len(source):]
    return value


def save_project(root,name,*,run_output=None,analyses=(),comparison=None,postprocessing=None,include_results=True,
                 include_analysis=True,include_figures=True,config=None):
    root=Path(root).resolve()
    if not re.fullmatch(r'[\w\-\u4e00-\u9fff ]{1,80}',name.strip()) or name.strip() in {'.','..'}:
        raise ValueError('项目名仅允许中文、字母、数字、空格、下划线和短横线，最多 80 字')
    if reasons:=busy_reasons(root): raise ValueError('任务运行中暂不能保存项目：'+'；'.join(reasons))
    destination=root/'results/projects'/name.strip()
    contained(root,destination)
    if destination.exists(): raise ValueError('同名项目已存在，请换名保存，已有项目不覆盖')
    staging=destination.with_name('.saving-'+uuid.uuid4().hex[:12])
    mappings=[];sources=[]
    certificates_path=root/'results/analysis-reuse-index.json'
    certificates=json.loads(certificates_path.read_text(encoding='utf-8')) if certificates_path.is_file() else {}
    staging.mkdir(parents=True)
    def copy_directory(source,target,*,media_only=False):
        source=contained(root,Path(source).resolve())
        if not source.is_dir(): raise ValueError(f'找不到来源目录：{source}')
        for path in files_under(source):
            contained(root,path)
            relative=path.relative_to(source)
            if media_only and path.suffix not in {'.png','.pdf','.svg'}: continue
            if any(part in {'.previews','saved-batches','rerun-backups','recovery-backups'} for part in relative.parts) or path.suffix in {'.log','.tmp','.zip'} or path.name in {'run.lock','CANCEL'}: continue
            if not include_figures and (path.suffix in {'.png','.pdf','.svg'} or 'figures' in relative.parts or 'views' in relative.parts): continue
            output=target/relative;output.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,output)
            if path.name=='report.json' and certificates:
                from .models import file_hash
                signature=certificates.get(file_hash(path))
                if signature:
                    report=json.loads(output.read_text(encoding='utf-8'))
                    if not report.get('numeric_signature'):
                        report['numeric_signature']=signature
                        atomic_json(output,report)
        # Final paths are stable even though copying occurs in staging.
        mappings.append((str(source),str(destination/target.relative_to(staging))))
        sources.append(str(source))
    try:
        if run_output and include_results:
            source=Path(run_output).resolve()
            if not (source/'manifest.json').is_file(): raise ValueError('当前没有可保存的模拟结果')
            copy_directory(source,staging/'simulation')
        elif run_output and include_figures and (Path(run_output)/'figures').is_dir():
            copy_directory(Path(run_output)/'figures',staging/'figures')
        if include_analysis:
            for index,path in enumerate(dict.fromkeys(map(str,analyses))):
                if (Path(path)/'report.json').is_file(): copy_directory(path,staging/'analysis'/f'{index:03d}')
        elif include_figures:
            for index,path in enumerate(dict.fromkeys(map(str,analyses))):
                if Path(path).is_dir(): copy_directory(path,staging/'analysis-figures'/f'{index:03d}',media_only=True)
        if include_figures and comparison: copy_directory(comparison,staging/'analysis-comparison',media_only=not include_analysis)
        if postprocessing and Path(postprocessing).is_dir():
            copy_directory(postprocessing,staging/'simulation' if include_results and run_output else staging/'postprocessing')
        # Materialize all numerical dependencies (including reused old runs and
        # snapshot hard links), so deleting an unsaved session cannot break a project.
        for path in list(files_under(staging)):
            if path.suffix!='.json': continue
            data=json.loads(path.read_text(encoding='utf-8'))
            def dependencies(value):
                if isinstance(value,dict):
                    if value.get('path') and 'species' in value and 'sha256' in value:
                        yield value['path']
                    for key,item in value.items():
                        if key in {'history_path','all_species_path'} and item:
                            yield item
                        if key=='mechanism' and isinstance(item,dict) and item.get('path'):
                            yield item['path']
                        yield from dependencies(item)
                elif isinstance(value,list):
                    for item in value: yield from dependencies(item)
            for reference in dependencies(data):
                source=Path(reference).resolve()
                if not source.is_file(): raise ValueError(f'结果依赖缺失，保存已中止：{source}')
                if any(str(source)==s or str(source).startswith(s+'\\') or str(source).startswith(s+'/') for s,_ in mappings): continue
                from .models import file_hash
                identity=file_hash(source)
                target=staging/'dependencies'/(identity[:24]+source.suffix)
                target.parent.mkdir(exist_ok=True)
                if not target.exists(): shutil.copy2(source,target)
                elif file_hash(target)!=identity: raise ValueError('Dependency filename collision; save cancelled')
                mappings.append((str(source),str(destination/'dependencies'/target.name)))
        mappings.sort(key=lambda pair:-len(pair[0]))
        for path in list(files_under(staging)):
            if path.suffix!='.json' and path.name not in {'config.yaml','precheck-config.yaml','figure.yaml','scoring.yaml'}: continue
            data=json.loads(path.read_text(encoding='utf-8')) if path.suffix=='.json' else yaml.safe_load(path.read_text(encoding='utf-8'))
            data=_rewrite(data,mappings)
            if path.suffix=='.json': atomic_json(path,data)
            else: path.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
        saved_config=_rewrite(config or {},mappings)
        if saved_config: saved_config['output']=str(destination/'simulation')
        (staging/'config.yaml').write_text(yaml.safe_dump(saved_config,allow_unicode=True,sort_keys=False),encoding='utf-8')
        info={'schema_version':1,'name':name.strip(),'saved_utc':datetime.now(timezone.utc).isoformat(),
              'include_results':include_results,'include_analysis':include_analysis,'include_figures':include_figures,'sources':sources}
        atomic_json(staging/'project.json',info)
        staging.rename(destination)
        return destination
    except Exception:
        # Only this newly-created, verified staging directory may be removed.
        contained(root,staging)
        shutil.rmtree(staging)
        raise
