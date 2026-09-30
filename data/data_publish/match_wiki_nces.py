#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Match verified Wikipedia school articles to NCES schools; write the matches and
the unmatched articles (with a reason).

Tiers — the first that yields a match wins for each article:

  1.  nces_id       Wikidata NCES id (P2484) equals an NCES school_id.
  1b. nces_id_stale Wikidata carries an id NCES has since re-issued: same state
                    and 5-digit school number, name core similarity >= 80.
  2.  name_state    normalized name + state are identical.
  3.  fuzzy         best similarity of the distinctive name core (generic words
                    like "high school"/"academy" removed) within the state,
                    rapidfuzz token_sort_ratio (stdlib difflib fallback); accepted
                    at >= 96, or >= --threshold when the title's city matches.
  4.  geo           the nearest NCES school within 1 km of the article's
                    coordinates that shares a distinctive, non-place name word
                    and whose name core is broadly similar (token_set >= 60).

Checks on tiers 2-4: a candidate is dropped when it contradicts the article —
a different city named in the title ("(City, State)" or "(City)"), or an NCES
grade span that can't serve the article's level (a high-school article is never
put on a K-5 school). Equally good candidates (same-named schools, fuzzy ties)
are resolved by the title's city, then by the article's coordinates (<= 50 km);
otherwise the article stays unmatched rather than guessing.

Only rows whose `validation` tag is in --statuses (default: school) are matched,
so people, events, districts, networks, colleges, closed schools and redirects
never reach the join. Each NCES school keeps at most one article: the strongest
match wins (tier, then score, then pageviews); the rest are `nces_conflict`.

Outputs (in output/): wiki_nces_matches.csv, and wiki_unmatched.csv with a
reason per unmatched article (not_operating / no_state / lost_nces_conflict /
no_nces_record_or_variant_name).

Usage:
    python match_wiki_nces.py
    python match_wiki_nces.py --threshold 90 --out matches.csv
    python match_wiki_nces.py --statuses school,unverified
