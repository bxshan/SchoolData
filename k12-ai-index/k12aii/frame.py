"""Build the school frame: HF dataset (wiki flag) joined to the NCES master (ground truth)."""
import glob
import re

import pandas as pd

from .common import resolve

LOCALE4 = {"1": "city", "2": "suburb", "3": "town", "4": "rural"}
LOCALE3 = {"city": "urban", "suburb": "suburban", "town": "rural", "rural": "rural"}
RELIG = {"1": "catholic", "2": "other_religious", "3": "none"}


def _grade(g):
    if g is None or pd.isna(g):
        return None
    g = str(g).strip()
    return {"PK": -1, "KG": 0}.get(g, int(g) if g.isdigit() else None)


GRADE_COLS = ["PSS_ENROLL_PK", "PSS_ENROLL_K"] + [f"PSS_ENROLL_{i}" for i in range(1, 13)]   # grade numbers -1, 0, 1..12


def _private_span(row):
    """PSS grade codes are opaque, so derive the span from grades that actually have enrollment."""
    gs = [g for g, c in zip(range(-1, 13), GRADE_COLS) if pd.to_numeric(row.get(c), errors="coerce") > 0]
    return (min(gs), max(gs)) if gs else (None, None)


def _level(lo, hi):
    """-> (level, accepted_alternative). 6-12 / 7-12 schools are 'combined' but named/called 'high' by everyone."""
    if lo is None or hi is None:
        return None, None
    if hi <= 6:
        return "elementary", None
    if lo >= 9:
        return "high", None
    if lo >= 5 and hi <= 8:
        return "middle", None
    if hi >= 12 and lo >= 6:
        return "combined", "high"
    return "combined", None


ABBREV = [(r"\bH\.? ?S\.?(?=\s|$)", "High School"), (r"\bM\.? ?S\.?(?=\s|$)", "Middle School"), (r"\bElem\.?(?=\s|$)", "Elementary"),
          (r"\bSr\.? High\b", "Senior High"), (r"\bJr\.? High\b", "Junior High"), (r"\bMid\.?(?=\s|$)", "Middle"),
          (r"\bSch\.?(?=\s|$)", "School"), (r"\bAcad\.?(?=\s|$)", "Academy")]
TERRITORIES = {"AS", "GU", "MP", "PR", "VI"}


def _clean_name(n):
    """Uniform display name for BOTH groups: NCES abbreviations are unevenly spread across wiki / non-wiki
    (e.g. 'Elem.' ~always non-wiki, 'H S' mostly wiki) and would otherwise confound recognition."""
    n = n.title().replace("'S", "'s") if n.isupper() else n
    for pat, rep in ABBREV:
        n = re.sub(pat, rep, n)
    n = re.sub(r"\b(High|Middle|Elementary|Intermediate|Primary)$", r"\1 School", n)
    return re.sub(r"\s+", " ", n).strip()


