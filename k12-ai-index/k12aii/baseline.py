"""Name-only baseline: how well can each item be guessed from the school NAME (and city) alone, with no knowledge of the school?
Model accuracy minus this baseline is the part that reflects actual knowledge. Deliberately naive keyword rules."""
import re

import numpy as np
import pandas as pd

from .score import district_match, enroll_ok, grades_ok

CATHOLIC = r"catholic|\bsaint\b|\bst\b|\bsts\b|\bholy\b|sacred|our lady|immaculate|blessed|cathedral|parish|\bmary\b|\bjoseph\b"
OTHER_REL = r"christian|lutheran|baptist|jewish|yeshiva|torah|hebrew|islamic|quran|adventist|methodist|episcopal|presbyterian|bible|covenant|calvary|faith|grace|trinity|gospel|church|mennonite|friends"
PRIVATE_KW = CATHOLIC + "|" + OTHER_REL + r"|montessori|waldorf|country day|day school"
SPAN = {"elementary": (0, 5), "middle": (6, 8), "high": (9, 12), "combined": (0, 12)}


def _lvl(name, sector):
    n = name.lower()
    if re.search(r"elementary|primary|intermediate|early childhood|kindergarten", n):
        return "elementary"
    if re.search(r"middle|junior|\bjr\b", n):
        return "middle"
    if re.search(r"\bhigh\b|senior|\bsr\b", n):
        return "high"
    return "elementary" if sector == "public" else "combined"


def predict(df):
    """Return the baseline's answer for every item, from name/city only."""
    n = df.school_name.str.lower()
    out = pd.DataFrame({"nces_id": df.nces_id.values})
    out["sector"] = np.where(n.str.contains(PRIVATE_KW).values, "private", "public")
    out["level"] = [_lvl(a, s) for a, s in zip(df.school_name, out.sector)]
    out["religion"] = np.where(n.str.contains(CATHOLIC).values, "catholic", np.where(n.str.contains(OTHER_REL).values, "other_religious", "none"))
    out["district"] = df.city.values
    out["lo_pred"] = [SPAN[l][0] for l in out.level]
    out["hi_pred"] = [SPAN[l][1] for l in out.level]
    med = df.assign(_lv=out.level.values, _s=out.sector.values).groupby(["_s", "_lv"]).enrollment.median()
    out["enroll_pred"] = [med.get((s, l), df.enrollment.median()) for s, l in zip(out.sector, out.level)]
    out["charter"] = n.str.contains(r"charter|academy|prep|leadership|virtual|online|digital").values
    return out


def baseline_long(df):
    """One row per (school, item): whether the name-only baseline is correct. NaN where the item does not apply."""
    p = predict(df).reset_index(drop=True)
    d = df.reset_index(drop=True)
    pub = d.sector == "public"
    rows = {
        "sector": p.sector == d.sector,
        "level": [(a == b) or (a == c) for a, b, c in zip(p.level, d.level, d.level_alt)],
        "district": [district_match(c, t or "") if (s == "public" and not ch) else np.nan
                     for c, t, s, ch in zip(p.district, d.district, d.sector, d.charter)],
        "religion": [(a == b) if s == "private" else np.nan for a, b, s in zip(p.religion, d.religion, d.sector)],
        "grades": [grades_ok(lo, hi, {"lo_n": a, "hi_n": b}) for lo, hi, a, b in zip(p.lo_pred, p.hi_pred, d.lo_n, d.hi_n)],
        "enroll": [enroll_ok(e, {"enrollment": t}) for e, t in zip(p.enroll_pred, d.enrollment)],
        "charter": [(bool(a) == bool(b)) if s == "public" else np.nan for a, b, s in zip(p.charter, d.charter, d.sector)],
    }
    L = pd.concat([pd.DataFrame({"nces_id": d.nces_id, "item": k, "base_ok": pd.Series(v, dtype="float")}) for k, v in rows.items()])
    return L.dropna(subset=["base_ok"])


def report(frame):
    e = frame[frame.eligible]
    B = baseline_long(e).merge(e[["nces_id", "from_wikipedia", "sector"]], on="nces_id")
    print(f"Name-only baseline accuracy over all {len(e):,} eligible schools (no model involved):\n")
    t = B.groupby(["item", "from_wikipedia"]).base_ok.mean().unstack().round(3)
    t["diff(wiki-no)"] = (t[1] - t[0]).round(3)
    t.columns = ["no-wiki", "wiki", "diff(wiki-no)"]
    print(t.to_string())
    print("\nIf the diff is ~0 the names of wiki / non-wiki schools are equally guessable, so a model gap is not a naming artefact; "
          "a positive diff means part of any model gap is just that wiki schools have more telling names.")