"""

import argparse
import csv
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common.states import NAME_TO_USPS, state_code  # noqa: E402

try:
    from rapidfuzz import fuzz
    _BACKEND = "rapidfuzz"
except Exception:                       # pragma: no cover - portability fallback
    import difflib

    class fuzz:  # noqa: N801 - mimic rapidfuzz API surface we use
        @staticmethod
        def token_sort_ratio(a, b):
            ta, tb = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
            return difflib.SequenceMatcher(None, ta, tb).ratio() * 100

        @staticmethod
        def token_set_ratio(a, b):
            sa, sb = set(a.split()), set(b.split())
            common = " ".join(sorted(sa & sb))
            ra = " ".join(sorted(sa - sb)); rb = " ".join(sorted(sb - sa))
            pairs = [(common, (common + " " + ra).strip()), (common, (common + " " + rb).strip()),
                     ((common + " " + ra).strip(), (common + " " + rb).strip())]
            return max(difflib.SequenceMatcher(None, x, y).ratio() for x, y in pairs) * 100
    _BACKEND = "difflib"

_ABBREV = [
    (r"\bst\.?\b", "saint"), (r"\bmt\.?\b", "mount"), (r"\bjr\.?\b", "junior"),
    (r"\bsr\.?\b", "senior"), (r"\bft\.?\b", "fort"),
]

# Generic, non-distinctive tokens. Stripped before fuzzy scoring so similarity is
# computed on the distinctive name core ("loyola", "pace") rather than the shared
# suffix ("high school", "academy") — which otherwise inflates token_set_ratio and
# matches unrelated schools (Pace Academy -> Price Academy). Religious/affiliation
# words (christian, catholic, ...) are deliberately KEPT as distinctive.
GENERIC = {
    "school", "schools", "high", "elementary", "middle", "primary", "secondary",
    "intermediate", "junior", "senior", "the", "of", "a", "and", "at", "for",
    "prep", "preparatory", "academy", "institute", "center", "centre",
    "es", "ms", "hs", "elem", "sch", "district", "campus", "program", "education",
}


def core_name(norm):
    """Distinctive tokens only — generic education words removed."""
    return " ".join(t for t in norm.split() if t not in GENERIC)


def norm_name(s):
    """Normalize a school name for comparison."""
    s = s.lower()
    s = re.sub(r"\(.*?\)", " ", s)          # drop "(City, State)" disambiguation
    s = s.replace("&", " and ")
    for pat, rep in _ABBREV:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_city(title):
    """Best-effort city hint from a Wikipedia title's parenthetical, e.g.
    'Lincoln High School (San Diego, California)' -> 'san diego'."""
    m = re.search(r"\(([^)]*)\)", title)
    if not m:
        return ""
    return m.group(1).split(",")[0].strip().lower()


# Bare title disambiguators that name no place.
_NON_PLACE = {"school", "high school", "academy", "private school", "public school"}


def title_explicit_city(title):
    """City named in a title parenthetical: '(City, State)' or a bare '(City)'.
    '' for a bare state ('(Georgia)') or a non-place disambiguator."""
    m = re.search(r"\(([^)]*)\)", title)
    if not m:
        return ""
    inner = m.group(1).strip().lower()
    if "," in inner:
        return inner.split(",")[0].strip()
    if inner in NAME_TO_USPS or inner in _NON_PLACE or re.search(r"\d", inner):
        return ""
    return inner


# Grade-level words in a normalized name -> level bucket. "Middle/High" yields
# {middle, high}; names with no level word ("Pine Crest School") yield {}.
LEVEL_WORDS = {
    "high": "high", "senior": "high", "secondary": "high", "hs": "high",
    "middle": "middle", "junior": "middle", "intermediate": "middle", "ms": "middle",
    "elementary": "elementary", "primary": "elementary", "elem": "elementary",
    "es": "elementary",
}


def school_levels(norm):
    return {LEVEL_WORDS[t] for t in norm.split() if t in LEVEL_WORDS}


# Grade number -> level bucket (PK = -1, K = 0).
def _grade_bucket(g):
    return "elementary" if g <= 5 else "middle" if g <= 8 else "high"


_PUBLIC_GRADE = {"PK": -1, "KG": 0, "K": 0}
_PSS_ENROLL = [(-1, "PSS_ENROLL_PK"), (0, "PSS_ENROLL_K")] + \
              [(g, f"PSS_ENROLL_{g}") for g in range(1, 13)]


def _public_grade(code):
    code = (code or "").strip().upper()
    if code in _PUBLIC_GRADE:
        return _PUBLIC_GRADE[code]
    return int(code) if code.isdigit() and 1 <= int(code) <= 12 else None


def _num(v):
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def grade_levels(r):
    """Level buckets an NCES school actually serves, from its grade span.

    Public: CCD low/high grade codes (PK, KG, 01-12; UG/AE/13 and blanks give no
    span). Private: the grades with non-zero PSS enrollment — the PSS LoGrade/
    HiGrade codes are an undocumented numeric scheme, so they aren't used.
    Returns an empty set when the span is unknown."""
    if r.get("sector") == "private":
        grades = [g for g, col in _PSS_ENROLL if _num(r.get(col))]
        if not grades:
            return set()
        lo, hi = grades[0], grades[-1]
    else:
        lo, hi = _public_grade(r.get("low_grade")), _public_grade(r.get("high_grade"))
        if lo is None or hi is None or lo > hi:
            return set()
    return {_grade_bucket(g) for g in range(lo, hi + 1)}


def wiki_levels(w, wnorm, use_categories):
    """Levels a Wikipedia school claims: level words in its title, else (when
    use_categories) the enrich step's `level`, which is inferred from categories
    and so less reliable ('combined' and blank impose no constraint)."""
    lv = school_levels(wnorm)
    if not lv and use_categories and w.get("level") in ("high", "middle", "elementary"):
        lv = {w["level"]}
    return lv


# Title cities that don't pin down an NCES city: NCES files New York City
# schools under borough or neighborhood names (Bronx, Astoria, Flushing, ...).
_UNCONSTRAINED_CITIES = {"new york", "manhattan", "brooklyn", "queens", "bronx",
                         "the bronx", "staten island"}
_CITY_FILLER = {"city", "township", "town", "village", "borough", "north", "south",
                "east", "west", "new", "saint", "fort", "port", "mount", "lake",
                "upper", "lower", "the", "of"}


def _city_norm(c):
    return norm_name(c or "")


def city_compatible(title_city_name, nces_city):
    """True unless the title's city clearly names a different place. Tolerates
    punctuation/abbreviations ('St. George' = 'st george'), 'X City'/'X
    Township' vs 'X Hills' (shared distinctive word), and NYC boroughs."""
    a, b = _city_norm(title_city_name), _city_norm(nces_city)
    if not a or not b or a == b or a in _UNCONSTRAINED_CITIES:
        return True
    ta = {t for t in a.split() if t not in _CITY_FILLER}
    tb = {t for t in b.split() if t not in _CITY_FILLER}
    return bool(ta & tb)


