"""Shared sensitivity chart for saved-result preview and scientific export."""
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def sensitivity_figure(report, sensitivity=None, limit=None):
    sensitivity = report.get('sensitivity') if sensitivity is None else sensitivity
    if not sensitivity:
        return None
    normalized = abs(sensitivity['baseline']) > sensitivity['zero_floor']
    key = 'coefficient' if normalized else 'derivative'
    rows = [r for r in sensitivity['rows'] if r['status'] == 'success'
            and r.get(key) is not None and math.isfinite(r[key])]
    limit = report['settings'].get('top_n', 15) if limit is None else limit
    rows = sorted(rows, key=lambda r: abs(r[key]), reverse=True)[:limit][::-1]
    if not rows:
        return None
    figure, axis = plt.subplots(figsize=(12, max(4, len(rows)*.38)))
    axis.barh([f"R{r['reaction_number']}  {r['equation']}" for r in rows],
              [r[key] for r in rows],
              color=['#377eb8' if r[key] >= 0 else '#e41a1c' for r in rows])
    axis.axvline(0, color='black', linewidth=.8)
    axis.set_xlabel('Normalized sensitivity coefficient S (dimensionless)' if normalized
                    else 'dy / d ln(multiplier) (observable SI unit)')
    axis.set_title(f"{sensitivity['target_key']} | {sensitivity.get('quantity', 'original observable')}")
    case = report['case']
    condition = case['condition']
    figure.suptitle(f"{case['mechanism']['id']} | {case['id'][:12]} | "
                   f"T0={condition['temperature']:g} K, P0={condition['pressure']:g} Pa")
    axis.tick_params(direction='in', top=True, right=True, labelsize=9)
    for spine in axis.spines.values():
        spine.set_visible(True)
    figure.tight_layout()
    return figure
