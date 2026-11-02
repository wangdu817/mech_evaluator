"""Read saved diagnostic reports and compare reactions without new solves."""
from collections import OrderedDict
from pathlib import Path
import csv
import json
import math

import h5py
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .native_analysis import species_sensitivity_view
from .atomic_io import atomic_json


def condition_label(report):
    case=report['case']; c=case['condition']
    dataset=case.get('experiment_id','').split('-',1)[-1]
    text=f"{dataset}/{case.get('group_id','')} | T={c['temperature']:g} K, P={c['pressure']/101325:g} atm"
    if c.get('residence_time') is not None: text+=f", tau={c['residence_time']:.4g} s"
    if c.get('scan_name')=='equivalence ratio': text+=f", phi={c['scan_value']:g}"
    sensitivity=report.get('sensitivity',{})
    if sensitivity.get('is_ignition_delay_proxy'):
        text+=f", t_sens={sensitivity['reference_time']:.4g} s (temperature proxy)"
    rop=report.get('rop',{})
    if rop and rop.get('aggregation','local_state')!='domain_integral' and rop.get('snapshot'):
        text+=f", {rop.get('coordinate_kind','position')}={rop['snapshot']['coordinate']:.4g}"
    return text+' | '+case['id'][:8]


def available_species(report, mode):
    if mode=='rop':
        data=report.get('rop',{})
        return [data['species']] if data else []
    data=report.get('sensitivity',{})
    path=data.get('all_species_path')
    if path and Path(path).is_file():
        with h5py.File(path,'r') as stream: names=stream['species'].asstr()[:].tolist()
        return (['Temperature'] if data.get('is_ignition_delay_proxy') else [])+names
    if not data: return []
    target=next((t for t in report['case'].get('targets',[]) if t['key']==data['target_key']),{})
    return [target.get('species') or ('Temperature' if data.get('is_ignition_delay_proxy') else target.get('quantity') or data['target_key'])]


def comparison_series(reports, mode, species, quantity='X', rop_metric='net'):
    series=[]; omitted=[]
    for source,report in reports:
        if not report.get(mode): continue
        for name in species:
            if name not in available_species(report,mode):
                omitted.append(f"{report['case']['mechanism']['id']} / {report['case']['id'][:8]} / {name}：未保存此分析")
                continue
            data=report.get(mode,{})
            if mode=='sensitivity' and name!='Temperature' and data.get('all_species_path'):
                data=species_sensitivity_view(data['all_species_path'],name,quantity,data['zero_floor'])
            case=report['case']; mechanism=case['mechanism']
            group=(mechanism.get('sha256') or str(source),case.get('kind','unknown'),name,
                   'temperature' if name=='Temperature' else quantity if mode=='sensitivity' and data.get('all_species_path') else data.get('quantity','original'),
                   data.get('aggregation','local_state') if mode=='rop' else 'sensitivity',
                   data.get('rate_unit','') if mode=='rop' else '')
            series.append({'source':str(source),'case':case,'data':data,'group':group,
                           'species':name,'label':condition_label(report),'mode':mode,'rop_metric':rop_metric})
    return series,omitted