def levels_compatible(wlevels, rec):
    """False only when both sides state levels and they cannot overlap. NCES
    levels come from the grade span, falling back to level words in the name."""
    nlevels = rec["grade_levels"] or rec["levels"]
    return not wlevels or not nlevels or bool(wlevels & nlevels)


def significant_tokens(norm):
    return {t for t in norm.split() if len(t) >= 4}


def load_nces(path, coords=None):
    """Return (by_id, by_state) where by_state[code] = list of record dicts.
    `coords` (NCES id -> (lat, lon)) adds lat/lon for the geo tier."""
    by_id = {}
    by_state = defaultdict(list)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            sid = r["school_id"].strip()
            rec = {
                "school_id": sid,
                "school_name": r["school_name"],
                "sector": r["sector"],
                "state": r["state"].strip().upper(),
                "city": r["city"].strip().lower(),
                "low_grade": r["low_grade"],
                "high_grade": r["high_grade"],
                "norm": norm_name(r["school_name"]),
            }
            rec["core"] = core_name(rec["norm"])
            rec["levels"] = school_levels(rec["norm"])
            rec["grade_levels"] = grade_levels(r)
            rec["lat"], rec["lon"] = (coords or {}).get(sid, (None, None))
            rec["tokens"] = significant_tokens(rec["core"])
            if sid:
                by_id[sid] = rec
            by_state[rec["state"]].append(rec)
    return by_id, by_state


def build_token_index(records):
    idx = defaultdict(list)
    for rec in records:
        for tok in rec["tokens"]:
            idx[tok].append(rec)
    return idx


OUT_FIELDS = [
    "wiki_title", "wiki_pageid", "wiki_url", "wiki_state", "wiki_level",
    "wiki_wikidata_qid", "wiki_nces_id",
    "match_method", "match_score",
    "nces_school_id", "nces_school_name", "nces_sector", "nces_state",
    "nces_city", "nces_low_grade", "nces_high_grade",
]


def emit(w, rec, method, score):
    return {
        "wiki_title": w["title"], "wiki_pageid": w["pageid"], "wiki_url": w["url"],
        "wiki_state": w["state"], "wiki_level": w["level"],
        "wiki_wikidata_qid": w["wikidata_qid"], "wiki_nces_id": w["nces_id"],
        "match_method": method, "match_score": f"{score:.1f}",
        "nces_school_id": rec["school_id"], "nces_school_name": rec["school_name"],
        "nces_sector": rec["sector"], "nces_state": rec["state"],
        "nces_city": rec["city"], "nces_low_grade": rec["low_grade"],
        "nces_high_grade": rec["high_grade"],
    }


