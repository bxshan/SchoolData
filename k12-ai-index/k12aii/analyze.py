"""Analysis for sub-questions 1-6. Writes report.md + figures to <run_dir>/analysis/."""
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from .common import ans_hash, judgments_path, load_responses, read_jsonl, resolve
from .baseline import baseline_long
from .bias import bias_section
from .score import EASY_ITEMS, HARD_ITEMS, ITEMS_KB, score_kb_all

warnings.filterwarnings("ignore")
ITEMS = list(ITEMS_KB)   # all 7 items; easy / hard are reported separately


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def md(df, floatfmt=3):
    df = df.reset_index()
    cols = [str(c) for c in df.columns]
    f = lambda v: f"{v:.{floatfmt}f}" if isinstance(v, (float, np.floating)) else str(v)
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(f(v) for v in r) + " |" for r in df.values])


def long_items(sc):
    L = sc.melt(id_vars=["model", "nces_id", "rep"], value_vars=[f"o_{i}" for i in ITEMS], var_name="item", value_name="outcome")
    L["item"] = L["item"].str[2:]
    L = L[L.outcome != "NA"]
    L["correct"] = (L.outcome == "correct").astype(int)
    L["wrong"] = (L.outcome == "wrong").astype(int)
    L["abstain"] = (L.outcome == "abstain").astype(int)
    return L


def gap_table(L, by="model"):
    rows = []
    for key, g in L.groupby(by):
        r = {by: key}
        for w in (0, 1):
            x = g[g.from_wikipedia == w]
            lo, hi = wilson(x.correct.sum(), len(x))
            r.update({f"acc_w{w}": x.correct.mean(), f"wrong_w{w}": x.wrong.mean(), f"abst_w{w}": x.abstain.mean()})
        r["acc_gap(wiki-no)"] = r["acc_w1"] - r["acc_w0"]
        r["wrong_gap(no-wiki)"] = r["wrong_w0"] - r["wrong_w1"]
        rows.append(r)
    return pd.DataFrame(rows).set_index(by)


class _PointEstimate:
    """Result stand-in when standard errors cannot be computed (prints nan CI / p)."""
    def __init__(self, params):
        self.params = params
        self.pvalues = pd.Series(np.nan, index=params.index)

    def conf_int(self):
        return pd.DataFrame(np.nan, index=self.params.index, columns=[0, 1])


def cluster_fit(formula, data, family=None):
    """GLM/OLS with school-clustered SEs; drops only rows missing a variable USED in the formula."""
    import patsy
    import statsmodels.api as sm
    y, X = patsy.dmatrices(formula, data, NA_action="drop", return_type="dataframe")
    groups = data.loc[y.index, "nces_id"]
    model = sm.GLM(y, X, family=family) if family else sm.OLS(y, X)
    try:
        return model.fit(cov_type="cluster", cov_kwds={"groups": groups})
    except np.linalg.LinAlgError:
        # (quasi-)complete separation or a collinear design: keep a point estimate, but no inference
        r = model.fit_regularized(alpha=1e-3, L1_wt=0.0)
        return _PointEstimate(pd.Series(np.asarray(r.params), index=X.columns))


def coef_line(res, term):
    return f"{term}: coef={res.params[term]:.3f}, 95% CI [{res.conf_int().loc[term, 0]:.3f}, {res.conf_int().loc[term, 1]:.3f}], p={res.pvalues[term]:.4f}"


def boot_gap(L, value, n=4000, seed=0):
    """Wiki - no-wiki gap in a per-school mean of `value`, with a percentile bootstrap CI resampling SCHOOLS within each group.
    Works when logit fails (perfect separation at n=50 per group)."""
    s = L.assign(_v=value).groupby(["nces_id", "from_wikipedia"])["_v"].mean().reset_index()
    a, b = s[s.from_wikipedia == 1]._v.values, s[s.from_wikipedia == 0]._v.values
    rng = np.random.default_rng(seed)
    d = np.array([rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n)])
    return a.mean() - b.mean(), np.percentile(d, 2.5), np.percentile(d, 97.5)


