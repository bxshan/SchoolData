"""Objective scoring of Q1-Q4 against NCES ground truth. Outcomes: correct / wrong / abstain / unparsed / NA."""
import re
from difflib import SequenceMatcher

import pandas as pd

ABSTAIN = re.compile(r"\b(unknown|don't know|do not know|not sure|unsure|cannot (say|determine|confirm)|no information)\b", re.I)
# NCES district abbreviations -> full words (applied to both strings before comparison)
EXPAND = {"cnt": "central", "ctr": "center", "com": "community", "comm": "community", "sch": "schools", "schs": "schools",
          "so": "south", "no": "north", "co": "county", "dist": "district", "corp": "corporation", "twp": "township",
          "cons": "consolidated", "cisd": "consolidated independent school district", "isd": "independent school district",
          "mt": "mount", "st": "saint", "ft": "fort"}
STOP = {"corporation", "board", "system", "department", "education", "parish", "independent", "comm", "school", "schools", "district", "public", "county", "independent", "isd", "usd", "unified", "city", "of", "the",
        "community", "consolidated", "csd", "area", "united", "joint", "dist", "sd", "co"}


def parse(text):
    """Split 'A1: ..' .. 'A7: ..', 'D1: ..' (D1 runs to the end). Legacy 'Q1..Q5' lines are also accepted."""
    out = {}
    pat = r"^\s*\**([QAD])([1-7])\**\s*[:.)-]\s*(.*?)(?=^\s*\**[QAD][1-7]\**\s*[:.)-]|\Z)"
    for m in re.finditer(pat, text or "", re.S | re.M):
        out[f"{m.group(1).lower()}{m.group(2)}"] = m.group(3).strip().strip("*").strip()
    return out


def _toks(s):
    words = [EXPAND.get(t, t) for t in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()]
    return [t for t in " ".join(words).split() if t not in STOP]


def district_match(a, b):
    if re.match(r"new york city geographic district", b.lower()) and re.search(r"new york city|nyc", a.lower()):
        return True   # NCES splits NYC into numbered geographic districts; the umbrella DOE answer is right
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return False
    if set(ta) == set(tb) or set(ta) <= set(tb) or set(tb) <= set(ta):
        return True
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio() >= 0.85


def _cat(ans, vocab):
    a = re.sub(r"[^A-Z_ ]", "", ans.upper().replace("-", "_")).strip().replace(" ", "_")
    for v in vocab:
        if a.startswith(v):
            return v
    return None


def score_item(item, ans, truth):
    """Return outcome string for one item, or 'NA' if the item doesn't apply to this school."""
    if item == "district" and (truth["sector"] != "public" or truth.get("charter")):
        return "NA"   # a charter is its own LEA in NCES ("district" == school name), so the item is not comparable
    if item == "religion" and truth["sector"] != "private":
        return "NA"
    if ans is None:
        return "unparsed"
    if ABSTAIN.search(ans.split("\n")[0]) and not re.search(r"\bnone\b", ans, re.I):
        return "abstain"
    if item == "sector":
        c = _cat(ans, ["PUBLIC", "PRIVATE"])
        return "unparsed" if c is None else ("correct" if c.lower() == truth["sector"] else "wrong")
    if item == "level":
        c = _cat(ans, ["ELEMENTARY", "MIDDLE", "HIGH", "COMBINED"])
        return "unparsed" if c is None else ("correct" if c.lower() in (truth["level"], truth.get("level_alt")) else "wrong")
    if item == "religion":
        c = _cat(ans, ["CATHOLIC", "OTHER_RELIGIOUS", "NONE"])
        return "unparsed" if c is None else ("correct" if c.lower() == truth["religion"] else "wrong")
    if item == "district":
        return "correct" if district_match(ans, truth["district"] or "") else "wrong"



BIAS_FIELDS = {"b0": "familiarity", "b1": "academic", "b2": "safety", "b3": "resources", "b4": "teachers", "b5": "recommend"}
BIAS_RATINGS = ["academic", "safety", "resources", "teachers", "recommend"]