# The match output lives in output/ (a sibling of this script). A bare --out name
# resolves here; --wiki/--nces default to the canonical pipeline artifacts,
# resolved relative to this script (data/data_publish/ -> ../{wiki,nces}_crawl/...).
HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "output")
DEFAULT_WIKI = os.path.join(HERE, "..", "wiki_crawl", "output", "schools_enriched.csv")
DEFAULT_NCES = os.path.join(HERE, "..", "nces_crawl", "output_all_schools", "all_schools_master.csv")
DEFAULT_COORDS = os.path.join(HERE, "..", "nces_crawl", "output_all_schools", "school_coordinates.csv")


def _out(name):
    return name if os.path.dirname(name) else os.path.join(OUT_DIR, name)


# Stronger tiers win when several Wikipedia articles land on one NCES school.
METHOD_RANK = {"nces_id": 0, "nces_id_stale": 1, "name_state": 2, "fuzzy": 3, "geo": 4}


def parse_statuses(s):
    """'school,unverified' -> {'school', 'unverified'}; '' or 'all' -> None (no filter)."""
    toks = {t.strip() for t in (s or "").split(",") if t.strip()}
    return None if not toks or "all" in toks else toks


def match_one(w, by_id, by_state, token_idx, threshold, stats, geo=None):
    """Best (nces_record, method, score) for one Wikipedia row, or None."""
    nid = (w.get("nces_id") or "").strip()
    # tier 1: exact NCES id
    if nid and nid in by_id:
        return by_id[nid], "nces_id", 100.0
    # tier 1b: stale NCES id — Wikidata still carries an id NCES has since
    # re-issued (typically a district reorganization changes the 7-digit LEA
    # prefix but keeps the state and 5-digit school number). Accept a same-state,
    # same-school-number record whose name core agrees.
    if nid and len(nid) == 12 and nid.isdigit():
        wcore = core_name(norm_name(w["title"]))
        for r in by_state.get(state_code(w["state"]) or "", ()):
            sid = r["school_id"]
            if (len(sid) == 12 and sid[:2] == nid[:2] and sid[-5:] == nid[-5:]
                    and wcore and fuzz.token_sort_ratio(wcore, r["core"]) >= 80):
                stats["stale_id_recovered"] += 1
                return r, "nces_id_stale", 100.0

    code = state_code(w["state"])
    wnorm = norm_name(w["title"])
    wcity = title_city(w["title"])
    wexplicit = title_explicit_city(w["title"])
    cands = by_state.get(code, []) if code else []

    # tier 2: exact normalized name + state (city-disambiguated). Same-named
    # schools are common, so a candidate must not contradict the title's city or
    # the article's grade level; if every candidate does, fall through to fuzzy.
    exact = [r for r in cands if r["norm"] == wnorm and wnorm]
    if exact:
        # Title level words only here: an exact name match is strong evidence,
        # so the noisier category-inferred level isn't allowed to veto it.
        tlevels = wiki_levels(w, wnorm, use_categories=False)
        ok = [r for r in exact
              if city_compatible(wexplicit, r["city"])
              and levels_compatible(tlevels, r)]
        if len(ok) < len(exact):
            stats["name_state_rejected"] += len(exact) - len(ok)
        if ok:
            best = pick_one(ok, w, wcity, stats)
            if best is not None:
                return best, "name_state", 100.0
            return None          # same-named schools and nothing to choose by

    wcore = core_name(wnorm)
    hit = _fuzzy(w, wnorm, wcore, wcity, wexplicit, code, cands, token_idx, threshold, stats)
    if hit is None and geo is not None:
        hit = _geo(w, wnorm, wcore, wexplicit, geo)
    return hit


def _km(lat1, lon1, lat2, lon2):
    return 111.0 * math.hypot(lat2 - lat1, (lon2 - lon1) * math.cos(math.radians(lat1)))