def paired_boot(L, value, pairs, n=4000, seed=1):
    """Mean within-pair difference (wiki - matched no-wiki), bootstrap over PAIRS."""
    s = L.assign(_v=value).groupby(["nces_id", "from_wikipedia"])["_v"].mean().reset_index()
    s["pair"] = s.nces_id.map(pairs)
    w = s[s.from_wikipedia == 1].set_index("pair")["_v"]
    c = s[s.from_wikipedia == 0].set_index("pair")["_v"]
    d = (w - c).dropna().values
    if len(d) < 5:
        return None
    rng = np.random.default_rng(seed)
    bs = np.array([rng.choice(d, len(d)).mean() for _ in range(n)])
    return d.mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5), len(d)


def boot_lines(L, pairs=None):
    g = boot_gap(L, L.correct)
    out = [f"School-bootstrap (4000 draws) wiki - no-wiki gap in accuracy: {g[0]:+.3f}, 95% CI [{g[1]:+.3f}, {g[2]:+.3f}]"]
    if L.base_ok.notna().all():
        g = boot_gap(L, L.correct - L.base_ok)
        out.append(f"... in accuracy ABOVE the name-only baseline (knowledge beyond the name): {g[0]:+.3f}, 95% CI [{g[1]:+.3f}, {g[2]:+.3f}]")
    if pairs is not None:
        g = paired_boot(L, L.correct, pairs)
        if g:
            out.append(f"PAIRED (enrollment-matched pairs, n={g[3]}) wiki - no-wiki accuracy: {g[0]:+.3f}, 95% CI [{g[1]:+.3f}, {g[2]:+.3f}]")
            if L.base_ok.notna().all():
                g = paired_boot(L, L.correct - L.base_ok, pairs)
                out.append(f"PAIRED, accuracy ABOVE the name-only baseline: {g[0]:+.3f}, 95% CI [{g[1]:+.3f}, {g[2]:+.3f}]")
    return "\n".join("    " + x for x in out) + "\n"


def baseline_blocks(L, ctrl, mdl, pairs=None):
    """Model accuracy vs the name-only baseline, and the wiki effect after controlling for name-guessability."""
    import statsmodels.api as sm
    U = L.drop_duplicates(["model", "nces_id", "item"])
    t = U.groupby(["item", "from_wikipedia"]).agg(model_acc=("correct", "mean"), name_only_acc=("base_ok", "mean")).unstack()
    t.columns = [f"{a}_w{b}" for a, b in t.columns]
    for w in (0, 1):
        t[f"above_name_w{w}"] = t[f"model_acc_w{w}"] - t[f"name_only_acc_w{w}"]
    out = ["\n### Is it knowledge, or just guessing from the school name?\n",
           "`name_only_acc` = accuracy of a keyword rule that sees only the school name/city (no model). "
           "`above_name` = model accuracy minus that baseline: the share attributable to knowing the school.\n", md(t), "\n"]
    if L.base_ok.notna().all():
        r = cluster_fit(f"correct ~ from_wikipedia + base_ok + {ctrl} + C(item){mdl}", L, sm.families.Binomial())
        out.append("Pooled logit, additionally controlling for whether the name alone gives the answer away (`base_ok`):\n\n    "
                   + coef_line(r, "from_wikipedia") + "\n")
    out += ["\n", boot_lines(L, pairs)]
    return out


