#!/usr/bin/env python3
"""Build the static map dataset for SchoolData.

Pulls the full NCES public-school directory (lat/lon for ~102k schools) from the
Urban Institute Education Data API, flags which schools already have an English
Wikipedia article, and writes a compact JSON the Next.js/Deck.gl frontend loads
as a static asset.

`has_wikipedia` is an EXACT join on the NCES school id (`ncessch`) against
`data/wiki_nces_matches.csv` — the audited Wikipedia<->NCES matcher output
(exact Wikidata nces_id + name+state + high-confidence fuzzy). This replaces the
old naive name+state matching (which over-counted via shared generic words).

This is the "local heavy-lifting / write side": run it locally, commit the
output, and Vercel serves it from its CDN — the browser never queries a database
to render the map.

Output: web/public/data/schools.json
  [{ i: ncessch, n: name, s: state, c: county_fips, ci: city, a: address,
     z: zip, d: district, lv: level, e: enrollment, ph: phone,
     tf: teachers_fte, gl: lowest_grade, gh: highest_grade, ch: charter Y/N,
     mg: magnet Y/N, w: 0|1 (has_wikipedia), x: lon, y: lat }, ...]
  (ph/tf/gl/gh/ch/mg are public-school only; NCES PSS omits them for private.)
plus state_coverage.json and county_coverage.json aggregates.

Usage:
    python build_dataset.py                 # full Urban API pull + flag + write
    python build_dataset.py --reflag        # re-flag existing schools.json (no API)
    python build_dataset.py --year 2021 --matches ../data/wiki_nces_matches.csv
"""

import argparse
import csv
import json
import os
import sys
import time

import requests

NCES_API = "https://educationdata.urban.org/api/v1/schools/ccd/directory/{year}/"
HERE = os.path.dirname(__file__)
DEFAULT_MATCHES = os.path.join(HERE, "..", "data", "wiki_nces_matches.csv")
OUT = os.path.join(HERE, "..", "web", "public", "data", "schools.json")

LEVEL = {"1": "elementary", "2": "middle", "3": "high", "4": "other"}


def _pad(i):
    """NCES ids are 12-digit, zero-padded. Normalize both sides of the join."""
    i = str(i)
    return i.zfill(12) if i.isdigit() else i


def load_matched_ids(path):
    """Set of NCES school ids that have a Wikipedia article, from the audited
    wiki<->NCES matcher output (column `nces_school_id`)."""
    ids = set()
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sid = (r.get("nces_school_id") or "").strip()
            if sid:
                ids.add(_pad(sid))
    return ids


STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "AS": "60", "GU": "66", "MP": "69",
    "PR": "72", "VI": "78",
}
PSS_LEVEL = {"1": "elementary", "2": "high", "3": "combined", "-1": "other"}