PICK_MAX_KM = 50.0


def pick_one(cands, w, wcity, stats):
    """Choose among equally good candidates (same-named schools in a state, or a
    fuzzy-score tie) without guessing: the one in the title's city, else the one
    nearest the article's coordinates (within PICK_MAX_KM), else None."""
    if len(cands) == 1:
        return cands[0]
    stats["ambiguous"] += 1
    in_city = [r for r in cands if wcity and r["city"] == wcity]
    if len(in_city) == 1:
        return in_city[0]
    try:
        lat, lon = float(w.get("lat") or ""), float(w.get("lon") or "")
    except ValueError:
        lat = None
    if lat is not None:
        near = sorted((_km(lat, lon, r["lat"], r["lon"]), r["school_id"], r)
                      for r in (in_city or cands) if r.get("lat") is not None)
        if near and near[0][0] <= PICK_MAX_KM:
            stats["ambiguous_resolved_by_coords"] += 1
            return near[0][2]
    stats["ambiguous_skipped"] += 1
    return None


def _fuzzy(w, wnorm, wcore, wcity, wexplicit, code, cands, token_idx, threshold, stats):
    """tier 3: fuzzy on the DISTINCTIVE name core within the same state."""
    if not cands or len(wcore.replace(" ", "")) < 4:   # skip too-generic cores
        return None
    seen, pool = set(), []
    for tok in significant_tokens(wcore):
        for r in token_idx[code].get(tok, ()):
            if r["school_id"] not in seen:
                seen.add(r["school_id"]); pool.append(r)
    best_s, best = -1.0, []
    wlevels = wiki_levels(w, wnorm, use_categories=True)
    for r in pool:
        if not r["core"]:
            continue
        # The core drops level words and ignores place, so reject candidates
        # that contradict the title: a different city named in the title, or a
        # grade span that can't overlap the article's level ("Troy High School"
        # vs a K-5 "Troy Elementary").
        if not city_compatible(wexplicit, r["city"]):
            continue
        if not levels_compatible(wlevels, r):
            continue
        # token_sort_ratio on cores: distinctive name, order-insensitive,
        # NOT inflated by shared generic suffix.
        s = fuzz.token_sort_ratio(wcore, r["core"])
        if wcity and r["city"] == wcity:
            s = min(100.0, s + 6.0)         # confirming-city boost
        if s > best_s:
            best_s, best = s, [r]
        elif s == best_s:
            best.append(r)
    if not best:
        return None
    best_r = pick_one(best, w, wcity, stats)
    if best_r is None:
        return None
    # Accept on strong core similarity, OR good similarity confirmed by a
    # matching city in the Wikipedia title.
    city_ok = bool(wcity) and best_r["city"] == wcity
    if best_s >= max(threshold, 96.0) or (best_s >= threshold and city_ok):
        return best_r, "fuzzy", best_s
    return None


class GeoIndex:
    """NCES schools on a 0.01-degree grid (~1 km) for nearest-school lookups."""

    def __init__(self, records):
        self.grid = defaultdict(list)
        for r in records:
            if r.get("lat") is not None:
                self.grid[(int(r["lat"] * 100), int(r["lon"] * 100))].append(r)

    def near(self, lat, lon, max_km):
        cy, cx, reach = int(lat * 100), int(lon * 100), int(max_km) + 1
        out = []
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                for r in self.grid.get((cy + dy, cx + dx), ()):
                    km = _km(lat, lon, r["lat"], r["lon"])
                    if km <= max_km:
                        out.append((km, r))
        return sorted(out, key=lambda t: t[0])


GEO_MAX_KM = 1.0
GEO_MIN_SIMILARITY = 60