def hard_section(L2, ctrl, mdl, pairs=None):
    """Hard items (A5 grade span, A6 enrollment band, A7 charter): not guessable from a name."""
    import statsmodels.api as sm
    if L2.empty:
        return []
    res = ["\n## SQ1-hard. School-specific facts (A5 exact grade span, A6 enrollment band, A7 charter)\n",
           f"Rows: {len(L2)}. Unparsed answers: {(L2.outcome == 'unparsed').sum()}. "
           "Note: UNKNOWN counts as not-correct, so items that models mostly decline (check abst_*) understate knowledge.\n",
           md(gap_table(L2)), "\n", md(gap_table(L2, "item")), "\n"]
    res += baseline_blocks(L2, ctrl, mdl, pairs)
    r = cluster_fit(f"correct ~ from_wikipedia + {ctrl} + C(item){mdl}", L2, sm.families.Binomial())
    res.append("Hard items, pooled logit, school-clustered:\n\n    " + coef_line(r, "from_wikipedia") + "\n")
    r = cluster_fit(f"wrong ~ from_wikipedia + {ctrl} + C(item){mdl}", L2, sm.families.Binomial())
    res.append("Wrong-answer (confident error) logit:\n\n    " + coef_line(r, "from_wikipedia") + "\n")
    return res


def balance_section(samp, frame):
    """Covariate balance of the analysed sample: |SMD| > 0.25 means the groups differ clearly on that variable."""
    if samp is None:
        return []
    d = samp[["nces_id", "from_wikipedia"]].merge(frame[["nces_id", "log_enroll", "log_name_freq", "frl_pct"]], on="nces_id")
    rows = []
    for c, lab in (("log_enroll", "log enrollment"), ("log_name_freq", "log name frequency in state"), ("frl_pct", "free/reduced lunch share (public)")):
        a, b = d[d.from_wikipedia == 1][c].dropna(), d[d.from_wikipedia == 0][c].dropna()
        if len(a) > 5 and len(b) > 5:
            rows.append({"variable": lab, "wiki_mean": a.mean(), "no_wiki_mean": b.mean(),
                         "SMD": (a.mean() - b.mean()) / np.sqrt((a.var() + b.var()) / 2)})
    out = ["\n## Sample balance (wiki vs no-wiki)\n", md(pd.DataFrame(rows).set_index("variable")), "\n"]
    if "pair_id" in samp:
        out.append(f"Design: {samp.pair_id.nunique()} enrollment-matched pairs (max |log ratio| = {samp.match_gap_log.max():.2f}).\n")
    else:
        out.append("Design: NOT pair-matched on enrollment; the regression's linear enrollment control carries the adjustment.\n")
    return out


def forced_section(out, ids, frame, ctrl, mdl, pairs, L_free):
    """kb_forced (no UNKNOWN allowed): latent knowledge. Compared with the free-form answers to separate 'knows' from 'dares to answer'."""
    import statsmodels.api as sm
    resp = load_responses(out, "kb_forced", ids)
    if not resp:
        return []
    sc = score_kb_all(resp, frame)
    cov = frame[["nces_id", "from_wikipedia", "sector", "locale3", "level", "log_enroll", "log_name_freq"]]
    F = long_items(sc.merge(cov, on="nces_id")).merge(cov, on="nces_id")
    F = F.merge(baseline_long(frame[frame.nces_id.isin(F.nces_id)]), on=["nces_id", "item"], how="left")
    res = ["\n## SQ1-forced. Forced answers (no UNKNOWN allowed): latent knowledge\n",
           f"Rows: {len(F)}. Abstentions that slipped through: {int((F.outcome == 'abstain').sum())}; unparsed: {int((F.outcome == 'unparsed').sum())}. "
           "With guessing forced, accuracy is directly comparable to the name-only baseline.\n"]
    for lab, items in (("HARD (A5-A7)", HARD_ITEMS), ("EASY (A1-A4)", EASY_ITEMS)):
        G = F[F.item.isin(items)]
        res += [f"\n### {lab}, forced\n", md(gap_table(G)), "\n"]
        res += baseline_blocks(G, ctrl, mdl, pairs)
    # free vs forced, per model and wiki status, on hard items
    free = L_free.groupby(["model", "from_wikipedia"]).agg(free_acc=("correct", "mean"), free_abstain=("abstain", "mean")).reset_index()
    frc = F[F.item.isin(HARD_ITEMS)].groupby(["model", "from_wikipedia"]).agg(forced_acc=("correct", "mean")).reset_index()
    t = free.merge(frc, on=["model", "from_wikipedia"])
    t["dares_gap(forced-free)"] = t.forced_acc - t.free_acc
    res += ["\n### Hard items: free-form vs forced, by model and wiki status\n",
            "`dares_gap` = how much accuracy rises when the model is forced to answer = knowledge the model had but would not commit to.\n",
            md(t.set_index(["model", "from_wikipedia"])), "\n"]
    return res