def comparison_figure(series, limit=15, columns=2):
    groups=OrderedDict()
    for entry in series: groups.setdefault(entry['group'],[]).append(entry)
    if not groups: raise ValueError('所选分析没有可绘制的数据。')
    if len(groups)>8: raise ValueError('单张图最多 8 个子图，请减少物种或机理数量。')
    if any(len(entries)>8 for entries in groups.values()): raise ValueError('每个子图最多比较 8 个工况，请分组绘制。')
    columns=min(columns,len(groups)); rows=math.ceil(len(groups)/columns)
    figure,axes=plt.subplots(rows,columns,figsize=(14 if columns>1 else 12,5*rows),squeeze=False)
    exported=[]
    colors=plt.get_cmap('tab10'); hatches=['','///','xxx','\\\\','...','++','oo','--']
    for axis,(group,entries) in zip(axes.flat,groups.items()):
        normalized=entries[0]['mode']=='sensitivity' and all(abs(e['data']['baseline'])>e['data']['zero_floor'] for e in entries)
        key=('coefficient' if normalized else 'derivative') if entries[0]['mode']=='sensitivity' else entries[0]['rop_metric']
        maps=[]; ranks={}; equations={}
        for entry in entries:
            values={}
            for r in entry['data']['rows']:
                number=r['reaction_number']; equation=r['equation']
                if number in equations and equations[number]!=equation:
                    plt.close(figure); raise ValueError('同一机理身份的反应编号与方程冲突，不能合并。')
                equations[number]=equation
                value=r.get(key)
                if r.get('status','success')!='success' or value is None or not math.isfinite(value): continue
                if key=='destruction': value=-value
                values[number]=value
                ranks[number]=max(ranks.get(number,0),abs(value))
            maps.append(values)
        chosen=sorted(ranks,key=lambda n:(-ranks[n],n))[:limit][::-1]
        if not chosen:
            axis.text(.5,.5,'No finite saved values',ha='center',transform=axis.transAxes)
            continue
        height=.78/len(entries); y=np.arange(len(chosen))
        for i,(entry,values) in enumerate(zip(entries,maps)):
            positions=y+(i-(len(entries)-1)/2)*height
            # Unanalysed reactions stay absent, never silently become zero.
            valid=[j for j,n in enumerate(chosen) if n in values]
            axis.barh(positions[valid],[values[chosen[j]] for j in valid],height=height,
                      label=entry['label'],color=colors(i),hatch=hatches[i],edgecolor='black',linewidth=.3)
            for j,n in enumerate(chosen):
                if n not in values: axis.plot(0,positions[j],marker='x',color=colors(i),markersize=4)
                exported.append({'source_report':entry['source'],'case_id':entry['case']['id'],
                    'mechanism_id':entry['case']['mechanism']['id'],'mechanism_sha256':entry['case']['mechanism'].get('sha256',''),
                    'species':entry['species'],'mode':entry['mode'],'metric':key,'reaction_number':n,
                    'equation':equations[n],'value':values.get(n),'status':'saved' if n in values else 'not_saved',
                    'aggregation':entry['data'].get('aggregation',''),'unit':entry['data'].get('rate_unit','dimensionless' if normalized else 'observable SI unit')})
        axis.set_yticks(y,[f'R{n}  {equations[n]}' for n in chosen],fontsize=8)
        padding=max(.7,(8-len(chosen))/2+.5)
        axis.set_ylim(-padding,len(chosen)-1+padding)
        axis.axvline(0,color='black',linewidth=.7)
        if entries[0]['mode']=='sensitivity':
            xlabel='Normalized sensitivity coefficient S' if normalized else 'dy / d ln(multiplier) (observable SI unit)'
        else: xlabel=f"{key} ROP ({group[-1]}) | {group[-2]}"
        axis.set_xlabel(xlabel)
        axis.set_title(f"{entries[0]['case']['mechanism']['id']} | {entries[0]['species']} | {group[1]} / {group[3]}",fontsize=10)
        axis.tick_params(direction='in',top=True,right=True,labelsize=8)
        for spine in axis.spines.values(): spine.set_visible(True)
        axis.legend(fontsize=6,loc='best')
    for axis in list(axes.flat)[len(groups):]: axis.set_visible(False)
    figure.tight_layout()
    return figure,exported


def export_comparison(reports, directory, mode, species, quantity='X', rop_metric='net', limit=15, columns=2):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    series,omitted=comparison_series(reports,mode,species,quantity,rop_metric)
    figure,rows=comparison_figure(series,limit,columns)
    try:
        for suffix in ['png','pdf','svg']:
            figure.savefig(directory/f'comparison.{suffix}',dpi=300,bbox_inches='tight')
    finally: plt.close(figure)
    with (directory/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        if rows:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    atomic_json(directory/'comparison.json',{'mode':mode,'species':species,'quantity':quantity,'rop_metric':rop_metric,
        'limit':limit,'columns':columns,'sources':[{'path':str(path),'case':report['case']} for path,report in reports],
        'omitted':omitted,'reaction_alignment':'same mechanism SHA and reaction number; equation conflicts rejected',
        'missing_values':'not_saved (cross marker), never filled with zero','rows':rows})
    return omitted
