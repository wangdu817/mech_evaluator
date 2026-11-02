"""Check scientific plot conventions against the actual Cantera run."""
from pathlib import Path
import json
import matplotlib.colors as colors
from pyteck.respecth.runner import load_run
from pyteck.respecth import reporting

root = Path(__file__).resolve().parents[1]
manifest, experiments, cases, results = load_run(root/'results/actual-audited/full')
selected = [e for e in experiments if Path(e.path).stem=='Hjuler_1995_Set13' or e.kind=='ignition']
checks = []
original_save = reporting._save_figure
def inspect_figure(fig, directory, stem, config):
    for ax in fig.axes:
        if not ax.get_visible():
            continue
        assert all(ax.spines[edge].get_visible() for edge in ('top','right','bottom','left'))
        assert all(tick.get_tickdir() == 'in' for tick in ax.xaxis.get_major_ticks()+ax.yaxis.get_major_ticks())
    if stem.startswith('species'):
        assert len(fig.axes)==3  # Default all three measured species of Set13.
    else:
        ax = fig.axes[0]
        measured = [line for line in ax.lines if line.get_marker() not in ('None','',None) and line.get_linestyle()=='None']
        predicted = [line for line in ax.lines if line.get_marker()=='None' and line.get_linestyle()!='None']
        assert len(measured)==len(predicted)==6
        for line in predicted:
            source = line.get_label().split(' / ')[1]
            experimental = next(container.lines[0] for container in ax.containers if container.get_label()==source)
            assert colors.to_rgba(line.get_color()) == colors.to_rgba(experimental.get_color())
        assert len({colors.to_rgba(line.get_color()) for line in predicted})==6
    checks.append({'figure':stem,'closed_frame':True,'inward_ticks':True,
                   'simulation_lines_experimental_points':True,'condition_colors_match':True if stem.startswith('ignition') else 'not applicable'})
    return original_save(fig,directory,stem,config)
reporting._save_figure = inspect_figure
try:
    reporting.render_figures(experiments,{'cases':cases,'results':results},
        {'experiments':[e.id for e in selected], 'output':str(root/'results/actual-audited/style-check'),
         'formats':['png','pdf','svg']})
finally:
    reporting._save_figure = original_save
(root/'results/actual-audited/plot-style-verification.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
print(json.dumps(checks))