def masked_section(out, ids, frame, pairs):
    """Identity gain = accuracy with the real name+city minus accuracy when the identifying name and city are hidden.
    This isolates knowledge of the specific school (district excluded: it needs the city)."""
    resp_m, resp_f = load_responses(out, "kb_masked", ids), load_responses(out, "kb_forced", ids)
    if not resp_m or not resp_f:
        return []
    items = [i for i in ITEMS if i != "district"]
    m = score_kb_all(resp_m, frame)
    f = score_kb_all(resp_f, frame)
    both = set(m.model) & set(f.model)        # only models that have BOTH conditions
    m, f = m[m.model.isin(both)], f[f.model.isin(both)]
    rows = []
    for tag, d in (("masked", m), ("real", f)):
        for it in items:
            x = d[["model", "nces_id", f"o_{it}"]].rename(columns={f"o_{it}": "o"})
            x = x[x.o != "NA"].assign(item=it, tag=tag, ok=lambda t: (t.o == "correct").astype(int))
            rows.append(x)
    X = pd.concat(rows).merge(frame[["nces_id", "from_wikipedia"]], on="nces_id")
    t = X.groupby(["model", "item", "from_wikipedia", "tag"]).ok.mean().unstack("tag")
    t["identity_gain"] = t["real"] - t["masked"]
    res = ["\n## SQ1-masked. How much is knowledge of the specific school? (real name+city vs hidden name, no city)\n",
           "Both conditions force an answer. `masked` = guessable from name structure + state; `real` = with the true name and city; "
           "`identity_gain` = real - masked. District item excluded (it needs the city).\n",
           md(t.round(3)), "\n"]
    P = X.pivot_table(index=["model", "nces_id", "from_wikipedia"], columns="tag", values="ok", aggfunc="mean").reset_index()
    P["gain"] = P["real"] - P["masked"]
    res += ["Per-school mean gain over items (wiki vs no-wiki), by model:\n", "| model | gain no-wiki | gain wiki | wiki - no-wiki (95% CI, bootstrap over schools/pairs) |", "|---|---|---|---|"]
    rng = np.random.default_rng(3)
    for mod, g in P.groupby("model"):
        a, b = g[g.from_wikipedia == 1], g[g.from_wikipedia == 0]
        if pairs is not None:
            w = a.set_index(a.nces_id.map(pairs)).gain
            c = b.set_index(b.nces_id.map(pairs)).gain
            dd = (w - c).dropna().values
            bs = np.array([rng.choice(dd, len(dd)).mean() for _ in range(4000)])
            est, lo, hi = dd.mean(), *np.percentile(bs, [2.5, 97.5])
        else:
            est = a.gain.mean() - b.gain.mean()
            bs = np.array([rng.choice(a.gain.values, len(a)).mean() - rng.choice(b.gain.values, len(b)).mean() for _ in range(4000)])
            lo, hi = np.percentile(bs, [2.5, 97.5])
        res.append(f"| {mod} | {b.gain.mean():+.3f} | {a.gain.mean():+.3f} | {est:+.3f} [{lo:+.3f}, {hi:+.3f}] |")
    res.append("\nReading: `gain wiki > gain no-wiki` means knowing the real identity helps more for wiki schools, i.e. a genuine school-specific knowledge gap, "
               "net of what the name structure gives away. Near-equal gains mean the models' knowledge of the two groups is similar once guessing is controlled.\n")
    return res


