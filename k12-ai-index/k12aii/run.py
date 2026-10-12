"""Run the tasks against models. Resumable: (model, nces_id, task) already in responses.jsonl are skipped.
Tasks: kb (A1-A7 + D1) | kb_forced (A1-A7, no UNKNOWN) | bias:none | bias:frl15 | bias:frl85 (counterfactual poverty statement)."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

from .common import append_jsonl, model_by_key, read_jsonl, resolve
from .prompts import BIAS_ARMS, build_bias_prompt, build_forced_prompt, build_masked_prompt, build_prompt
from .providers import available, complete

DEFAULT_TASKS = ["kb", "bias:none"]


def select_models(cfg, keys):
    ms = [model_by_key(cfg, k) for k in keys] if keys else [m for m in cfg["models"] if m["provider"] != "mock"]
    ok = [m for m in ms if available(m)]
    for m in ms:
        if m not in ok:
            print(f"SKIP {m['key']}: API key env var not set")
    return ok


def make_prompt(task, r, cfg):
    if task == "kb":
        return build_prompt(r, cfg["prompt"]["include_city"])
    if task == "kb_masked":
        return build_masked_prompt(r, cfg["prompt"]["include_city"])
    if task == "kb_forced":
        return build_forced_prompt(r, cfg["prompt"]["include_city"])
    return build_bias_prompt(r, task.split(":")[1], cfg["prompt"]["include_city"])


def check_tasks(tasks):
    for t in tasks:
        assert t in ("kb", "kb_forced", "kb_masked") or (t.startswith("bias:") and t.split(":")[1] in BIAS_ARMS), f"unknown task {t}"


def estimate(cfg, sample, keys, tasks=None, repeats=None):
    n = len(pd.read_parquet(resolve(sample)))
    ms = select_models(cfg, keys)
    t = tasks or DEFAULT_TASKS
    check_tasks(t)
    k = repeats or cfg.get("repeats", 1)
    print(f"{n} schools x {len(ms)} models x {len(t)} tasks x {k} repeats = {n * len(ms) * len(t) * k} calls "
          f"(~350 in / ~250 out tokens each), plus {n * len(ms) * k} judge calls")


def run(cfg, sample, run_dir, keys, tasks=None, repeats=None):
    s = pd.read_parquet(resolve(sample))
    out = resolve(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    f = out / "responses.jsonl"
    s.to_parquet(out / "sample.parquet")   # analysis restricts to this sample
    tasks = tasks or DEFAULT_TASKS
    check_tasks(tasks)
    reps = repeats or cfg.get("repeats", 1)
    done = {(r["model"], r["nces_id"], r.get("task", "facts"), r.get("rep", 0)) for r in read_jsonl(f) if not r.get("error")}
    for m in select_models(cfg, keys):
        jobs = [(m, r, t, k) for k in range(reps) for t in tasks for r in s.to_dict("records")
                if (m["key"], r["nces_id"], t, k) not in done]
        print(f"{m['key']}: {len(jobs)} calls ({', '.join(tasks)}; {reps} repeat(s))")

        def work(job):
            m, r, t, k = job
            prompt = make_prompt(t, r, cfg)
            try:
                res = complete(m, prompt, cfg["max_tokens_default"])
                return {"model": m["key"], "nces_id": r["nces_id"], "task": t, "rep": k, "prompt": prompt, **res, "ts": time.time()}
            except Exception as e:  # keep going; failed items are retried on the next run
                return {"model": m["key"], "nces_id": r["nces_id"], "task": t, "rep": k, "error": str(e)[:300]}

        with ThreadPoolExecutor(cfg["concurrency"]) as ex:
            for fu in tqdm(as_completed([ex.submit(work, j) for j in jobs]), total=len(jobs)):
                append_jsonl(f, fu.result())
    recs = read_jsonl(f)
    print(f"done. errors={sum(1 for r in recs if r.get('error'))}  "
          f"responses showing tool/search traces={sum(1 for r in recs if r.get('tool_trace'))} (must be 0)")


CANARY = ("Without using any tools: what was the top headline on the BBC News homepage this morning, "
          "and what is the current temperature in Chicago? If you cannot know, say so.")


def check_tools(cfg, keys):
    """Pilot step 1: confirm calls carry no tools and the model admits it cannot know live information."""
    for m in select_models(cfg, keys):
        r = complete(m, CANARY, cfg["max_tokens_default"])
        print(f"\n=== {m['key']}  tool_trace={r['tool_trace']}\n{r['text'][:500]}")
