"""Web visibility of each school = how often its exact name occurs in large web-text corpora (infini-gram mini: exact phrase counts).
Indexes: Common Crawl dump 2025-05, DCLM-baseline (filtered Common Crawl), The Pile (~2020). Read-only public API.
CAUTION: counts are of the NAME STRING (same-named schools and Wikipedia mirrors are included) and the CC dump is from 2025, after the models' cutoffs."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
from tqdm import tqdm

from .common import resolve

API = "https://api.infini-gram-mini.io/"
INDEXES = {"cc2025": "v2_cc-2025-05", "dclm": "v2_dclm_all", "pile": "v2_piletrain"}


def count(index, query, retries=5):
    for i in range(retries):
        try:
            r = requests.post(API, json={"index": index, "query_type": "count", "query": query}, timeout=90)
            j = r.json()
            if "count" in j:
                return int(j["count"])
        except Exception:
            pass
        time.sleep(2 + 2 * i)
    return None


def query_counts(sample_path, out_path, workers=4):
    s = pd.read_parquet(resolve(sample_path))[["nces_id", "school_name", "city", "state", "from_wikipedia"]].drop_duplicates("nces_id")
    out = resolve(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    have = pd.read_parquet(out) if out.exists() else pd.DataFrame(columns=["nces_id"] + list(INDEXES))
    done = set(have.dropna().nces_id)
    todo = [r for r in s.to_dict("records") if r["nces_id"] not in done]

    def work(r):
        return {"nces_id": r["nces_id"], **{k: count(ix, r["school_name"]) for k, ix in INDEXES.items()}}
    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for fu in tqdm(as_completed([ex.submit(work, r) for r in todo]), total=len(todo), desc="visibility counts"):
            rows.append(fu.result())
    res = pd.concat([have[have.nces_id.isin(done)], pd.DataFrame(rows)], ignore_index=True)
    res.to_parquet(out)
    print(f"{len(res)} schools; failed lookups: {int(res[list(INDEXES)].isna().sum().sum())}")
    return res


def report(cfg, sample_path, counts_path, run_dir):
    """Does visibility differ by wiki status, and does it explain the models' willingness / ability to answer?"""
    import statsmodels.formula.api as smf
    from scipy import stats
    from .common import load_responses
    from .score import EASY_ITEMS, HARD_ITEMS, score_kb_all
    frame = pd.read_parquet(resolve(cfg["paths"]["frame"]))
    CNT = pd.read_parquet(resolve(counts_path))
    for k in INDEXES:
        CNT[f"log_{k}"] = np.log1p(CNT[k].astype(float))
    ids = set(pd.read_parquet(resolve(sample_path)).nces_id)
    sc = score_kb_all(load_responses(resolve(run_dir), "kb", ids), frame)
    rows = []
    for (m, nid), g in sc.groupby(["model", "nces_id"]):
        o = pd.concat([g[f"o_{i}"] for i in HARD_ITEMS]); o = o[o != "NA"]
        rows.append({"model": m, "nces_id": nid, "hard_abstain": (o == "abstain").mean(), "hard_acc": (o == "correct").mean()})
    M = pd.DataFrame(rows).merge(CNT, on="nces_id").merge(frame[["nces_id", "from_wikipedia", "sector", "log_enroll", "log_name_freq", "name_freq_state"]], on="nces_id")
    print(f"schools analysed: {M.nces_id.nunique()} (wiki: {int(M.drop_duplicates('nces_id').from_wikipedia.sum())})\n")
    U = M.drop_duplicates("nces_id")
    print("Name occurrences in each corpus (median count; share of schools with zero hits), by wiki status:")
    t = pd.DataFrame({k: {"median_wiki": U[U.from_wikipedia == 1][k].median(), "median_no_wiki": U[U.from_wikipedia == 0][k].median(),
                          "zero_wiki": (U[U.from_wikipedia == 1][k] == 0).mean(), "zero_no_wiki": (U[U.from_wikipedia == 0][k] == 0).mean(),
                          "mann_whitney_p": stats.mannwhitneyu(U[U.from_wikipedia == 1][k].dropna(), U[U.from_wikipedia == 0][k].dropna()).pvalue} for k in INDEXES}).T
    print(t.round(3).to_string())
    print("\nSpearman: log name count vs the model's hard-item ABSTAIN rate / ACCURACY (free-form), per model:")
    for m, g in M.groupby("model"):
        for k in INDEXES:
            a = stats.spearmanr(g[f"log_{k}"], g.hard_abstain, nan_policy="omit")[0]
            b = stats.spearmanr(g[f"log_{k}"], g.hard_acc, nan_policy="omit")[0]
            print(f"  {m:8} {k:7} rho(abstain)={a:+.2f}  rho(accuracy)={b:+.2f}")
    print("\nDoes visibility explain the wiki gap? OLS (HC3) on hard-item abstain rate, one row per (model, school):")
    for k in INDEXES:
        d = M.dropna(subset=[f"log_{k}", "log_enroll", "log_name_freq"])
        base = smf.ols("hard_abstain ~ from_wikipedia + C(model) + log_enroll + C(sector) + log_name_freq", d).fit(cov_type="cluster", cov_kwds={"groups": d.nces_id})
        adj = smf.ols(f"hard_abstain ~ from_wikipedia + log_{k} + C(model) + log_enroll + C(sector) + log_name_freq", d).fit(cov_type="cluster", cov_kwds={"groups": d.nces_id})
        print(f"  {k:7} wiki coef without count: {base.params['from_wikipedia']:+.3f} (p={base.pvalues['from_wikipedia']:.3f}) | "
              f"with log count: wiki {adj.params['from_wikipedia']:+.3f} (p={adj.pvalues['from_wikipedia']:.3f}), count {adj.params[f'log_{k}']:+.3f} (p={adj.pvalues[f'log_{k}']:.3f})")
