#!/usr/bin/env python3
"""Geocode the NCES private (PSS) schools so they can be placed on the map.

The NCES private master has full mailing addresses but no coordinates, and the
Urban API / PSS does not expose private-school lat/lon. We resolve them with the
free U.S. Census Bureau batch geocoder (no key), which also returns the county
FIPS used by the county choropleth.

Reads:  ../../data/nces_crawl/output_all_schools/all_schools_master.csv  (sector=private)
Writes: ../data/private_geocoded.csv
        columns: school_id, lat, lon, county_fips, match

Resumable: already-geocoded school_ids in the output are skipped on re-run.

Usage:
    python geocode_private.py
    python geocode_private.py --batch 5000
"""

import argparse
import csv
import io
import os
import sys
import time

import requests

HERE = os.path.dirname(__file__)
MASTER = os.path.join(HERE, "..", "..", "data", "nces_crawl", "output_all_schools",
                      "all_schools_master.csv")
OUT = os.path.join(HERE, "..", "data", "private_geocoded.csv")
GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
FIELDS = ["school_id", "lat", "lon", "county_fips", "match"]


def load_private(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r["sector"] != "private":
                continue
            rows.append({
                "id": r["school_id"].strip(),
                "street": r["address"].strip(),
                "city": r["city"].strip(),
                "state": r["state"].strip(),
                "zip": r["zip"].strip(),
            })
    return rows


def load_done(path):
    done = {}
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            done[r["school_id"]] = r
    return done


def geocode_batch(session, batch):
    """POST one batch (<=10k) to the Census geocoder; yield (id,lat,lon,fips,match)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    for s in batch:
        w.writerow([s["id"], s["street"], s["city"], s["state"], s["zip"]])
    files = {"addressFile": ("addr.csv", buf.getvalue(), "text/csv")}
    data = {"benchmark": "Public_AR_Current", "vintage": "Current_Current"}

    backoff = 5
    for attempt in range(4):
        try:
            resp = session.post(GEOCODER, files=files, data=data, timeout=600)
            resp.raise_for_status()
            text = resp.text
            break
        except requests.RequestException as exc:
            if attempt == 3:
                raise
            sys.stderr.write(f"  ! batch failed ({exc}); retry in {backoff}s\n")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
    else:  # pragma: no cover
        return

    out = []
    for row in csv.reader(io.StringIO(text)):
        # id, input, matchIndicator, matchType, matchedAddr, "lon,lat",
        # tigerId, side, stateFP, countyFP, tract, block
        if not row:
            continue
        sid = row[0]
        match = row[2] if len(row) > 2 else "No_Match"
        if match == "Match" and len(row) >= 10 and row[5]:
            try:
                lon, lat = row[5].split(",")
                fips = (row[8] or "").zfill(2) + (row[9] or "").zfill(3)  # state+county
                out.append((sid, lat.strip(), lon.strip(), fips, "Match"))
                continue
            except (ValueError, IndexError):
                pass
        out.append((sid, "", "", "", match))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--batch", type=int, default=5000, help="rows per request (max 10000)")
    args = ap.parse_args()

    private = load_private(args.master)
    done = load_done(args.out)
    todo = [s for s in private if s["id"] not in done]
    sys.stderr.write(f"private schools: {len(private):,} | already done: {len(done):,} | "
                     f"to geocode: {len(todo):,}\n")
    if not todo:
        sys.stderr.write("nothing to do.\n")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "SchoolData/1.0 (boxuan.shan@gmail.com)"})

    # open output in append mode (write header if new)
    new_file = not os.path.exists(args.out)
    fh = open(args.out, "a", newline="", encoding="utf-8")
    w = csv.writer(fh)
    if new_file:
        w.writerow(FIELDS)

    matched = 0
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        t0 = time.time()
        results = geocode_batch(session, chunk)
        for sid, lat, lon, fips, m in results:
            w.writerow([sid, lat, lon, fips, m])
            matched += 1 if m == "Match" else 0
        fh.flush()
        sys.stderr.write(
            f"  batch {i//args.batch + 1}: {min(i+args.batch, len(todo)):,}/{len(todo):,} "
            f"sent, matched so far={matched:,}  ({time.time()-t0:.0f}s)\n")
    fh.close()
    sys.stderr.write(f"\nDone. {matched:,} geocoded -> {args.out}\n")


if __name__ == "__main__":
    main()
