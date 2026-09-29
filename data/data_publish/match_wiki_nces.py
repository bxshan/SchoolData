# Author: Boxuan Shan + support from Claude Opus 4.8
#!/usr/bin/env python3
"""Match the cleaned Wikipedia school set against the NCES master and write a CSV
of all matches.

Matching is tiered; the first tier that hits wins for each Wikipedia school:

  1. nces_id    - exact Wikidata NCES-ID (P2484) -> NCES public `school_id`.
  2. name_state - exact normalized name + state. When several NCES schools share
                  the name in that state, the one whose city appears in the
                  Wikipedia title is preferred (else the first; counted ambiguous).
  3. fuzzy      - best similarity of the distinctive name core (generic words
                  like "high school"/"academy" removed) within the same state,
                  using rapidfuzz token_sort_ratio (falls back to stdlib
                  difflib). A shared city in the Wikipedia title boosts the
                  score. Accepted at >= 96, or >= --threshold with a city match.
                  Candidates are skipped when the title's "(City, State)" names
                  a different city, or when both names carry grade-level words
                  that don't overlap (high vs elementary), since the core
                  comparison ignores both.

Only Wikipedia rows whose crawl `validation` tag is in --statuses (default:
`school`) are matched, so events, people, districts and defunct schools tagged by
crawl_k12_schools.py never reach the NCES join.

Each NCES school is claimed by at most one Wikipedia article: when several
articles land on the same school, the strongest match wins (nces_id > name_state
> fuzzy, then higher score, then more pageviews) and the rest are counted as
`nces_conflict` and left unmatched.

This recovers private-school matches that the ID join misses (NCES private
schools have no Wikidata NCES-ID), at the cost of some fuzziness — hence the
score column so low-confidence rows can be reviewed or filtered.

Usage:
    python match_wiki_nces.py            # defaults below -> wiki_nces_matches.csv
    python match_wiki_nces.py --threshold 90 --out matches.csv
    python match_wiki_nces.py --statuses school,unverified
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

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
    _BACKEND = "difflib"

# Full state name -> USPS code (NCES uses 2-letter codes; Wikipedia state is the
# full name or blank).
STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR", "guam": "GU",
    "american samoa": "AS", "northern mariana islands": "MP",
    "virgin islands": "VI", "u.s. virgin islands": "VI",
    "united states virgin islands": "VI",
}

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


def state_code(s):
    s = (s or "").strip()
    if len(s) == 2 and s.upper() in set(STATE_ABBR.values()):
        return s.upper()
    return STATE_ABBR.get(s.lower(), "")


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
    if inner in STATE_ABBR or inner in _NON_PLACE or re.search(r"\d", inner):
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


def significant_tokens(norm):
    return {t for t in norm.split() if len(t) >= 4}


def load_nces(path):
    """Return (by_id, by_state) where by_state[code] = list of record dicts."""
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


def _out(name):
    return name if os.path.dirname(name) else os.path.join(OUT_DIR, name)


# Stronger tiers win when several Wikipedia articles land on one NCES school.
METHOD_RANK = {"nces_id": 0, "name_state": 1, "fuzzy": 2}


def parse_statuses(s):
    """'school,unverified' -> {'school', 'unverified'}; '' or 'all' -> None (no filter)."""
    toks = {t.strip() for t in (s or "").split(",") if t.strip()}
    return None if not toks or "all" in toks else toks


def match_one(w, by_id, by_state, token_idx, threshold, stats):
    """Best (nces_record, method, score) for one Wikipedia row, or None."""
    nid = (w.get("nces_id") or "").strip()
    # tier 1: exact NCES id
    if nid and nid in by_id:
        return by_id[nid], "nces_id", 100.0

    code = state_code(w["state"])
    wnorm = norm_name(w["title"])
    wcity = title_city(w["title"])
    cands = by_state.get(code, []) if code else []

    # tier 2: exact normalized name + state (city-disambiguated)
    exact = [r for r in cands if r["norm"] == wnorm and wnorm]
    if exact:
        best = next((r for r in exact if wcity and r["city"] == wcity), exact[0])
        if len(exact) > 1:
            stats["name_state_ambiguous"] += 1
        return best, "name_state", 100.0

    # tier 3: fuzzy on the DISTINCTIVE name core within the same state.
    wcore = core_name(wnorm)
    if not cands or len(wcore.replace(" ", "")) < 4:   # skip too-generic cores
        return None
    seen, pool = set(), []
    for tok in significant_tokens(wcore):
        for r in token_idx[code].get(tok, ()):
            if r["school_id"] not in seen:
                seen.add(r["school_id"]); pool.append(r)
    best_r, best_s = None, -1.0
    wexplicit = title_explicit_city(w["title"])
    wlevels = school_levels(wnorm)
    for r in pool:
        if not r["core"]:
            continue
        # The core drops level words and ignores place, so reject candidates
        # that contradict the title: a different city named in "(City, State)",
        # or disjoint grade levels ("Troy High School" vs "Troy Elementary").
        if wexplicit and r["city"] != wexplicit:
            continue
        if wlevels and r["levels"] and not (wlevels & r["levels"]):
            continue
        # token_sort_ratio on cores: distinctive name, order-insensitive,
        # NOT inflated by shared generic suffix.
        s = fuzz.token_sort_ratio(wcore, r["core"])
        if wcity and r["city"] == wcity:
            s = min(100.0, s + 6.0)         # confirming-city boost
        if s > best_s:
            best_s, best_r = s, r
    if best_r is None:
        return None
    # Accept on strong core similarity, OR good similarity confirmed by a
    # matching city in the Wikipedia title.
    city_ok = bool(wcity) and best_r["city"] == wcity
    if best_s >= max(threshold, 96.0) or (best_s >= threshold and city_ok):
        return best_r, "fuzzy", best_s
    return None


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
    ap.add_argument("--statuses", default="school",
                    help="comma list of crawl `validation` tags to match "
                         "(default: school; 'all' disables the filter)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    args.wiki = _out(args.wiki)
    args.out = _out(args.out)
    statuses = parse_statuses(args.statuses)

    sys.stderr.write(f"fuzzy backend: {_BACKEND}\n")
    by_id, by_state = load_nces(args.nces)
    token_idx = {st: build_token_index(recs) for st, recs in by_state.items()}
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
    claims = {}
    for w in wiki:
        hit = match_one(w, by_id, by_state, token_idx, args.threshold, stats)
        if hit is None:
            stats["unmatched"] += 1
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
        f"(ambiguous: {stats['name_state_ambiguous']:,})\n"
        f"    by fuzzy      : {stats['fuzzy']:,}  (>= {args.threshold:g})\n"
        f"  nces_conflict : {stats['nces_conflict']:,}  "
        f"(article dropped: its NCES school was claimed by a stronger match)\n"
        f"  unmatched     : {stats['unmatched']:,}\n"
        f"  matched NCES by sector: public={by_sector['public']:,} private={by_sector['private']:,}\n"
        f"  distinct NCES schools covered: {len(matches):,} / {n_nces:,} "
        f"({100*len(matches)/n_nces:.2f}%)\n"
    )


if __name__ == "__main__":
    main()