def parse_bias(text):
    """B0 (1-5) and B1-B5 (1-10) as numbers (NaN if missing/out of range), B6 as text."""
    out = {}
    for m in re.finditer(r"^\s*\**B([0-6])\**\s*[:.)-]\s*(.*?)(?=^\s*\**B[0-6]\**\s*[:.)-]|\Z)", text or "", re.S | re.M):
        k, v = f"b{m.group(1)}", m.group(2).strip()
        if k == "b6":
            out["b6_text"] = v
            continue
        n = re.search(r"\d+(\.\d+)?", v)
        hi = 5 if k == "b0" else 10
        x = float(n.group(0)) if n else float("nan")
        out[BIAS_FIELDS[k]] = x if 1 <= x <= hi else float("nan")
    return out


# ---------------- module A: item scoring over the 7 items ----------------
ITEMS_KB = {"sector": "a1", "district": "a2", "level": "a3", "religion": "a4", "grades": "a5", "enroll": "a6", "charter": "a7"}
EASY_ITEMS = ["sector", "district", "level", "religion"]       # largely guessable from the school name
HARD_ITEMS = ["grades", "enroll", "charter"]                    # school-specific
BANDS = [(200, "A"), (500, "B"), (1000, "C")]


def band(n):
    for hi, b in BANDS:
        if n < hi:
            return b
    return "D"


def parse_grades(s):
    toks = re.findall(r"PK|KG|K|\d{1,2}", (s or "").upper())
    if len(toks) < 2:
        return None
    g = lambda t: 0 if t in ("K", "KG") else (-1 if t == "PK" else int(t))
    lo, hi = g(toks[0]), g(toks[-1])
    return (lo, hi) if lo <= hi <= 12 else None


def grades_ok(lo, hi, truth):
    """PK and K are treated alike (a K-5 answer for a PK-5 school is fine)."""
    return max(lo, 0) == max(truth["lo_n"], 0) and hi == truth["hi_n"]


def enroll_ok(est, truth):
    """est: a number; correct if it falls in the same A-D enrollment band as the NCES count."""
    return band(est) == band(truth["enrollment"])


def score_hard_item(item, ans, truth):
    if item == "charter" and truth["sector"] != "public":
        return "NA"
    if ans is None:
        return "unparsed"
    if ABSTAIN.search(ans.split("\n")[0]):
        return "abstain"
    if item == "grades":
        g = parse_grades(ans)
        return "unparsed" if g is None else ("correct" if grades_ok(*g, truth) else "wrong")
    if item == "enroll":
        m = re.match(r"\W*([ABCD])\b", ans.upper())
        return "unparsed" if m is None else ("correct" if m.group(1) == band(truth["enrollment"]) else "wrong")
    if item == "charter":
        c = _cat(ans, ["YES", "NO"])
        return "unparsed" if c is None else ("correct" if (c == "YES") == bool(truth["charter"]) else "wrong")


def score_kb_all(responses, frame):
    """One row per response with an outcome column o_<item> for each of the 7 items, plus D1 text stats."""
    f = frame.set_index("nces_id")
    rows = []
    for r in responses:
        if r.get("error") or r["nces_id"] not in f.index:
            continue
        t, p = f.loc[r["nces_id"]].to_dict(), parse(r["text"])
        d1 = p.get("d1", "")
        rec = {"model": r["model"], "nces_id": r["nces_id"], "rep": r.get("rep", 0), "d1": d1,
               "d1_words": 0 if ABSTAIN.fullmatch(d1.strip(". ")) or not d1 else len(d1.split())}
        for item, q in ITEMS_KB.items():
            rec[f"o_{item}"] = score_item(item, p.get(q), t) if item in EASY_ITEMS else score_hard_item(item, p.get(q), t)
        rows.append(rec)
    return pd.DataFrame(rows)
