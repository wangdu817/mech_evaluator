"""Delete inactive operational logs only, preserving mechanism audit evidence."""
from pathlib import Path
import argparse
import datetime
import json
import os
import psutil

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','.venv313','.venv314','node_modules'}


def files_under(directory):
    for base,dirs,files in os.walk(directory):
        dirs[:]=[d for d in dirs if d not in SKIP and not Path(base,d).is_symlink()]
        for name in files:
            path=Path(base,name)
            if not path.is_symlink() and path.resolve().is_relative_to(ROOT):yield path


def active_files():
    opened=set()
    for process in psutil.process_iter(['cmdline','cwd']):
        try:
            cwd=process.info['cwd']
            belongs=(cwd and Path(cwd).resolve().is_relative_to(ROOT)) or str(ROOT).casefold() in ' '.join(process.info['cmdline'] or []).casefold()
            if belongs:opened.update(str(Path(f.path).resolve()).casefold() for f in process.open_files())
        except (psutil.Error,OSError):pass
    return opened


def protected_audit(path):
    relative=path.relative_to(ROOT)
    if not relative.parts or relative.parts[0]!='results':return False
    name=path.name.lower()
    return name.startswith('conversion') or name=='initial-conversion.log' or name=='load-warnings.log'


def result_inventory():
    return {str(p.relative_to(ROOT)):(p.stat().st_size,p.stat().st_mtime_ns)
            for p in files_under(ROOT/'results') if p.suffix.lower()!='.log'}


def clean(apply=False):
    opened=active_files();before=result_inventory();deleted=[];kept=[]
    for path in files_under(ROOT):
        if path.suffix.lower()!='.log':continue
        relative=str(path.relative_to(ROOT))
        if protected_audit(path):kept.append({'path':relative,'reason':'mechanism conversion/load audit'});continue
        if str(path.resolve()).casefold() in opened:kept.append({'path':relative,'reason':'active process handle'});continue
        size=path.stat().st_size
        if apply:
            try:path.unlink()
            except OSError as error:
                kept.append({'path':relative,'reason':str(error)});continue
        deleted.append({'path':relative,'bytes':size})
    after=result_inventory()
    report={'apply':apply,'deleted_logs':deleted,'kept_logs':kept,
            'freed_bytes':sum(p['bytes'] for p in deleted) if apply else 0,
            'result_files':len(before),'result_inventory_unchanged':before==after,
            'result_check':'all non-log result paths, lengths and modification times',
            'excluded_directories':sorted(SKIP)}
    if apply:
        directory=ROOT/'results/runtime';directory.mkdir(parents=True,exist_ok=True)
        stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        output=directory/f'log-cleanup-{stamp}.json'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('清理报告：'+str(output))
    print(json.dumps({k:v for k,v in report.items() if k not in {'deleted_logs','kept_logs'}},ensure_ascii=False))
    print(f"日志：{'删除' if apply else '拟删除'} {len(deleted)} 份，保留 {len(kept)} 份。")
    if before!=after:raise RuntimeError('清理期间结果目录内容发生变化，请查看审计报告。')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    clean(parser.parse_args().apply)
