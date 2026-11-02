"""Inspect cache use, or remove only reproducible obsolete artifacts."""
import argparse
import json
from pathlib import Path
from pyteck.respecth.runner import project_root
from pyteck.respecth.cache_maintenance import inventory,cleanup,LABELS,busy_reasons
from pyteck.respecth.atomic_io import atomic_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--clean-auto',action='store_true')
    args=parser.parse_args();root=project_root()
    before=inventory(root)
    summary={key:{'files':sum(i['category']==key for i in before['items']),
        'bytes':sum(i['bytes'] for i in before['items'] if i['category']==key)} for key in LABELS}
    report={'before':summary,'scan_errors':before['errors'],'active':busy_reasons(root)}
    if args.clean_auto: report['cleanup']=cleanup(root,['obsolete'],snapshot=before)
    atomic_json(root/'docs/delivery/cache-maintenance-audit.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
