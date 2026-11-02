"""XML coverage based on original measurement identities, separately per mechanism."""
from collections import defaultdict, Counter
from pathlib import Path
import math


def dataset_coverage(experiments,cases,results,mechanisms=None):
    mechanisms=list(mechanisms) if mechanisms is not None else sorted({c.mechanism.id for c in cases})
    result_map={r.case_id:r for r in results}
    grouped=defaultdict(list)
    for case in cases: grouped[case.experiment_id,case.mechanism.id].append(case)
    records=[]
    for experiment in experiments:
        required={(s.id,point) for s in experiment.observations for point in s.point_indices}
        for mechanism in mechanisms:
            available=set(); attempted=0; ready_cases=0; grid_ready=0; statuses=Counter()
            scoring=[c for c in grouped[experiment.id,mechanism] if c.role=='scoring']
            for case in grouped[experiment.id,mechanism]:
                result=result_map.get(case.id)
                status=result.status if result else 'not_computed'
                if case.role=='scoring': statuses[status]+=1
                if result and status not in {'cancelled','not_computed'}: attempted+=1
                if not result or status!='success' or result.validation.get('passed') is not True: continue
                valid_targets=[t for t in case.targets if t['key'] in result.predictions
                    and math.isfinite(result.predictions[t['key']])
                    and (t['quantity'] not in {'ignition delay','laminar burning velocity'} or result.predictions[t['key']]>0)]
                if case.role=='scoring':
                    if len(valid_targets)==len(case.targets): ready_cases+=1
                    for target in valid_targets:
                        available.update((target.get('series_id',target['key']),point) for point in target['point_indices'])
                    grid_ready += sum(t.get('role')=='plotting' for t in valid_targets)
                elif valid_targets: grid_ready+=1
            count=len(required & available)
            category=('全部完成' if required and count==len(required) else '部分完成' if count or grid_ready
                      else '计算失败或不可用' if attempted else '未运行')
            records.append({'experiment_id':experiment.id,'XML':Path(experiment.path).name,'机理':mechanism,
                '分类':category,'原始测量预测':count,'原始测量总数':len(required),
                '覆盖率':count/len(required) if required else 0.,'原始工况可用':ready_cases,
                '原始工况总数':len(scoring),'加密工况可用':grid_ready,'有模拟曲线':bool(count or grid_ready),
                '失败状态':dict(statuses)})
    return records


def dataset_options(experiments,cases,results,mechanisms=None):
    records=dataset_coverage(experiments,cases,results,mechanisms)
    groups=defaultdict(list)
    for record in records: groups[record['experiment_id']].append(record)
    options={}
    for experiment in experiments:
        rows=groups[experiment.id]
        category=('全部完成' if rows and all(r['分类']=='全部完成' for r in rows) else
                  '部分完成' if any(r['有模拟曲线'] for r in rows) else
                  '计算失败或不可用' if any(r['分类']=='计算失败或不可用' for r in rows) else '未运行')
        options[experiment.id]={'category':category,'available':any(r['有模拟曲线'] for r in rows),
            'label':Path(experiment.path).stem}
    return options,records
