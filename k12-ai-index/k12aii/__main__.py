import argparse

from . import analyze as an, baseline, calibrate, dose, exposure, visibility, frame, judge, power, run, sample
from .common import load_cfg


def main():
    ap = argparse.ArgumentParser(prog="k12aii")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("build-frame")
    sp.add_parser("power")
    sp.add_parser("baseline")
    p = sp.add_parser("visibility", help="exact-phrase counts of each school name in web corpora (infini-gram mini)")
    p.add_argument("action", choices=["query", "report"])
    p.add_argument("--sample", required=True); p.add_argument("--counts", default="runs/visibility/counts.parquet"); p.add_argument("--run-dir", default="runs/matched")
    p = sp.add_parser("exposure", help="verbatim-continuation + page-creation-timing experiments")
    p.add_argument("action", choices=["build", "positive-control", "qa-build", "mc-build", "truth-build", "run", "grade", "grade-direct", "report"])
    p.add_argument("--run-dir", default="runs/exposure")
    p.add_argument("--models", nargs="*", default=["gpt-4o"])
    p.add_argument("--model", default="gpt-4o", help="model whose cutoff defines the exposed/unexposed split")
    p.add_argument("--tasks", nargs="*", default=["cont", "qa"], help="cont qa mc mc_blind direct")
    p.add_argument("--no-fetch", action="store_true", help="reuse cached wiki creation dates")
    p.add_argument("--judge-provider"); p.add_argument("--judge-model")
    p = sp.add_parser("dose"); p.add_argument("--run-dirs", nargs="+", required=True)
    s = sp.add_parser("sample"); s.add_argument("--n", type=int); s.add_argument("--seed", type=int); s.add_argument("--out")
    for name in ("estimate", "check-tools", "run"):
        p = sp.add_parser(name)
        p.add_argument("--models", nargs="*")
        if name != "check-tools":
            p.add_argument("--sample", required=True)
        if name in ("run", "estimate"):
            p.add_argument("--tasks", nargs="*", help="kb kb_forced kb_masked bias:none bias:frl15 bias:frl85 bias:placebo (default: kb bias:none)")
            p.add_argument("--repeats", type=int, help="calls per (model, school, task); default config.repeats")
        if name == "run":
            p.add_argument("--run-dir", required=True)
    for name in ("judge", "calibrate-export", "calibrate-score", "analyze"):
        p = sp.add_parser(name); p.add_argument("--run-dir", required=True)
        if name in ("judge", "analyze", "calibrate-score"):
            p.add_argument("--judge-provider"); p.add_argument("--judge-model")
        if name in ("judge", "calibrate-export", "analyze"):
            p.add_argument("--frame", default=None, help="defaults to the frame in config")
    a = ap.parse_args()
    cfg = load_cfg()
    if getattr(a, "judge_provider", None): cfg["judge"]["provider"] = a.judge_provider
    if getattr(a, "judge_model", None): cfg["judge"]["model"] = a.judge_model
    fr = getattr(a, "frame", None) or cfg["paths"]["frame"]
    if a.cmd == "build-frame": frame.build(cfg)
    elif a.cmd == "power": power.report()
    elif a.cmd == "exposure":
        {"build": lambda: exposure.build_pool(cfg, a.run_dir, model=a.model, fetch=not a.no_fetch), "positive-control": lambda: exposure.add_positive_control(cfg, a.run_dir), "qa-build": lambda: exposure.build_qa(cfg, a.run_dir), "mc-build": lambda: exposure.build_mc(cfg, a.run_dir), "truth-build": lambda: exposure.build_truth(cfg, a.run_dir), "grade-direct": lambda: exposure.grade_direct(cfg, a.run_dir),
         "run": lambda: exposure.run_models(cfg, a.run_dir, a.models, a.tasks), "grade": lambda: exposure.grade_qa(cfg, a.run_dir),
         "report": lambda: exposure.report(cfg, a.run_dir)}[a.action]()
    elif a.cmd == "visibility":
        visibility.query_counts(a.sample, a.counts) if a.action == "query" else visibility.report(cfg, a.sample, a.counts, a.run_dir)
    elif a.cmd == "dose": dose.report(cfg, a.run_dirs)
    elif a.cmd == "baseline":
        import pandas as pd
        from .common import resolve
        baseline.report(pd.read_parquet(resolve(cfg["paths"]["frame"])))
    elif a.cmd == "sample": sample.draw(cfg, a.n, a.seed, a.out)
    elif a.cmd == "estimate": run.estimate(cfg, a.sample, a.models, a.tasks, a.repeats)
    elif a.cmd == "check-tools": run.check_tools(cfg, a.models)
    elif a.cmd == "run": run.run(cfg, a.sample, a.run_dir, a.models, a.tasks, a.repeats)
    elif a.cmd == "judge": judge.run_judge(cfg, a.run_dir, fr)
    elif a.cmd == "calibrate-export": calibrate.export(cfg, a.run_dir, fr)
    elif a.cmd == "calibrate-score": calibrate.score(cfg, a.run_dir)
    elif a.cmd == "analyze": an.analyze(cfg, a.run_dir, fr)


main()