def stability_section(L, sc):
    """Run-to-run noise (only when there are repeats): outcomes cannot be pinned with temperature=0 on new models."""
    k = sc.groupby(["model", "nces_id"]).rep.nunique()
    if k.max() < 2:
        return []
    multi = L.groupby(["model", "nces_id", "item"]).outcome.agg(lambda s: s.nunique() == 1 if len(s) > 1 else np.nan)
    out = ["\n## Run-to-run stability\n", f"Repeats per (model, school): up to {int(k.max())}.\n",
           "Share of (school, item) whose objective outcome was identical across repeats:\n",
           md(multi.dropna().groupby(level=0).mean().to_frame("identical_outcome_share")), "\n"]
    return out


def analyze(cfg, run_dir, frame_path):
    import statsmodels.api as sm
    out = resolve(run_dir)
    fig_dir = out / "analysis"
    fig_dir.mkdir(exist_ok=True)
    frame = pd.read_parquet(resolve(frame_path))
    samp = pd.read_parquet(out / "sample.parquet") if (out / "sample.parquet").exists() else None
    ids = set(samp.nces_id) if samp is not None else None
    pairs = samp.set_index("nces_id").pair_id if (samp is not None and "pair_id" in samp) else None
    resp = load_responses(out, "kb", ids)
    sc = score_kb_all(resp, frame)
    jd = pd.DataFrame([j for j in read_jsonl(judgments_path(out, cfg)) if "halluc" in j and (ids is None or j["nces_id"] in ids)])
    if len(jd) and "rep" not in jd:
        jd["rep"] = 0
    elif len(jd):
        jd["rep"] = jd["rep"].fillna(0).astype(int)
    if len(jd):   # only judgments made for the CURRENT answer text (legacy judgments without a hash are ignored)
        sc["ans_hash"] = sc.d1.map(ans_hash)
        jd = jd.dropna(subset=["ans_hash"]) if "ans_hash" in jd else jd.iloc[0:0]
    meta = pd.DataFrame(cfg["models"])[["key", "family", "release", "cutoff"]].rename(columns={"key": "model"})
    cov = frame[["nces_id", "from_wikipedia", "sector", "locale3", "level", "level_group", "log_enroll", "log_name_freq", "frl_pct", "ses_quartile"]]
    sc = sc.merge(cov, on="nces_id").merge(meta, on="model", how="left")
    L = long_items(sc).merge(sc[["model", "nces_id", "rep", "from_wikipedia", "sector", "locale3", "level", "level_group", "log_enroll", "log_name_freq"]].drop_duplicates(["model", "nces_id", "rep"]), on=["model", "nces_id", "rep"])
    B = baseline_long(frame[frame.nces_id.isin(sc.nces_id)])
    L = L.merge(B, on=["nces_id", "item"], how="left")   # base_ok: would a name-only guess be right?
    L_hard = L[L.item.isin(HARD_ITEMS)].copy()
    L = L[L.item.isin(EASY_ITEMS)].copy()                   # main sections below = easy items
    rep = ["# K12-AII analysis report\n", f"Judge: {cfg['judge']['provider']}/{cfg['judge']['model']}\n", f"Schools: {sc.nces_id.nunique()}, models: {sc.model.nunique()}, responses: {len(sc)}, item-level rows: {len(L)}\n"]
    mdl = " + C(model)" if sc.model.nunique() > 1 else ""   # model FE only with >1 model
    ctrl = "C(sector) + C(locale3) + C(level) + log_enroll + log_name_freq"   # full 4-way level, not just high/other

    # SQ1: factual accuracy, wiki vs no-wiki
    rep += ["\n## SQ1. Factual accuracy: wiki vs no-wiki (easy items A1-A4 pooled over applicable items)\n", md(gap_table(L)), "\n"]
    pooled = cluster_fit(f"correct ~ from_wikipedia + {ctrl} + C(item){mdl}", L, sm.families.Binomial())
    rep.append("Pooled logit, school-clustered SEs, controls = sector, locale, level, log enrollment, item, model FE:\n\n    " + coef_line(pooled, "from_wikipedia") + f"  (odds ratio {np.exp(pooled.params['from_wikipedia']):.2f})\n")
    rep += baseline_blocks(L, ctrl, mdl, pairs)
    by_item = gap_table(L, "item")
    rep += ["\nBy item:\n", md(by_item), "\n"]

    rep += hard_section(L_hard, ctrl, mdl, pairs)
    rep += forced_section(out, ids, frame, ctrl, mdl, pairs, L_hard)
    rep += masked_section(out, ids, frame, pairs)

    # SQ2: hallucination / abstention
    rep += ["\n## SQ2. Wrong-vs-abstain behaviour\n",
            "`wrong_*` = confident wrong answer rate (objective hallucination), `abst_*` = said UNKNOWN. Compare: a model that does not know should abstain, not err.\n",
            md(gap_table(L)[[c for c in gap_table(L).columns if c.startswith(("wrong", "abst"))]]), "\n"]
    wr = cluster_fit(f"wrong ~ from_wikipedia + {ctrl} + C(item){mdl}", L, sm.families.Binomial())
    rep.append("Wrong-answer logit:\n\n    " + coef_line(wr, "from_wikipedia") + "\n")
    if len(jd):
        J = sc.merge(jd.drop_duplicates(["model", "nces_id", "rep", "ans_hash"]), on=["model", "nces_id", "rep", "ans_hash"])
        J["specific"] = (J.halluc == 2).astype(int)   # judge score 2 = makes concrete claims (NOT necessarily wrong)
        J["strict"] = (J.contradicted > 0).astype(int)
        J["n_spec"] = J.unverifiable_specific.fillna(0) + J.contradicted.fillna(0)
        tab = J.groupby(["model", "from_wikipedia"])[["strict", "specific", "d1_words", "n_spec"]].mean().unstack()
        rep += ["\nOpen-ended D1 (judge): **`strict` = hallucination indicator**: at least one claim contradicting NCES facts. `specific` = answer makes concrete claims the NCES facts cannot verify (a measure of DETAIL; correct details count, so it is higher where the model knows more). `n_spec` = such claims per answer, `d1_words` = length.\n", md(tab), "\n"]
        for y, lab in (("specific", "makes concrete claims"), ("strict", "contradicts NCES")):
            if J[y].sum() >= 3:   # skip degenerate outcomes
                h = cluster_fit(f"{y} ~ from_wikipedia + {ctrl}{mdl}", J, sm.families.Binomial())
                rep.append(f"D1 logit, {lab}:\n\n    " + coef_line(h, "from_wikipedia") + "\n")
            else:
                rep.append(f"D1 '{lab}': only {int(J[y].sum())} positive answers, too few to model.\n")
        rep.append("\nCaveat: NCES facts cannot verify founding years/programs/namesakes, so true fabrication of such details is NOT captured by `strict` (a lower bound). Verify the unverifiable claims against an external source (e.g. Wikipedia text for wiki schools, school websites for the rest) before calling them hallucinations. Judge false positives happen (check with calibrate-*).\n")

        # SQ5: bias vs SES (public, with FRL), school-clustered
        P = J[(J.sector == "public") & J.frl_pct.notna()].copy()
        P["frl10"] = P.frl_pct * 10   # per 10 percentage points
        rep += ["\n## SQ5. Description tone/detail vs poverty (FRL%, public schools)\n"]
        for w, lab in ((0, "no-wiki"), (1, "wiki"), (None, "all (wiki as control)")):
            d = P if w is None else P[P.from_wikipedia == w]
            if len(d) < 20:
                continue
            extra = " + from_wikipedia" if w is None else ""
            for y in ("sentiment", "d1_words", "n_spec"):
                r = cluster_fit(f"{y} ~ frl10 + log_enroll + C(locale3) + C(level){mdl}{extra}", d)
                rho = stats.spearmanr(d.frl_pct, d[y])[0]
                rep.append(f"- [{lab}] {y} vs FRL (+10pp): {coef_line(r, 'frl10')}; Spearman rho={rho:.3f} (n={len(d)})")
        rep.append(f"- stereotype flag rate: " + ", ".join(f"{q}: {v:.3f}" for q, v in P.groupby('ses_quartile', observed=True).stereotype.mean().items()))
        rep.append("\nCaveat: models know less about low-income schools, so shorter answers can reflect ignorance, not bias. Compare within the wiki group (similar knowledge) and read sentiment together with the abstention rate.\n")

    rep += bias_section(out, ids, frame[["nces_id", "from_wikipedia", "sector", "locale3", "level", "log_enroll", "frl_pct", "ses_quartile"]],
                        cluster_fit, coef_line, mdl, md)

    rep += stability_section(L, sc)
    rep += balance_section(samp, frame)

    # SQ3: models
    pm = L.groupby("model").apply(lambda g: pd.Series({"overall_acc": g.correct.mean()}))
    rep += ["\n## SQ3. Do models agree on the gap?\n", "Per-model gaps are in the SQ1 table. Interaction test (wiki x model):\n"]
    try:
        if sc.model.nunique() < 2:
            raise ValueError("needs >= 2 models")
        full = smf.logit(f"correct ~ from_wikipedia * C(model) + {ctrl} + C(item)", L.dropna()).fit(disp=0)
        red = smf.logit(f"correct ~ from_wikipedia + C(model) + {ctrl} + C(item)", L.dropna()).fit(disp=0)
        lr = 2 * (full.llf - red.llf)
        dfree = int(full.df_model - red.df_model)
        rep.append(f"    LR chi2={lr:.2f}, df={dfree}, p={stats.chi2.sf(lr, dfree):.4f}  (item-level; ignores clustering, indicative only)\n")
    except Exception as e:
        rep.append(f"    (failed: {e})\n")

    # SQ4: locale
    rep += ["\n## SQ4. Urban/suburban/rural beyond wiki status\n", md(L.groupby(["locale3", "from_wikipedia"]).correct.mean().unstack()), "\n"]
    lo = cluster_fit(f"correct ~ from_wikipedia * C(locale3, Treatment('urban')) + C(sector) + C(level) + log_enroll + C(item){mdl}", L, sm.families.Binomial())
    rep.append("Logit with wiki x locale interaction (reference = urban):\n\n" + "\n".join("    " + coef_line(lo, t) for t in lo.params.index if "locale3" in t) + "\n")

    # SQ6: version trend
    rep += ["\n## SQ6. Gap across model versions (same family)\n"]
    g = gap_table(L).join(meta.set_index("model")[["family", "release", "cutoff"]]).sort_values(["family", "release"])
    rep += [md(g[["family", "release", "cutoff", "acc_w0", "acc_w1", "acc_gap(wiki-no)", "wrong_w0"]]), "\n",
            "Caveat: schools founded after a model's knowledge cutoff cannot be known; check `cutoff` vs school open dates before reading a shrinking gap as progress.\n"]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    gg = gap_table(L)
    x = np.arange(len(gg))
    ax[0].bar(x - .2, gg.acc_w0, .4, label="no wiki")
    ax[0].bar(x + .2, gg.acc_w1, .4, label="wiki")
    ax[0].set_xticks(x, gg.index, rotation=30, ha="right")
    ax[0].set_ylabel("accuracy")
    ax[0].legend()
    ax[0].set_title("Accuracy by wiki status")
    for fam, d in g.groupby("family"):
        ax[1].plot(d.release, d["acc_gap(wiki-no)"], marker="o", label=fam)
    ax[1].set_title("Wiki accuracy gap by release")
    ax[1].legend()
    plt.setp(ax[1].get_xticklabels(), rotation=30)
    plt.tight_layout()
    plt.savefig(fig_dir / "accuracy_gap.png", dpi=150)
    (fig_dir / "report.md").write_text("\n".join(rep))
    print("\n".join(rep))
    print(f"\nwritten: {fig_dir / 'report.md'}")
