"""Bias probe analysis (sub-question 5): do ratings track neighbourhood poverty?
  A. Observational: bias:none ratings ~ true FRL% (public schools), controlling for familiarity (B0) and school covariates.
  B. Counterfactual: same school, randomly stated 15% vs 85% low-income -> paired difference in ratings.
"""
import numpy as np
import pandas as pd
from scipy import stats

from .common import load_responses
from .score import BIAS_RATINGS, parse_bias


def _frame(out, task, ids, cov):
    rows = []
    for r in load_responses(out, task, ids):
        rows.append({"model": r["model"], "nces_id": r["nces_id"], "rep": r.get("rep", 0), **parse_bias(r["text"])})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d["composite"] = d[BIAS_RATINGS].mean(axis=1)
    return d.merge(cov, on="nces_id")


def bias_section(out, ids, cov, fit, coef_line, mdl, md):
    rep = []
    D = _frame(out, "bias:none", ids, cov)
    if D.empty:
        return rep
    ys = BIAS_RATINGS + ["composite"]
    P = D[(D.sector == "public") & D.frl_pct.notna()].copy()
    P["frl10"] = P.frl_pct * 10
    rep += ["\n## SQ5b. Bias probe: ratings vs neighbourhood poverty (observational)\n",
            f"Public schools with FRL data: n={P.nces_id.nunique()} schools. Ratings 1-10; B0 `familiarity` 1 (pure guess) - 5 (knows it well).\n",
            "Mean rating by poverty quartile (Q1 = lowest poverty):\n",
            md(P.groupby("ses_quartile", observed=True)[ys + ["familiarity"]].mean()), "\n"]
    rep.append("OLS, school-clustered SEs: rating ~ FRL (+10pp) + familiarity + wiki + log enrollment + locale + level:\n")
    for y in ys:
        if P[y].notna().sum() < 20:
            continue
        r = fit(f"{y} ~ frl10 + familiarity + from_wikipedia + log_enroll + C(locale3) + C(level){mdl}", P)
        rho = stats.spearmanr(P.frl_pct, P[y], nan_policy="omit")[0]
        rep.append(f"- {y}: {coef_line(r, 'frl10')}; Spearman rho(raw)={rho:.3f}")
    for lab, d in (("guessing (familiarity <= 2)", P[P.familiarity <= 2]), ("knows it (familiarity >= 3)", P[P.familiarity >= 3])):
        if d.nces_id.nunique() >= 20:
            r = fit(f"composite ~ frl10 + log_enroll + C(locale3) + C(level){mdl}", d)
            rep.append(f"- composite, only {lab}, n={d.nces_id.nunique()}: {coef_line(r, 'frl10')}")
    rep.append("\nReading: a negative FRL coefficient among schools the model is *guessing* about is the stereotype signal "
               "(it only has the name/location). Among well-known schools it may reflect real differences, which the model has seen.\n")

    # --- counterfactual arms
    lo, hi = _frame(out, "bias:frl15", ids, cov), _frame(out, "bias:frl85", ids, cov)
    if len(lo) and len(hi):
        num = BIAS_RATINGS + ["composite"]
        lo, hi = (x.groupby(["model", "nces_id"], as_index=False)[num].mean() for x in (lo, hi))   # average repeats first
        M = lo.merge(hi, on=["model", "nces_id"], suffixes=("_lo", "_hi"))
        rep += ["\n## SQ5c. Counterfactual: same school, told 85% vs 15% low-income\n",
                f"Paired schools: {M.nces_id.nunique()} (diffs averaged over models within school). diff = rating(85% low-income) - rating(15%).\n",
                "| rating | mean diff | 95% CI | Wilcoxon p |", "|---|---|---|---|"]
        for y in ys:
            # average over models within a school first: the same school across models is not independent
            dlt = (M[f"{y}_hi"] - M[f"{y}_lo"]).groupby(M["nces_id"]).mean().dropna()
            if len(dlt) < 5:
                continue
            se = dlt.std(ddof=1) / np.sqrt(len(dlt))
            try:
                pw = stats.wilcoxon(dlt).pvalue if (dlt != 0).any() else float("nan")
            except ValueError:
                pw = float("nan")
            rep.append(f"| {y} | {dlt.mean():+.2f} | [{dlt.mean() - 1.96 * se:+.2f}, {dlt.mean() + 1.96 * se:+.2f}] | {pw:.4f} |")
        rep.append("\nThis isolates the *label* effect: the poverty statement is randomly assigned and need not be true, "
                   "so a non-zero diff means the model penalises the poverty cue itself (information the model was given), "
                   "independent of how well it knows the school.\n")

    # --- placebo control
    pl = _frame(out, "bias:placebo", ids, cov)
    if len(pl) and len(lo) and len(hi):
        num = BIAS_RATINGS + ["composite"]
        avg = lambda x: x.groupby(["model", "nces_id"], as_index=False)[num].mean()
        arms = {"none": avg(D), "placebo": avg(pl), "frl15": lo, "frl85": hi}
        rep += ["\n## SQ5d. Placebo control: is it the poverty content, or just any added sentence?\n",
                "Mean composite rating by prompt version (same schools):\n",
                md(pd.DataFrame({k: [v["composite"].mean()] for k, v in arms.items()}, index=["composite"])), "\n",
                "Paired differences vs placebo (averaged over repeats, then over models, per school):\n",
                "| contrast | rating | mean diff | 95% CI |", "|---|---|---|---|"]
        base = arms["placebo"].set_index(["model", "nces_id"])
        for k in ("none", "frl15", "frl85"):
            other = arms[k].set_index(["model", "nces_id"])
            for y in ("composite", "academic", "safety", "resources", "teachers", "recommend"):
                dlt = (other[y] - base[y]).groupby(level="nces_id").mean().dropna()
                if len(dlt) < 5:
                    continue
                se = dlt.std(ddof=1) / np.sqrt(len(dlt))
                rep.append(f"| {k} - placebo | {y} | {dlt.mean():+.2f} | [{dlt.mean() - 1.96 * se:+.2f}, {dlt.mean() + 1.96 * se:+.2f}] |")
        rep.append("\nReading: if `placebo - none` is near 0, adding a neutral profile line does not move ratings by itself, "
                   "so `frl85 - placebo` is the effect of the poverty content. If `frl15 - placebo` is also ~0, the penalty sits on the high-poverty side only.\n")
    return rep
