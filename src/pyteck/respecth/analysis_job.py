"""One diagnostic job per fresh process, with independent artifacts and cancel."""
from dataclasses import asdict
from pathlib import Path
import csv
import json
import re
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .analysis_reconstruction import compute_rop, compute_sensitivity, compute_temperature_sensitivity
from .atomic_io import atomic_json
from .cases import prepare_mechanism
from .models import case_from_dict, result_from_dict, file_hash, digest
from .gas_io import load_gas
from .runner import project_root
from .solvers import Cancelled


def export_analysis(report, directory):
    directory=Path(directory)
    for name in ('rop','sensitivity'):
        rows=report.get(name,{}).get('rows',[])
        if rows:
            if name=='rop':
                rows=[{**row,'rate_unit':report['rop']['rate_unit'],
                    'aggregation':report['rop'].get('aggregation','local_state')} for row in rows]
            columns=list(dict.fromkeys(k for row in rows for k in row))
            with (directory/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=['case_id','mechanism_id',*columns])
                writer.writeheader()
                writer.writerows({'case_id':report['case']['id'],'mechanism_id':report['case']['mechanism']['id'],**row} for row in rows)
    figures={}
    rop=report.get('rop')
    limit=report['settings'].get('top_n',15)
    if rop and rop['rows']:
        rows=rop['rows'][:limit][::-1]
        figure, axes=plt.subplots(1,2,figsize=(14,max(4,len(rows)*.32)),sharey=True)
        labels=[f"R{r['reaction_number']}  {r['equation']}" for r in rows]
        axes[0].barh(labels,[r['formation'] for r in rows],color='#377eb8')
        axes[1].barh(labels,[-r['destruction'] for r in rows],color='#e41a1c')
        axes[0].set_title('Formation'); axes[1].set_title('Destruction')
        for axis in axes:
            axis.set_xlabel('Domain-integrated ROP (mol m$^{-3}$)' if rop.get('aggregation')=='domain_integral' else 'Chemical ROP (mol m$^{-3}$ s$^{-1}$)')
        figures['rop']=figure
        profile=rop['profile']; selected=rop['profile_reaction_indices'][:5]
        figure,axis=plt.subplots(figsize=(10,5))
        for column,index in enumerate(selected):
            axis.plot([r['coordinate'] for r in profile],[r['net'][column] for r in profile],label=f'R{index+1}')
        if rop.get('aggregation')!='domain_integral':
            axis.axvline(rop['snapshot']['coordinate'],color='gray',linestyle='--',label='Selected state')
        axis.set_xlabel('Position (m)' if rop['coordinate_kind']=='grid' else 'Time (s)')
        axis.set_ylabel('Net chemical ROP (mol m$^{-3}$ s$^{-1}$)'); axis.legend()
        figures['rop_profile']=figure
    from .analysis_plotting import sensitivity_figure
    figure=sensitivity_figure(report)
    if figure is not None:
        figures['sensitivity']=figure
    for name,figure in figures.items():
        for axis in figure.axes:
            axis.tick_params(direction='in',top=True,right=True,labelsize=8)
            for spine in axis.spines.values(): spine.set_visible(True)
        figure.suptitle(f"{report['case']['mechanism']['id']} | {report['case']['id'][:12]} | T0={report['case']['condition']['temperature']:g} K")
        figure.tight_layout()
        for extension in ('png','pdf','svg'):
            figure.savefig(directory/f'{name}.{extension}',dpi=300,bbox_inches='tight')
        plt.close(figure)


