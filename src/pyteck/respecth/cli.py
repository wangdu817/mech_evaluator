"""Batch entrypoint and offline re-evaluation/plotting."""
import argparse
from collections import Counter
from pathlib import Path
import json
import yaml
from pyteck.respecth.yaml_io import load_yaml

from .reader import discover_experiments, load_experiment
from .runner import load_config, prepare_run, run_project, load_run
from .evaluation import evaluate_results
from .reporting import render_figures, export_results
from .solvers import atomic_json


def main():
    parser = argparse.ArgumentParser(prog="pyteck-respecth")
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory", help="Read experimental XML without simulation")
    inventory.add_argument("root")
    check = sub.add_parser("check", help="Prepare mechanisms and validate all cases")
    check.add_argument("config")
    run = sub.add_parser("run", help="Run/resume the selected batch")
    run.add_argument("config")
    run.add_argument('--retry-failed', action='store_true', help='Retry failed/cancelled cases; retain verified success caches')
    run.add_argument('--force-rerun', action='store_true', help='Recalculate selected cases, bypassing local and historical caches')
    run.add_argument('--discard-previous', action='store_true', help='With --force-rerun, delete all prior results in this output directory instead of backing them up')
    redraw = sub.add_parser("redraw", help="Redraw from saved predictions without simulation")
    redraw.add_argument("output")
    redraw.add_argument("--figure-config")
    score = sub.add_parser("score", help="Re-evaluate saved predictions")
    score.add_argument("output")
    score.add_argument("--scoring-config")
    cancel = sub.add_parser("cancel", help="Request cancellation of an active run")
    cancel.add_argument("output")
    snapshot = sub.add_parser('snapshot', help='Read committed results while a batch continues running')
    snapshot.add_argument('output')
    compare = sub.add_parser("compare", help="Combine saved independent mechanism runs without simulation")
    compare.add_argument("output")
    compare.add_argument("sources", nargs="+")
    compare.add_argument("--dataset-policy", choices=["intersection", "union"], default="intersection")
    analysis = sub.add_parser('analyze', help='Analyze an existing verified case without changing its batch')
    analysis.add_argument('output')
    analysis.add_argument('--case', required=True, help='Full saved case ID')
    analysis.add_argument('--species', help='ROP species; required unless --no-rop')
    analysis.add_argument('--no-rop', action='store_true', help='Compute sensitivity only')
    analysis.add_argument('--row', type=int, help='Stored history row; default ignition event or final state')
    analysis.add_argument('--target', help='Existing observation key for sensitivity')
    analysis.add_argument('--reactions', help='1-based comma-separated reaction numbers, or all')
    analysis.add_argument('--temperature-proxy', action='store_true', help='Native temperature sensitivity for ignition at a fixed time')
    analysis.add_argument('--time', type=float, help='Fixed proxy time in seconds, default original simulated ignition delay')
    args = parser.parse_args()
    if args.command == "inventory":
        experiments = [load_experiment(p) for p in discover_experiments(args.root)]
        print(json.dumps({"xml_count": len(experiments),
            "points": sum(len(g.points) for e in experiments for g in e.groups),
            "measurement_values": sum(len(s.y) for e in experiments for s in e.observations),
            "types": dict(Counter(e.kind for e in experiments)),
            "parse_issues": {e.path: e.issues for e in experiments if e.issues}}, ensure_ascii=False, indent=2))
    elif args.command == 'snapshot':
        from .live_snapshot import create_completed_snapshot
        print(str(create_completed_snapshot(args.output)))
    elif args.command == "check":
        _, cases, notes = prepare_run(load_config(args.config))
        invalid = [{"case": c.id, "issues": c.issues} for c in cases if c.issues]
        print(json.dumps({"cases": len(cases), "blocked": len(invalid), "warnings": notes,
                          "invalid_cases": invalid}, ensure_ascii=False, indent=2))
        return 1 if invalid else 0
    elif args.command == "run":
        if args.discard_previous and not args.force_rerun: parser.error('--discard-previous requires --force-rerun')
        config = load_config(args.config)
        if args.retry_failed: config.retry_failed = True
        manifest = run_project(config,
                               lambda n, total, identity, status: print(f"{n}/{total} {identity[:12]} {status}", flush=True), force_rerun=args.force_rerun, discard_previous=args.discard_previous)
        print(manifest["status"])
        return 1 if any(r["status"] != "success" for r in manifest["results"]) else 0
    elif args.command == "compare":
        from .saved_runs import combine_saved_runs
        manifest = combine_saved_runs(args.sources,args.output,args.dataset_policy)
        print(json.dumps(manifest["saved_comparison"],ensure_ascii=False,indent=2))
    elif args.command == "cancel":
        directory = Path(args.output).resolve()
        if not (directory / "run.lock").exists():
            parser.error("No active run lock in this output directory")
        (directory / "CANCEL").touch()
    elif args.command == 'analyze':
        import numpy as np
        from dataclasses import asdict
        from .analysis import history_coordinates, analysis_identity
        from .analysis_job import run_job
        from .gas_io import load_gas
        from .runner import project_root
        manifest, experiments, cases, results = load_run(args.output)
        case = next((c for c in cases if c.id == args.case), None)
        result = next((r for r in results if r.case_id == args.case), None)
        if case is None or result is None:
            parser.error('Selected case/result does not exist in this batch')
        _, coordinates = history_coordinates(case,result)
        row=args.row if args.row is not None else int(np.argmin(abs(coordinates-next(iter(result.predictions.values()))))) if case.kind=='ignition' else len(coordinates)-1
        if not args.no_rop and not args.species: parser.error('ROP requires --species')
        if args.no_rop and not (args.target or args.temperature_proxy): parser.error('--no-rop requires a sensitivity target')
        settings={'rop':not args.no_rop,'species':args.species,'row':row,'top_n':15,'sensitivity':bool(args.target or args.temperature_proxy)}
        if args.target or args.temperature_proxy:
            if not args.reactions: parser.error('Sensitivity requires --reactions')
            gas=load_gas(case.mechanism.path,case.mechanism.phase)
            settings.update(target_key=args.target,reaction_indices=list(range(gas.n_reactions)) if args.reactions=='all' else [int(v)-1 for v in args.reactions.split(',')],delta=.01,zero_floor=1e-20)
            if args.temperature_proxy:
                settings.update(target_key='temperature_at_fixed_time',reference_time=args.time or next(iter(result.predictions.values())))
        directory=project_root()/'results/analysis'/analysis_identity(case,result,settings)
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/'report.json'
        if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('status')=='completed':
            print(str(directory)); return 0
        (directory/'CANCEL').unlink(missing_ok=True)
        atomic_json(directory/'job.json',{'case':asdict(case),'result':asdict(result),'settings':settings,'source_run':str(Path(args.output).resolve())})
        report=run_job(directory/'job.json')
        print(json.dumps({'status':report['status'],'output':str(directory),'reason':report.get('reason')},ensure_ascii=False))
        return 0 if report['status']=='completed' else 1
    else:
        manifest, experiments, cases, results = load_run(args.output)
        if args.command == "redraw":
            options = (load_yaml(Path(args.figure_config).read_text(encoding="utf-8"))
                       if args.figure_config else manifest["config"].get("figure", {}))
            paths = render_figures(experiments, {"cases": cases, "results": results},
                                   {**options, "output": str(Path(args.output) / "figures")})
            print(json.dumps(paths, ensure_ascii=False))
        else:
            options = (load_yaml(Path(args.scoring_config).read_text(encoding="utf-8"))
                       if args.scoring_config else manifest["config"].get("scoring", {}))
            evaluation = evaluate_results(experiments, results, options, cases)
            atomic_json(Path(args.output) / "evaluation.json", evaluation)
            export_results({"output": args.output, "evaluation": evaluation, "cases": cases})
            print(json.dumps(evaluation["formal"]["mechanisms"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
