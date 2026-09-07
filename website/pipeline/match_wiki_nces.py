#!/usr/bin/env python3
"""Match the cleaned Wikipedia school set against the NCES master and write a CSV
of all matches.

Matching is tiered; the first tier that hits wins for each Wikipedia school:

  1. nces_id    - exact Wikidata NCES-ID (P2484) -> NCES public `school_id`.
  2. name_state - exact normalized name + state. When several NCES schools share
                  the name in that state, the one whose city appears in the
                  Wikipedia title is preferred (else the first; counted ambiguous).
  3. fuzzy      - best normalized-name similarity within the same state, using
                  rapidfuzz token_set_ratio (falls back to stdlib difflib). A
                  shared city in the Wikipedia title boosts the score. Accepted
                  when the score >= --threshold.

This recovers private-school matches that the ID join misses (NCES private
schools have no Wikidata NCES-ID), at the cost of some fuzziness — hence the
score column so low-confidence rows can be reviewed or filtered.

Usage:
    python match_wiki_nces.py            # defaults below -> wiki_nces_matches.csv
    python match_wiki_nces.py --threshold 90 --out matches.csv
"""

import argparse
import csv
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
        def token_set_ratio(a, b):
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


def main():
    ap = argparse.ArgumentParser(description="Match cleaned Wikipedia schools to NCES master.")
    ap.add_argument("--wiki", default="schools_new_enriched.csv")
    ap.add_argument("--nces", default="../../data/nces_crawl/output_all_schools/all_schools_master.csv")
    ap.add_argument("--out", default="wiki_nces_matches.csv")
    ap.add_argument("--threshold", type=float, default=88.0,
                    help="min fuzzy score (0-100) to accept a name match (default 88)")
    args = ap.parse_args()

    sys.stderr.write(f"fuzzy backend: {_BACKEND}\n")
    by_id, by_state = load_nces(args.nces)
    token_idx = {st: build_token_index(recs) for st, recs in by_state.items()}
    n_nces = sum(len(v) for v in by_state.values())
    sys.stderr.write(f"loaded NCES: {n_nces:,} schools in {len(by_state)} states\n")

    wiki = list(csv.DictReader(open(args.wiki, newline="", encoding="utf-8", errors="replace")))
    sys.stderr.write(f"loaded Wikipedia clean set: {len(wiki):,} schools\n")

    matches = []
    stats = defaultdict(int)
    used_nces = set()

    for w in wiki:
        nid = w["nces_id"].strip()
        # tier 1: exact NCES id
        if nid and nid in by_id:
            matches.append(emit(w, by_id[nid], "nces_id", 100.0))
            used_nces.add(by_id[nid]["school_id"]); stats["nces_id"] += 1
            continue

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
            matches.append(emit(w, best, "name_state", 100.0))
            used_nces.add(best["school_id"]); stats["name_state"] += 1
            continue

        # tier 3: fuzzy on the DISTINCTIVE name core within the same state.
        wcore = core_name(wnorm)
        if cands and len(wcore.replace(" ", "")) >= 4:   # skip too-generic cores
            seen, pool = set(), []
            for tok in significant_tokens(wcore):
                for r in token_idx[code].get(tok, ()):
                    if r["school_id"] not in seen:
                        seen.add(r["school_id"]); pool.append(r)
            best_r, best_s = None, -1.0
            for r in pool:
                if not r["core"]:
                    continue
                # token_sort_ratio on cores: distinctive name, order-insensitive,
                # NOT inflated by shared generic suffix.
                s = fuzz.token_sort_ratio(wcore, r["core"])
                if wcity and r["city"] == wcity:
                    s = min(100.0, s + 6.0)         # confirming-city boost
                if s > best_s:
                    best_s, best_r = s, r
            if best_r is not None:
                # Accept on strong core similarity, OR good similarity confirmed
                # by a matching city in the Wikipedia title.
                city_ok = bool(wcity) and best_r["city"] == wcity
                if best_s >= max(args.threshold, 96.0) or (best_s >= args.threshold and city_ok):
                    matches.append(emit(w, best_r, "fuzzy", best_s))
                    used_nces.add(best_r["school_id"]); stats["fuzzy"] += 1
                    continue

        stats["unmatched"] += 1

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
        f"({100*len(matches)/len(wiki):.1f}%)\n"
        f"    by nces_id    : {stats['nces_id']:,}\n"
        f"    by name+state : {stats['name_state']:,}  "
        f"(ambiguous: {stats['name_state_ambiguous']:,})\n"
        f"    by fuzzy      : {stats['fuzzy']:,}  (>= {args.threshold:g})\n"
        f"  unmatched     : {stats['unmatched']:,}\n"
        f"  matched NCES by sector: public={by_sector['public']:,} private={by_sector['private']:,}\n"
        f"  distinct NCES schools covered: {len(used_nces):,} / {n_nces:,} "
        f"({100*len(used_nces)/n_nces:.2f}%)\n"
    )


if __name__ == "__main__":
    main()
