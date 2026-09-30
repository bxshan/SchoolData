#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Build the static map dataset for SchoolData.

Builds every NCES school (public + private) from the same data the Hugging Face
dataset uses — data/nces_crawl's all-schools master plus its NCES coordinates
file (EDGE for public schools, the PSS public-use file for private ones) — flags
which schools already have an English Wikipedia article, and writes a compact
JSON the Next.js/Deck.gl frontend loads as a static asset.

`has_wikipedia` is an EXACT join on the NCES school id against the audited
Wikipedia<->NCES matcher output (data/data_publish/output/wiki_nces_matches.csv).

This is the "local heavy-lifting / write side": run it locally, commit the
output, and Vercel serves it from its CDN — the browser never queries a database
to render the map.

Output: web/public/data/schools.json
  [{ i: nces_id, n: name, s: state, c: county_fips, ci: city, a: address,
     z: zip, d: district, lv: level, e: enrollment, ph: phone,
     tf: teachers_fte, gl: lowest_grade, gh: highest_grade, ch: charter Y/N
     (public only), pv: 1 (private only), w: 0|1 (has_wikipedia),
     wt: matched Wikipedia article title (when w=1), x: lon, y: lat }, ...]
  gl/gh are blank when NCES has no grade span; nothing is guessed.
plus state_coverage.json and county_coverage.json aggregates.

Usage:
    python build_dataset.py            # NCES master + coordinates + flag + write
    python build_dataset.py --reflag   # only re-flag has_wikipedia from new matches
"""

import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data")
DEFAULT_MATCHES = os.path.join(DATA, "data_publish", "output", "wiki_nces_matches.csv")
DEFAULT_MASTER = os.path.join(DATA, "nces_crawl", "output_all_schools", "all_schools_master.csv")
DEFAULT_COORDS = os.path.join(DATA, "nces_crawl", "output_all_schools", "school_coordinates.csv")
OUT = os.path.join(HERE, "..", "web", "public", "data", "schools.json")

PSS_LEVEL = {"1": "elementary", "2": "high", "3": "combined", "-1": "other"}
# NCES grade-offered codes in numeric form: -1 PK, 0 K, 1-12, 13.
GRADE = {-1: "PK", 0: "K", 13: "13"}
_MASTER_GRADE = {"PK": -1, "KG": 0}


def _pad(i):
    """NCES ids are 12-digit, zero-padded. Normalize both sides of the join."""
    i = str(i)
    return i.zfill(12) if i.isdigit() else i


def load_matched_ids(path):
    """NCES school id -> matched Wikipedia article title, from the audited
    wiki<->NCES matcher output (columns `nces_school_id`, `wiki_title`)."""
    ids = {}
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sid = (r.get("nces_school_id") or "").strip()
            if sid:
                ids[_pad(sid)] = (r.get("wiki_title") or "").strip()
    return ids


def _enroll(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None



def _grade(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return ""
    if n in GRADE:
        return GRADE[n]
    return str(n) if 1 <= n <= 12 else ""


def _master_grade(code):
    """CCD grade code (PK, KG, 01-12, 13) -> the map's form (PK, K, 1-12, 13)."""
    code = (code or "").strip().upper()
    if code in _MASTER_GRADE:
        return _grade(_MASTER_GRADE[code])
    return _grade(code) if code.isdigit() else ""


def _span_level(lo, hi):
    """Map level from a public grade span (the bulk directory's own LEVEL isn't
    in the master): elementary <= 5, middle 6-8, high >= 9, else other."""
    order = {"PK": -1, "K": 0}
    try:
        a, b = order.get(lo, None), order.get(hi, None)
        a = int(lo) if a is None else a
        b = int(hi) if b is None else b
    except ValueError:
        return "other"
    if b <= 5:
        return "elementary"
    if a >= 6 and b <= 8:
        return "middle"
    if a >= 9:
        return "high"
    return "other"


def load_coords(path):
    """school_id -> (lat, lon, county_fips) from data/nces_crawl."""
    with open(path, newline="", encoding="utf-8") as f:
        return {r["school_id"]: (float(r["lat"]), float(r["lon"]), r["county_fips"])
                for r in csv.DictReader(f) if r["lat"] and r["lon"]}


_PSS_GRADES = [("PK", "PSS_ENROLL_PK"), ("K", "PSS_ENROLL_K")] + \
              [(str(g), f"PSS_ENROLL_{g}") for g in range(1, 13)]


def _phone(p):
    """PSS stores bare digits; show them like CCD does: (334)585-5100."""
    d = "".join(ch for ch in (p or "") if ch.isdigit())
    return f"({d[:3]}){d[3:6]}-{d[6:]}" if len(d) == 10 else (p or "").strip()


def _private_grades(r):
    """First/last grade with enrolled students — the PSS LoGrade/HiGrade codes
    are an undocumented numeric scheme (same rule as generate_article.py)."""
    present = [g for g, col in _PSS_GRADES if (_enroll(r.get(col)) or 0) > 0]
    return (present[0], present[-1]) if present else ("", "")