def run_job(payload_path):
    payload_path=Path(payload_path).resolve(); directory=payload_path.parent
    if not directory.is_relative_to(project_root()/'results/analysis'):
        raise ValueError('Diagnostic jobs must stay in the project results/analysis directory')
    payload=json.loads(payload_path.read_text(encoding='utf-8'))
    case=case_from_dict(payload['case']); result=result_from_dict(payload['result']); settings=payload['settings']
    cancel=directory/'CANCEL'
    from .analysis_cache import numeric_signature
    report={'numeric_signature':numeric_signature(),'schema_version':1,'status':'running','case':payload['case'],'source_run':payload['source_run'],
            'settings':settings,'comparison':payload.get('comparison',[]),'rop':{},'sensitivity':{}}
    def progress(done,total,message):
        atomic_json(directory/'progress.json',{'status':'running','done':done,'total':total,'message':message})
    try:
        # Re-prepare from original hashed inputs; reject changed chemistry or phase.
        inputs=case.mechanism.provenance['inputs']
        if any(Path(p['path']).exists() and file_hash(p['path'])!=p['sha256'] for p in inputs.values()):
            raise ValueError('Original mechanism input changed after this case was computed')
        unavailable=[p['path'] for p in inputs.values() if not Path(p['path']).exists()]
        if unavailable:
            # Historical results retain a self-contained YAML. Verify its full
            # canonical resolved identity rather than require the moved source.
            gas=load_gas(case.mechanism.path,case.mechanism.phase)
            # Use the archived serialization itself. Serializing the parsed
            # YAML again can round converted SI constants a second time.
            resolved=Path(case.mechanism.path).read_text(encoding='utf-8')
            import cantera as ct
            identity=digest({'inputs':inputs,'resolved':resolved,'phase':gas.name,'cantera':ct.__version__,'map':case.mechanism.species_map})
            if identity!=case.mechanism.sha256:
                raise ValueError('Archived resolved YAML identity differs from the original simulation')
            fresh=case.mechanism
            report['source_verification']={'mode':'archived self-contained YAML, canonical identity checked','unavailable_original_inputs':unavailable}
        else:
            config={k:p['path'] for k,p in inputs.items()}
            config.update(id=case.mechanism.id,phase=case.mechanism.phase,
                          species_map=case.mechanism.species_map,prepared_dir=str(directory/'prepared'))
            fresh=prepare_mechanism(config)
            if fresh.sha256!=case.mechanism.sha256:
                raise ValueError('Resolved mechanism identity changed after this case was computed')
            report['source_verification']={'mode':'original inputs and resolved YAML identity checked'}
        report['prepared_input_sha256']=file_hash(fresh.path)
        case.mechanism=fresh
        if not settings.get('rop', True) and not settings.get('sensitivity'):
            raise ValueError('Select ROP, sensitivity, or both')
        if settings.get('rop', True):
            progress(0,1,'Computing full-domain PFR ROP' if case.kind=='pfr' else 'Computing chemical ROP')
            report['rop']=compute_rop(case,result,settings['species'],settings['row'],settings.get('top_n',15),cancel_file=cancel)
        atomic_json(directory/'report.json',report)
        if settings.get('sensitivity'):
            def checkpoint(data):
                report['sensitivity']=data; atomic_json(directory/'report.json',report)
            if settings['target_key']=='temperature_at_fixed_time':
                report['sensitivity']=compute_temperature_sensitivity(case,result,settings['reaction_indices'],
                    settings['reference_time'],cancel,progress,directory=directory)
            else:
                report['sensitivity']=compute_sensitivity(case,result,settings['target_key'],settings['reaction_indices'],
                    directory,settings.get('delta',.01),settings.get('zero_floor',1e-20),cancel,progress,checkpoint)
        report['status']='completed'
    except Cancelled as error:
        report.update(status='cancelled',reason=str(error))
    except Exception as error:
        report.update(status='failed',reason=str(error))
    finally:
        atomic_json(directory/'report.json',report)
        export_analysis(report,directory)
        atomic_json(directory/'progress.json',{'status':report['status'],'message':report.get('reason','Analysis complete')})
    return report


if __name__=='__main__':
    raise SystemExit(0 if run_job(sys.argv[1])['status']=='completed' else 1)