def _geo(w, wnorm, wcore, wexplicit, geo):
    """tier 4: the nearest NCES school within GEO_MAX_KM of the article's
    coordinates that shares a distinctive name token — geography disambiguates
    names too different for the fuzzy tier (informal titles, former names)."""
    try:
        lat, lon = float(w.get("lat") or ""), float(w.get("lon") or "")
    except ValueError:
        return None
    wtoks = significant_tokens(wcore)
    if not wtoks:
        return None
    wlevels = wiki_levels(w, wnorm, use_categories=True)
    for km, r in geo.near(lat, lon, GEO_MAX_KM):
        # A shared *place* word proves nothing nearby ("Wichita Falls High School"
        # vs "Premier HS - Wichita Falls"), so the shared word must not be part
        # of the school's city, and the name cores must be broadly similar.
        place = set(_city_norm(r["city"]).split())
        if not ((wtoks & r["tokens"]) - place):
            continue
        if fuzz.token_set_ratio(wcore, r["core"]) < GEO_MIN_SIMILARITY:
            continue
        if city_compatible(wexplicit, r["city"]) and levels_compatible(wlevels, r):
            return r, "geo", round(100.0 * (1 - km / GEO_MAX_KM), 1)
    return None


def load_coords(path):
    """NCES id -> (lat, lon) from nces_crawl's school_coordinates.csv (NCES EDGE
    for public schools, the PSS public-use file for private ones)."""
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["school_id"]: (float(r["lat"]), float(r["lon"]))
                for r in csv.DictReader(fh) if r["lat"] and r["lon"]}


def unmatched_reason(w):
    """Why a kept Wikipedia school has no NCES match (for wiki_unmatched.csv)."""
    if w.get("operating") == "no":
        return "not_operating"          # closed/historic: NCES lists current schools
    if not state_code(w.get("state", "")):
        return "no_state"               # can only match by id or coordinates
    return "no_nces_record_or_variant_name"


def _pageviews(w):
    try:
        return int(float(w.get("pageviews_60d") or 0))
    except ValueError:
        return 0