def build(cfg):
    hf = pd.concat(pd.read_parquet(f) for f in sorted(glob.glob(str(resolve(cfg["paths"]["hf_parquet_glob"])))))
    hf = hf[["nces_id", "name", "state", "sector", "from_wikipedia"]].rename(columns={"sector": "sector_hf"})
    m = pd.read_csv(resolve(cfg["paths"]["nces_master"]), dtype=str)
    m = m.rename(columns={"sector": "sector_nces"})
    df = hf.merge(m, left_on="nces_id", right_on="school_id", how="inner", suffixes=("", "_m"))
    assert (df.sector_hf == df.sector_nces).all(), "sector mismatch between HF and NCES master"
    df["sector"] = df.sector_hf

    # --- derived ground truth / covariates ---
    df["school_name"] = df["name"].map(_clean_name)
    df["city"] = df["city"].fillna("").str.title()
    code = df["Locale Code"].fillna(df["PSS_LOCALE"]).fillna("").str[:1]
    df["locale4"] = code.map(LOCALE4)
    df["locale3"] = df["locale4"].map(LOCALE3)
    df["enrollment"] = pd.to_numeric(df["total_students"], errors="coerce")
    df["log_enroll"] = df["enrollment"].where(df["enrollment"] > 0).map(lambda x: None if pd.isna(x) else __import__("math").log(x))
    pub = df.sector == "public"
    spans = [(_grade(a), _grade(b)) for a, b in zip(df["low_grade"], df["high_grade"])]
    pspans = [_private_span(r) for r in df[GRADE_COLS].to_dict("records")]
    lv = [_level(*(sp if pb else ps)) for sp, ps, pb in zip(spans, pspans, pub)]
    df["level"], df["level_alt"] = [x[0] for x in lv], [x[1] for x in lv]
    chosen = [sp if pb else ps for sp, ps, pb in zip(spans, pspans, pub)]
    df["lo_n"], df["hi_n"] = [c[0] for c in chosen], [c[1] for c in chosen]   # PK=-1, K=0, 1..12
    df["level_group"] = df["level"].map(lambda x: None if x is None else ("high" if x == "high" else "other"))
    free = pd.to_numeric(df["Free Lunch"], errors="coerce")
    red = pd.to_numeric(df["Reduced Lunch"], errors="coerce")
    frl = (free + red) / df["enrollment"].where(df["enrollment"] > 0)
    df["frl_pct"] = frl.where(pub & (frl <= 1))
    df["district"] = df["District"].where(pub)
    df["religion"] = df["PSS_RELIG"].map(RELIG).where(~pub)
    df["charter"] = (df["Charter"] == "Yes").where(pub)
    df["ses_quartile"] = pd.qcut(df["frl_pct"], 4, labels=["Q1_low_poverty", "Q2", "Q3", "Q4_high_poverty"])

    # --- wiki match reliability (HF release has no tier column; take it from the matcher output) ---
    df["match_method"] = None
    try:
        mm = pd.read_csv(resolve(cfg["paths"]["wiki_matches"]), dtype=str)
        df["match_method"] = df["nces_id"].map(mm.drop_duplicates("nces_school_id").set_index("nces_school_id")["match_method"])
    except FileNotFoundError:
        print("WARN: wiki_matches not found; weak-match filter skipped")

    # --- eligibility filters ---
    fc = cfg["frame"]
    ok = df.level.notna() & df.locale3.notna() & df.enrollment.notna() & (df.city != "") & df.state.notna()
    ok &= ~(pub & ~df["type"].isin(fc["public_types"]))
    ok &= ~(pub & ~df["Status"].isin(fc["public_statuses"]))   # default excludes New/Added: models cannot know them (cutoff)
    if fc.get("require_high_school"):
        hi = pd.to_numeric(df["hi_n"], errors="coerce")
        ok &= hi >= 12                      # serves grade 12: pure high schools plus 6-12 / 7-12 / K-12 schools
    if fc["exclude_territories"]:
        ok &= ~df.state.isin(TERRITORIES)
    if fc["require_frl_for_public"]:
        ok &= ~(pub & df.frl_pct.isna())
    if df.match_method.notna().any():
        ok &= ~((df.from_wikipedia == 1) & ~df.match_method.isin(fc["wiki_match_methods"]))
    # same name+city+state is ambiguous to a model -> drop all of them
    dup = df.duplicated(["school_name", "city", "state"], keep=False)
    df["eligible"] = ok & ~dup
    nm = df["school_name"].str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.strip()
    df["name_freq_state"] = df.groupby([df["state"], nm])["nces_id"].transform("size")   # same name used by N schools in the state
    df["log_name_freq"] = df["name_freq_state"].map(lambda x: __import__("math").log(x))
    keep = ["nces_id", "name_freq_state", "log_name_freq", "school_name", "city", "state", "county", "sector", "from_wikipedia", "match_method", "locale4",
            "locale3", "level", "level_alt", "level_group", "lo_n", "hi_n", "enrollment", "log_enroll", "frl_pct", "ses_quartile", "district",
            "religion", "charter", "eligible"]
    out = df[keep].reset_index(drop=True)
    p = resolve(cfg["paths"]["frame"])
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(p)
    e = out[out.eligible]
    print(f"frame: {len(out):,} schools, {len(e):,} eligible -> {p}")
    print(e.groupby(["from_wikipedia", "sector", "level_group"]).size().unstack(fill_value=0))
    return out
