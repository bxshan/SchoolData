"""Dose-response INSIDE the wiki group: does model knowledge rise with how prominent the Wikipedia page is?
Uses only local SchoolData files (pageviews_60d, article length, founded year, website). No API calls.
A gradient is stronger evidence for an exposure mechanism than the binary wiki flag, but still correlational."""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from .baseline import baseline_long
from .common import load_responses, read_jsonl, resolve
from .score import EASY_ITEMS, HARD_ITEMS, score_kb_all


def load_prominence(cfg):
    p = cfg["paths"]
    m = pd.read_csv(resolve(p["wiki_matches"]), dtype=str)[["wiki_pageid", "nces_school_id"]].drop_duplicates("nces_school_id")
    e = pd.read_csv(resolve(p["wiki_enriched"]), dtype=str)[["pageid", "pageviews_60d", "founded", "website", "lead"]]
    a = pd.DataFrame([{"pageid": str(r["pageid"]), "article_chars": float(r.get("chars") or 0)} for r in read_jsonl(resolve(p["wiki_articles"]))])
    d = m.merge(e, left_on="wiki_pageid", right_on="pageid", how="left").merge(a, on="pageid", how="left")
    d["pageviews"] = pd.to_numeric(d.pageviews_60d, errors="coerce")
    d["log_pageviews"] = np.log1p(d.pageviews)
    d["log_article_chars"] = np.log(d.article_chars.where(d.article_chars > 0))
    yr = pd.to_numeric(d.founded.str.extract(r"(\d{4})")[0], errors="coerce")
    d["school_age"] = (2026 - yr).where((yr > 1600) & (yr <= 2026))
    d["has_website"] = d.website.notna() & (d.website.str.len() > 3)
    return d.rename(columns={"nces_school_id": "nces_id"})[["nces_id", "pageviews", "log_pageviews", "log_article_chars", "school_age", "has_website"]]


def per_school(cfg, run_dirs, frame):
    rows = []
    for rd in run_dirs:
        out = resolve(rd)
        ids = set(pd.read_parquet(out / "sample.parquet").nces_id)
        sc = score_kb_all(load_responses(out, "kb", ids), frame)
        rows.append(sc)
    sc = pd.concat(rows)
    B = baseline_long(frame[frame.nces_id.isin(sc.nces_id)])
    res = []
    for (model, nid), g in sc.groupby(["model", "nces_id"]):
        r = {"model": model, "nces_id": nid}
        for lab, items in (("easy", EASY_ITEMS), ("hard", HARD_ITEMS)):
            vals, above, ab, wr = [], [], [], []
            for it in items:
                o = g[f"o_{it}"].iloc[0]
                if o == "NA":
                    continue
                b = B[(B.nces_id == nid) & (B.item == it)].base_ok
                c = float(o == "correct")
                vals.append(c); ab.append(float(o == "abstain")); wr.append(float(o == "wrong"))
                if len(b):
                    above.append(c - float(b.iloc[0]))
            r.update({f"{lab}_acc": np.mean(vals) if vals else np.nan, f"{lab}_above_name": np.mean(above) if above else np.nan,
                      f"{lab}_abstain": np.mean(ab) if ab else np.nan, f"{lab}_wrong": np.mean(wr) if wr else np.nan})
        res.append(r)
    return pd.DataFrame(res).groupby("nces_id", as_index=False).mean(numeric_only=True)   # average over models and duplicate runs


def report(cfg, run_dirs):
    frame = pd.read_parquet(resolve(cfg["paths"]["frame"]))
    P = load_prominence(cfg)
    S = per_school(cfg, run_dirs, frame)
    cov = frame[["nces_id", "from_wikipedia", "sector", "level", "log_enroll", "locale3"]]
    D = S.merge(cov, on="nces_id").merge(P, on="nces_id", how="left")
    W = D[(D.from_wikipedia == 1) & D.log_pageviews.notna()].copy()
    print(f"Wiki-group dose-response: {len(W)} wiki schools with pageview data (pooled over runs {run_dirs}).")
    print(f"Pageviews (60 days): median {W.pageviews.median():,.0f}, 10th pct {W.pageviews.quantile(.1):,.0f}, 90th pct {W.pageviews.quantile(.9):,.0f}\n")
    W["tercile"] = pd.qcut(W.log_pageviews, 3, labels=["low views", "mid views", "high views"])
    cols = ["easy_acc", "hard_acc", "hard_above_name", "hard_abstain", "hard_wrong"]
    print("Mean outcome by page-view tercile:\n" + W.groupby("tercile", observed=True)[cols + ["log_enroll"]].mean().round(3).to_string() + "\n")
    print("Spearman rho (n=%d):" % len(W))
    for prox in ("log_pageviews", "log_article_chars"):
        for y in cols:
            ok = W[[prox, y]].dropna()
            rho, p = stats.spearmanr(ok[prox], ok[y])
            print(f"  {y:16} vs {prox:18} rho={rho:+.2f} p={p:.3f} (n={len(ok)})")
    print("\nOLS (HC3 SEs), controlling for enrollment, sector and level; coefficient per +1 log-pageview unit (x2.7 views):")
    for y in ("hard_acc", "hard_above_name", "hard_abstain", "easy_acc"):
        d = W.dropna(subset=[y, "log_pageviews", "log_enroll", "level", "sector"])
        r = smf.ols(f"{y} ~ log_pageviews + log_enroll + C(sector) + C(level)", d).fit(cov_type="HC3")
        lo, hi = r.conf_int().loc["log_pageviews"]
        print(f"  {y:16} coef={r.params['log_pageviews']:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  p={r.pvalues['log_pageviews']:.3f}  (n={int(r.nobs)})")
    ag = W.dropna(subset=["school_age", "hard_acc"])
    if len(ag) > 15:
        rho, p = stats.spearmanr(ag.school_age, ag.hard_acc)
        print(f"\nSchool age (from wiki 'founded', wiki schools only): hard_acc vs age rho={rho:+.2f} p={p:.3f} (n={len(ag)})")
    print("\nReading: a positive gradient (more page views -> more correct / fewer abstentions) supports 'prominence/exposure'"
          " rather than a flag effect. A flat gradient suggests the wiki flag marks something else or a threshold.")
