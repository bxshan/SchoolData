#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Fetch California Department of Education directory fields for fact sheets.

The CDE school directory pages (sd.cde.ca.gov) sit behind a bot challenge, but
CDE publishes the same directory as an open GIS layer, "California Public
Schools", keyed by the federal (NCES) school id. This script queries that layer
for every research/<nces_id>.json that is a California public school and caches
the fields a fact sheet uses:

  CDSCode, SchoolName, Status, OpenDate (YYYY-MM-DD), GradeLow, GradeHigh,
  Charter, Magnet, Website, Year (directory year)

Output: cde_directory.json  { nces_id: {...fields} }   (re-run to refresh)

The OpenDate is an administrative record date and is shown on a sheet only as
"state directory open date"; the Website is what the state directory lists,
which may be outdated (build_sheets.py flags that).

Usage:
    python fetch_cde.py [--layer SchoolSites2526]
"""

import argparse
import datetime
import glob
import json
import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.join(HERE, "research")
OUT = os.path.join(HERE, "cde_directory.json")

SERVICE = "https://services3.arcgis.com/fdvHcZVgB2QSRNkL/arcgis/rest/services/{layer}/FeatureServer/0/query"
FIELDS = ["FedID", "CDSCode", "SchoolName", "Status", "OpenDate", "GradeLow", "GradeHigh",
          "Charter", "Magnet", "Website", "Year"]
USER_AGENT = ("SchoolDataBot/1.0 (https://github.com/bxshan/SchoolData; "
              "contact: boxuan.shan@gmail.com) python-requests")


def query(session, layer, ids):
    where = "FedID IN (" + ",".join(f"'{i}'" for i in ids) + ")"
    resp = session.get(SERVICE.format(layer=layer), timeout=60,
                       params={"where": where, "outFields": ",".join(FIELDS), "f": "json"})
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"CDE layer error: {data['error']}")
    out = {}
    for feat in data.get("features", []):
        a = feat["attributes"]
        if a.get("OpenDate"):
            a["OpenDate"] = datetime.datetime.fromtimestamp(
                a["OpenDate"] / 1000, datetime.timezone.utc).date().isoformat()
        out[a.pop("FedID")] = a
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layer", default="SchoolSites2526",
                    help="CDE GIS layer name (one per school year)")
    args = ap.parse_args()

    ids = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(RESEARCH, "*.json")))
    ca = [i for i in ids if i.startswith("06")]  # NCES ids start with the state FIPS code
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    found = {}
    for start in range(0, len(ca), 50):
        found.update(query(session, args.layer, ca[start:start + 50]))

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(found, fh, indent=1, ensure_ascii=False, sort_keys=True)
    missing = [i for i in ca if i not in found]
    sys.stderr.write(f"{len(found)}/{len(ca)} California schools -> {OUT}\n")
    for i in missing:
        sys.stderr.write(f"  not in the CDE layer: {i}\n")


if __name__ == "__main__":
    main()
