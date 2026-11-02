"""Reload changed UI code only when project services have no running jobs."""
import argparse
import json
from pathlib import Path
import psutil
from launch_ui import project_service, launch, ROOT, restart_blockers
from pyteck.respecth.atomic_io import atomic_json
from pyteck.respecth.yaml_io import load_yaml
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    from pyteck.respecth.cache_maintenance import busy_reasons
    if reasons:=busy_reasons(ROOT):
        raise RuntimeError('Active jobs; refusing restart: '+'; '.join(reasons))
    services = [psutil.Process(pid) for port in (8502,8503) if (pid:=project_service(port))]
    for service in services:
        if reasons:=restart_blockers(service.pid):
            raise RuntimeError('Active jobs; refusing restart: '+'; '.join(reasons))
        if service.children(recursive=True):
            raise RuntimeError(f'PID {service.pid} has active child jobs; refusing restart')
        for lock in (ROOT/'results').rglob('run.lock'):
            owner = json.loads(lock.read_text(encoding='utf-8'))
            if owner.get('pid')==service.pid:
                raise RuntimeError(f'Run lock belongs to this service: {lock}; refusing restart')
    if args.config:
        text = args.config.read_text(encoding='utf-8-sig')
        data = load_yaml(text)
        state_path = ROOT/'results/ui-state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        atomic_json(ROOT/'docs/delivery/ui-state-before-update.json', state)
        state.update(config_text=text, mechanism_entries=data['mechanisms'],
            mechanism_list_yaml=yaml.safe_dump(data['mechanisms'],allow_unicode=True,sort_keys=False),
            input_datasets=data['datasets'], output=data['output'])
        atomic_json(state_path, state)
    for service in services:
        service.terminate()
        service.wait(timeout=10)
    print(json.dumps(launch(8502,no_browser=True),ensure_ascii=False))


if __name__=='__main__':
    main()