def _enroll(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# NCES grade-offered codes (Urban API numeric form): -1 PK, 0 K, 1-12, 13.
GRADE = {-1: "PK", 0: "K", 13: "13"}


def _grade(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return ""
    if n in GRADE:
        return GRADE[n]
    return str(n) if 1 <= n <= 12 else ""


def _yesno(v):
    """NCES coded flag: 1=Yes, 2=No, negatives=missing/NA."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return ""
    return "Yes" if n == 1 else ("No" if n == 2 else "")


def load_private_master(path):
    """NCES private (PSS) school records needed to build map rows."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r["sector"] != "private":
                continue
            st = r["state"].strip().upper()
            cfips = r.get("PSS_COUNTY_FIPS", "").strip()
            county = (STATE_FIPS.get(st, "") + cfips.zfill(3)) if cfips and st in STATE_FIPS else ""
            out.append({
                "i": r["school_id"].strip(),
                "n": r["school_name"].strip(),
                "s": st,
                "c": county,
                "ci": r["city"].strip(),
                "a": r["address"].strip(),
                "z": r["zip"].strip(),
                "d": "",                       # private schools have no LEA/district
                "lv": PSS_LEVEL.get(r.get("PSS_LEVEL", "").strip(), "other"),
                "e": _enroll(r.get("total_students")),
            })
    return out


def load_geocode(path):
    """school_id -> (lat, lon) for Census-matched private schools."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("match") == "Match" and r.get("lat") and r.get("lon"):
                out[r["school_id"]] = (float(r["lat"]), float(r["lon"]))
    return out


def load_wiki_coords(matches_path, enriched_path):
    """nces_school_id -> (lat, lon) from the matched Wikipedia article (Wikidata
    coords). Fallback coordinate source for private schools Census can't match."""
    pid_coord = {}
    with open(enriched_path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("lat") and r.get("lon"):
                pid_coord[r["pageid"]] = (float(r["lat"]), float(r["lon"]))
    out = {}
    with open(matches_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r["nces_school_id"]
            coord = pid_coord.get(r["wiki_pageid"])
            if sid and coord and sid not in out:
                out[sid] = coord
    return out


def build_private_rows(master, geocode, wiki_coords, matched_ids):
    """Compact map rows for private schools that have coordinates (Census match,
    else Wikidata fallback). Returns (rows, n_census, n_wiki, n_nocoord)."""
    rows, n_census, n_wiki, n_nocoord = [], 0, 0, 0
    for m in master:
        sid = m["i"]
        coord = geocode.get(sid)
        if coord:
            n_census += 1
        else:
            coord = wiki_coords.get(_pad(sid)) or wiki_coords.get(sid)
            if coord:
                n_wiki += 1
            else:
                n_nocoord += 1
                continue
        lat, lon = coord
        row = dict(m)
        row["w"] = 1 if _pad(sid) in matched_ids else 0
        row["x"] = round(lon, 5)
        row["y"] = round(lat, 5)
        rows.append(row)
    return rows, n_census, n_wiki, n_nocoord


def fetch_nces(session, year, delay):
    url = NCES_API.format(year=year)
    page, out = 1, []
    while True:
        for attempt in range(6):
            try:
                d = session.get(url, params={"page": page}, timeout=90).json()
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt == 5:
                    raise
                sys.stderr.write(f"  ! page {page} retry ({exc})\n")
                time.sleep(2 ** attempt)
        out.extend(d.get("results", []))
        sys.stderr.write(f"  fetched page {page}: {len(out)}/{d.get('count')}\n")
        if not d.get("next"):
            break
        page += 1
        time.sleep(delay)
    return out


def nces_to_row(r):
    """Urban API record -> compact schools.json row (`w` filled by flag()).
    Returns None when the school has no usable coordinates."""
    lat, lon = r.get("latitude"), r.get("longitude")
    if lat in (None, 0) or lon in (None, 0):
        return None
    return {
        "i": r.get("ncessch"),
        "n": r.get("school_name"),
        "s": r.get("state_location") or "",
        "c": (r.get("county_code") or "").zfill(5),
        "ci": r.get("city_location") or "",
        "a": r.get("street_location") or "",
        "z": str(r.get("zip_location") or ""),
        "d": r.get("lea_name") or "",
        "lv": LEVEL.get(str(r.get("school_level")), "other"),
        "e": r.get("enrollment") if isinstance(r.get("enrollment"), int) else None,
        "ph": r.get("phone") or "",               # school phone
        "tf": _enroll(r.get("teachers_fte")),     # teaching staff (FTE) -> ratio
        "gl": _grade(r.get("lowest_grade_offered")),
        "gh": _grade(r.get("highest_grade_offered")),
        "ch": _yesno(r.get("charter")),
        "mg": _yesno(r.get("magnet")),
        "w": 0,
        "x": round(lon, 5),
        "y": round(lat, 5),
    }


def flag(rows, matched_ids):
    """Set each row's `w` from the matched-id set; return the matched count."""
    matched = 0
    for s in rows:
        s["w"] = 1 if _pad(s["i"]) in matched_ids else 0
        matched += s["w"]
    return matched


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2021")
    ap.add_argument("--matches", default=DEFAULT_MATCHES)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--reflag", action="store_true",
                    help="recompute has_wikipedia on the existing schools.json "
                         "(no Urban API pull)")
    ap.add_argument("--add-private", action="store_true",
                    help="merge geocoded NCES private schools into the existing "
                         "schools.json (needs private_geocoded.csv)")
    ap.add_argument("--master", default=os.path.join(HERE, "..", "..", "data", "nces_crawl",
                    "output_all_schools", "all_schools_master.csv"))
    ap.add_argument("--geocode", default=os.path.join(HERE, "..", "data", "private_geocoded.csv"))
    ap.add_argument("--enriched", default=os.path.join(HERE, "..", "data", "schools_enriched.csv"))
    args = ap.parse_args()

    sys.stderr.write(f"Loading matched NCES ids from {args.matches}...\n")
    matched_ids = load_matched_ids(args.matches)
    sys.stderr.write(f"  {len(matched_ids):,} matched ids\n")

    if args.reflag:
        sys.stderr.write(f"Re-flagging existing {args.out} (no API pull)...\n")
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

    if args.add_private:
        sys.stderr.write("Adding geocoded NCES private schools...\n")
        with open(args.out, encoding="utf-8") as fh:
            existing = json.load(fh)
        master = load_private_master(args.master)
        private_ppins = {m["i"] for m in master}
        # keep public rows only (idempotent: drop any previously-added private)
        public = [r for r in existing if str(r["i"]) not in private_ppins]
        geocode = load_geocode(args.geocode)
        wiki_coords = load_wiki_coords(args.matches, args.enriched)
        priv_rows, n_census, n_wiki, n_nocoord = build_private_rows(
            master, geocode, wiki_coords, matched_ids)
        rows = public + priv_rows
        state_agg, county_agg = write_outputs(args.out, rows)
        n_match = sum(r["w"] for r in priv_rows)
        sys.stderr.write(
            f"\nMerged private schools -> {args.out}\n"
            f"  public rows kept      : {len(public):,}\n"
            f"  private added         : {len(priv_rows):,} of {len(master):,}\n"
            f"    coords via Census   : {n_census:,}\n"
            f"    coords via Wikidata : {n_wiki:,}\n"
            f"    dropped (no coords) : {n_nocoord:,}\n"
            f"  private w/ wikipedia  : {n_match:,}\n"
            f"  total rows            : {len(rows):,}\n"
            f"  states={len(state_agg)} counties={len(county_agg)}\n"
        )
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "SchoolData/1.0 (boxuan.shan@gmail.com)"})
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})

    sys.stderr.write(f"Fetching NCES {args.year} directory...\n")
    raw = fetch_nces(session, args.year, args.delay)
    rows, skipped = [], 0
    for r in raw:
        row = nces_to_row(r)
        if row is None:
            skipped += 1
        else:
            rows.append(row)

    n_match = flag(rows, matched_ids)
    state_agg, county_agg = write_outputs(args.out, rows)
    mb = os.path.getsize(args.out) / 1e6
    sys.stderr.write(
        f"\nDone. {len(rows):,} schools -> {args.out} ({mb:.1f} MB)\n"
        f"  has_wikipedia : {n_match:,} ({100*n_match/max(len(rows),1):.1f}%)\n"
        f"  states={len(state_agg)}  counties={len(county_agg)}\n"
        f"  dropped (no geo): {skipped}\n"
    )


if __name__ == "__main__":
    main()
