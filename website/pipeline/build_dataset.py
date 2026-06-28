#!/usr/bin/env python3
"""Build the static map dataset for SchoolData.

Pulls the full NCES public-school directory (lat/lon for ~102k schools) from the
Urban Institute Education Data API, flags which schools already have an English
Wikipedia article by matching against the local crawl (../../schools.csv), and
writes a compact JSON the Next.js/Deck.gl frontend loads as a static asset.

This is the "local heavy-lifting / write side" of the architecture: run it
locally, commit the output, and Vercel serves it from its CDN — the browser
never queries a database to render the map.

Output: schooldata-web/public/data/schools.json
  [{ i: ncessch, n: name, s: state, lv: level, e: enrollment,
     w: 0|1 (has_wikipedia), x: lon, y: lat }, ...]

Usage:
    python build_dataset.py                 # full pull
    python build_dataset.py --year 2021
    python build_dataset.py --wiki ../../schools.csv --proxy http://127.0.0.1:7890
"""

import argparse
import json
import os
import re
import sys
import time

import requests

NCES_API = "https://educationdata.urban.org/api/v1/schools/ccd/directory/{year}/"
DEFAULT_WIKI = os.path.join(os.path.dirname(__file__), "..", "data", "schools.csv")
OUT = os.path.join(os.path.dirname(__file__), "..", "web", "public", "data", "schools.json")

LEVEL = {"1": "elementary", "2": "middle", "3": "high", "4": "other"}

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "District of Columbia": "DC",
}
_STATES_BY_LEN = sorted(STATE_ABBR, key=len, reverse=True)

_STOP = {"school", "schools", "high", "elementary", "middle", "junior",
         "senior", "the", "of", "academy", "center", "centre"}


def norm_name(title):
    """Normalize a school name for fuzzy cross-source matching."""
    title = re.sub(r"\(.*?\)", " ", title)          # drop parentheticals
    title = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    toks = [t for t in title.split() if t and t not in _STOP]
    return " ".join(sorted(toks))                   # order-independent key


def load_wiki_index(path):
    """Return a set of (state_abbr, normalized_name) for Wikipedia schools."""
    import csv
    idx = set()
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            text = r.get("source_category", "") + " " + r.get("title", "")
            st = next((s for s in _STATES_BY_LEN if s in text), None)
            if not st:
                continue
            idx.add((STATE_ABBR[st], norm_name(r["title"])))
    return idx


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2021")
    ap.add_argument("--wiki", default=DEFAULT_WIKI)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--proxy", default=None)
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": "SchoolData/1.0 (boxuan.shan@gmail.com)"})
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})

    sys.stderr.write("Loading Wikipedia index...\n")
    wiki = load_wiki_index(args.wiki)
    sys.stderr.write(f"  {len(wiki)} (state, name) keys from {args.wiki}\n")

    sys.stderr.write(f"Fetching NCES {args.year} directory...\n")
    rows = fetch_nces(session, args.year, args.delay)

    out, matched, skipped = [], 0, 0
    for r in rows:
        lat, lon = r.get("latitude"), r.get("longitude")
        if lat in (None, 0) or lon in (None, 0):
            skipped += 1
            continue
        st = r.get("state_location") or ""
        cty = (r.get("county_code") or "").zfill(5)  # 5-digit county FIPS
        has = 1 if (st, norm_name(r.get("school_name", ""))) in wiki else 0
        matched += has
        out.append({
            "i": r.get("ncessch"),
            "n": r.get("school_name"),
            "s": st,
            "c": cty,
            "ci": r.get("city_location") or "",
            "a": r.get("street_location") or "",      # street address
            "z": str(r.get("zip_location") or ""),     # ZIP
            "d": r.get("lea_name") or "",              # school district
            "lv": LEVEL.get(str(r.get("school_level")), "other"),
            "e": r.get("enrollment") if isinstance(r.get("enrollment"), int) else None,
            "w": has,
            "x": round(lon, 5),
            "y": round(lat, 5),
        })

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)

    # Aggregate coverage by state and by county for the zoomed-out choropleth.
    # Tiny files the frontend loads first; the 12 MB point file loads lazily
    # only once the user zooms into a region.
    def aggregate(key):
        agg = {}
        for s in out:
            k = s[key]
            if not k:
                continue
            a = agg.setdefault(k, [0, 0])  # [total, has_wiki]
            a[0] += 1
            a[1] += s["w"]
        return agg

    outdir = os.path.dirname(args.out)
    state_agg = aggregate("s")
    county_agg = aggregate("c")
    with open(os.path.join(outdir, "state_coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(state_agg, fh, separators=(",", ":"))
    with open(os.path.join(outdir, "county_coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(county_agg, fh, separators=(",", ":"))

    mb = os.path.getsize(args.out) / 1e6
    sys.stderr.write(
        f"\nDone. {len(out)} schools -> {args.out} ({mb:.1f} MB)\n"
        f"  has_wikipedia : {matched} ({100*matched/max(len(out),1):.1f}%)\n"
        f"  states={len(state_agg)}  counties={len(county_agg)}\n"
        f"  dropped (no geo): {skipped}\n"
    )


if __name__ == "__main__":
    main()