def main():
    ap = argparse.ArgumentParser(description="Match cleaned Wikipedia schools to NCES master.")
    ap.add_argument("--wiki", default=DEFAULT_WIKI)
    ap.add_argument("--nces", default=DEFAULT_NCES)
    ap.add_argument("--out", default="wiki_nces_matches.csv")
    ap.add_argument("--threshold", type=float, default=88.0,
                    help="min fuzzy score (0-100) to accept a name match (default 88)")
    ap.add_argument("--nces-coords", default=DEFAULT_COORDS,
                    help="NCES coordinates (school_coordinates.csv) for the geo tier; "
                         "'' disables it")
    ap.add_argument("--unmatched", default="wiki_unmatched.csv",
                    help="where to write kept Wikipedia schools with no match")
    ap.add_argument("--statuses", default="school",
                    help="comma list of crawl `validation` tags to match "
                         "(default: school; 'all' disables the filter)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    args.wiki = _out(args.wiki)
    args.out = _out(args.out)
    statuses = parse_statuses(args.statuses)

    sys.stderr.write(f"fuzzy backend: {_BACKEND}\n")
    coords = load_coords(args.nces_coords) if args.nces_coords and os.path.exists(args.nces_coords) else {}
    by_id, by_state = load_nces(args.nces, coords)
    token_idx = {st: build_token_index(recs) for st, recs in by_state.items()}
    geo = GeoIndex(by_id.values()) if coords else None
    sys.stderr.write(f"geo tier: {'on' if geo else 'off'} "
                     f"({sum(r['lat'] is not None for r in by_id.values()):,} NCES schools with coordinates)\n")
    n_nces = sum(len(v) for v in by_state.values())
    sys.stderr.write(f"loaded NCES: {n_nces:,} schools in {len(by_state)} states\n")

    with open(args.wiki, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        has_validation = "validation" in (reader.fieldnames or [])
        wiki_all = list(reader)
    if statuses is None:
        wiki = wiki_all
    elif has_validation:
        wiki = [w for w in wiki_all if w["validation"] in statuses]
    else:
        sys.exit(f"{args.wiki} has no `validation` column, so --statuses "
                 f"{args.statuses!r} cannot be applied.\n"
                 f"  re-run wiki_crawl/enrich_schools.py on the tagged crawl, "
                 f"or pass --statuses all to match every row unfiltered.")
    sys.stderr.write(f"loaded Wikipedia: {len(wiki_all):,} rows, "
                     f"{len(wiki):,} kept by --statuses {args.statuses}\n")

    stats = defaultdict(int)
    # nces school_id -> (rank key, wiki row, nces record, method, score)
    claims, unmatched = {}, set()
    for w in wiki:
        hit = match_one(w, by_id, by_state, token_idx, args.threshold, stats, geo)
        if hit is None:
            stats["unmatched"] += 1
            unmatched.add(w["pageid"])
            continue
        rec, method, score = hit
        key = (METHOD_RANK[method], -score, -_pageviews(w))
        prev = claims.get(rec["school_id"])
        if prev is None or key < prev[0]:
            claims[rec["school_id"]] = (key, w, rec, method, score)
        stats["nces_conflict"] += prev is not None   # one of the two loses

    matches = [emit(w, rec, method, score)
               for _, w, rec, method, score in claims.values()]
    for m in matches:
        stats[m["match_method"]] += 1

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        wr.writeheader()
        wr.writerows(matches)

    # Kept Wikipedia schools with no NCES match, labeled with the likely reason.
    matched_pages = {m["wiki_pageid"] for m in matches}
    reasons = defaultdict(int)
    with open(_out(args.unmatched), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["title", "pageid", "url", "state", "level",
                                           "wikidata_qid", "nces_id", "operating",
                                           "description", "reason"],
                            extrasaction="ignore")
        wr.writeheader()
        for w in wiki:
            if w["pageid"] in matched_pages:
                continue
            reason = "lost_nces_conflict" if w["pageid"] not in unmatched else unmatched_reason(w)
            reasons[reason] += 1
            wr.writerow({**w, "reason": reason})

    # summary
    by_sector = defaultdict(int)
    for m in matches:
        by_sector[m["nces_sector"]] += 1
    sys.stderr.write(
        f"\n=== matches -> {args.out} ===\n"
        f"  total matched : {len(matches):,} / {len(wiki):,} wiki "
        f"({100*len(matches)/max(len(wiki), 1):.1f}%)\n"
        f"    by nces_id    : {stats['nces_id']:,}\n"
        f"    by name+state : {stats['name_state']:,}  "
        f"(candidates rejected on city/level: {stats['name_state_rejected']:,})\n"
        f"    by stale id   : {stats['nces_id_stale']:,}\n"
        f"    by fuzzy      : {stats['fuzzy']:,}  (>= {args.threshold:g})\n"
        f"    by geo        : {stats['geo']:,}  (<= {GEO_MAX_KM:g} km + shared name token)\n"
        f"  ambiguous     : {stats['ambiguous']:,} same-named/tied candidates -> "
        f"{stats['ambiguous_resolved_by_coords']:,} resolved by coordinates, "
        f"{stats['ambiguous_skipped']:,} left unmatched\n"
        f"  nces_conflict : {stats['nces_conflict']:,}  "
        f"(article dropped: its NCES school was claimed by a stronger match)\n"
        f"  unmatched     : {stats['unmatched']:,}  -> {_out(args.unmatched)}\n"
        f"    by reason   : {dict(reasons)}\n"
        f"  matched NCES by sector: public={by_sector['public']:,} private={by_sector['private']:,}\n"
        f"  distinct NCES schools covered: {len(matches):,} / {n_nces:,} "
        f"({100*len(matches)/n_nces:.2f}%)\n"
    )


if __name__ == "__main__":
    main()