def rows_from_master(master_path, coords):
    """Compact map rows for every NCES school with coordinates.
    Returns (rows, n_nocoord)."""
    rows, n_nocoord = [], 0
    with open(master_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r["school_id"].strip()
            if sid not in coords:
                n_nocoord += 1
                continue
            lat, lon, county = coords[sid]
            row = {"i": sid, "n": r["school_name"].strip(), "s": r["state"].strip().upper(),
                   "c": county, "ci": r["city"].strip(), "a": r["address"].strip(),
                   "z": r["zip"].strip(), "e": _enroll(r.get("total_students"))}
            if r["sector"] == "public":
                gl, gh = _master_grade(r["low_grade"]), _master_grade(r["high_grade"])
                row.update({"d": r.get("District", ""), "lv": _span_level(gl, gh),
                            "ph": r.get("phone", ""), "tf": _enroll(r.get("teachers")),
                            "gl": gl, "gh": gh,
                            "ch": r.get("Charter", "") if r.get("Charter") in ("Yes", "No") else ""})
            else:
                gl, gh = _private_grades(r)
                row.update({"pv": 1, "d": "",
                            "lv": PSS_LEVEL.get(r.get("PSS_LEVEL", "").strip(), "other"),
                            "ph": _phone(r.get("phone", "")), "tf": _enroll(r.get("teachers")),
                            "gl": gl, "gh": gh})
            row.update({"w": 0, "x": round(lon, 5), "y": round(lat, 5)})
            rows.append(row)
    return rows, n_nocoord


def flag(rows, matched):
    """Set each row's `w` (has Wikipedia) and `wt` (the matched article title)
    from the matcher output; return the matched count."""
    n = 0
    for s in rows:
        title = matched.get(_pad(s["i"]))
        s["w"] = 1 if title is not None else 0
        if title:
            s["wt"] = title
        else:
            s.pop("wt", None)
        n += s["w"]
    return n


def write_outputs(out_path, rows):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, separators=(",", ":"), ensure_ascii=False)

    # By-state and by-county coverage for the zoomed-out choropleth (tiny files
    # the frontend loads first; the big point file loads lazily on zoom).
    def aggregate(key):
        agg = {}
        for s in rows:
            k = s[key]
            if not k:
                continue
            a = agg.setdefault(k, [0, 0])  # [total, has_wiki]
            a[0] += 1
            a[1] += s["w"]
        return agg

    outdir = os.path.dirname(out_path)
    state_agg = aggregate("s")
    county_agg = aggregate("c")
    with open(os.path.join(outdir, "state_coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(state_agg, fh, separators=(",", ":"))
    with open(os.path.join(outdir, "county_coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(county_agg, fh, separators=(",", ":"))
    return state_agg, county_agg


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--master", default=DEFAULT_MASTER)
    ap.add_argument("--coords", default=DEFAULT_COORDS)
    ap.add_argument("--matches", default=DEFAULT_MATCHES)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--reflag", action="store_true",
                    help="recompute has_wikipedia on the existing schools.json only")
    args = ap.parse_args()

    sys.stderr.write(f"Loading matched NCES ids from {args.matches}...\n")
    matched_ids = load_matched_ids(args.matches)
    sys.stderr.write(f"  {len(matched_ids):,} matched ids\n")

    if args.reflag:
        with open(args.out, encoding="utf-8") as fh:
            rows = json.load(fh)
        before = sum(s["w"] for s in rows)
        n_match = flag(rows, matched_ids)
        state_agg, county_agg = write_outputs(args.out, rows)
        sys.stderr.write(
            f"\nRe-flagged {len(rows):,} schools -> {args.out}\n"
            f"  has_wikipedia : {before:,} (old) -> {n_match:,} (new) "
            f"({100*n_match/max(len(rows),1):.1f}%)\n"
            f"  states={len(state_agg)} counties={len(county_agg)}\n"
        )
        return

    rows, n_nocoord = rows_from_master(args.master, load_coords(args.coords))
    n_match = flag(rows, matched_ids)
    state_agg, county_agg = write_outputs(args.out, rows)
    mb = os.path.getsize(args.out) / 1e6
    sys.stderr.write(
        f"\nDone. {len(rows):,} schools -> {args.out} ({mb:.1f} MB)\n"
        f"  public/private: {sum(not r.get('pv') for r in rows):,} / "
        f"{sum(bool(r.get('pv')) for r in rows):,}\n"
        f"  has_wikipedia : {n_match:,} ({100*n_match/max(len(rows),1):.1f}%)\n"
        f"  states={len(state_agg)}  counties={len(county_agg)}\n"
        f"  dropped (no coordinates): {n_nocoord}\n"
    )


if __name__ == "__main__":
    main()
