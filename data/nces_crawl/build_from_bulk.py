#!/usr/bin/env python3
"""Build the public-school master from NCES bulk data files (the default source).

Replaces the Selenium scrape of the CCD search tool for public schools: the bulk
files are versioned, download in minutes, and give one consistent school year
(the search tool mixes a preliminary next-year directory with prior-year counts).

Inputs (downloaded into bulk_downloads/ by --download, or placed there by hand):
  ccd_sch_029_<yy>  directory        ids, name, district, address, grades, status
  ccd_sch_052_<yy>  membership       total enrollment ("Education Unit Total")
  ccd_sch_059_<yy>  staff            teacher FTE
  ccd_sch_033_<yy>  lunch            free / reduced-price / direct certification
  EDGE_GEOCODE_PUBLICSCH_<yy>        county, locale, latitude/longitude
  pss<yy>_pu_csv                     private-school coordinates (PSS public-use file)

Outputs:
  output_public_schools/public_schools_master.csv
      same 26 columns as the scraper's export; only schools operating in the
      year (status Open/New/Added/Changed Boundary/Agency/Reopened); numbers as
      plain values, blank when NCES reports missing/not applicable
  output_all_schools/school_coordinates.csv
      school_id, lat, lon, county_fips, source — public (EDGE) and private (PSS)
      schools; used by the website map, the Wikipedia matcher's geo tier and
      enrich's state inference

Private schools still come from the PSS search export (download_schools.py
--type private, ~5 min): the PSS public-use file uses questionnaire item codes,
and the export already carries the decoded fields the article generator uses.

Usage:
    python build_from_bulk.py --download      # fetch the files, then build
    python build_from_bulk.py                 # build from bulk_downloads/
    python combine_all_schools.py             # then rebuild the unified master
"""

import argparse
import csv
import glob
import os
import subprocess
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BULK = os.path.join(HERE, "bulk_downloads")
PUBLIC_OUT = os.path.join(HERE, "output_public_schools", "public_schools_master.csv")
COORDS_OUT = os.path.join(HERE, "output_all_schools", "school_coordinates.csv")

# The release to build. Update these together when NCES publishes a new year
# (file names come from https://nces.ed.gov/ccd/files.asp).
YEAR = "2425"
FILES = {
    "directory": "https://nces.ed.gov/ccd/Data/zip/ccd_sch_029_2425_w_1a_073025.zip",
    "membership": "https://nces.ed.gov/ccd/Data/zip/ccd_sch_052_2425_l_1a_073025.zip",
    "staff": "https://nces.ed.gov/ccd/Data/zip/ccd_sch_059_2425_l_1a_073025.zip",
    "lunch": "https://nces.ed.gov/ccd/Data/zip/ccd_sch_033_2425_l_2a_073025.zip",
    "edge_public": "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_2425.zip",
    "pss": "https://nces.ed.gov/surveys/pss/zip/pss2324_pu_csv.zip",
}

PUBLIC_COLUMNS = [
    "NCES School ID", "State School ID", "NCES District ID", "State District ID",
    "Low Grade", "High Grade", "School Name", "District", "County Name",
    "Street Address", "City", "State", "ZIP", "ZIP 4-digit", "Phone", "Locale Code",
    "Locale", "Charter", "Students", "Teachers", "Student Teacher Ratio",
    "Free Lunch", "Reduced Lunch", "Directly Certified", "Type", "Status",
]
OPERATING = {"Open", "New", "Added", "Changed Boundary/Agency", "Reopened"}
TYPE_LABEL = {"Regular School": "Regular", "Special Education School": "Special Education",
              "Career and Technical School": "Vocational",
              "Alternative School": "Other/Alternative"}
LOCALE_LABEL = {
    "11": "City, Large", "12": "City, Midsize", "13": "City, Small",
    "21": "Suburban, Large", "22": "Suburban, Midsize", "23": "Suburban, Small",
    "31": "Town, Fringe", "32": "Town, Distant", "33": "Town, Remote",
    "41": "Rural, Fringe", "42": "Rural, Distant", "43": "Rural, Remote",
}
# EDGE geocode TXT has no header row; this is its documented column order.
EDGE_COLUMNS = ["NCESSCH", "LEAID", "NAME", "OPSTFIPS", "STREET", "CITY", "STATE",
                "ZIP", "STFIP", "CNTY", "NMCNTY", "LOCALE", "LAT", "LON", "CBSA",
                "NMCBSA", "CBSATYPE", "CSA", "NMCSA", "CD", "SLDL", "SLDU", "SCHOOLYEAR"]


def download():
    os.makedirs(BULK, exist_ok=True)
    for name, url in FILES.items():
        dest = os.path.join(BULK, os.path.basename(url))
        if os.path.exists(dest):
            print(f"  have {os.path.basename(dest)}")
            continue
        print(f"  downloading {name}: {url}")
        urllib.request.urlretrieve(url, dest + ".part")
        os.replace(dest + ".part", dest)


def _zip_reader(url, suffix=".csv", delimiter=",", fieldnames=None):
    """Stream rows of the first `suffix` member of a downloaded zip.

    Some NCES zips (the 190 MB membership file) use Deflate64, which Python's
    zipfile can't read, so members are extracted with the system `unzip` into
    bulk_downloads/<zip name>/ and read from there."""
    path = os.path.join(BULK, os.path.basename(url))
    if not os.path.exists(path):
        sys.exit(f"missing {path} — run with --download")
    outdir = path[:-len(".zip")]
    found = glob.glob(os.path.join(outdir, "*" + suffix)) + \
        glob.glob(os.path.join(outdir, "*" + suffix.lower()))
    if not found:
        subprocess.run(["unzip", "-oq", path, "-d", outdir], check=True)
        found = glob.glob(os.path.join(outdir, "*" + suffix)) + \
            glob.glob(os.path.join(outdir, "*" + suffix.lower()))
    fh = open(found[0], encoding="utf-8", newline="")   # EDGE has UTF-8 names (PR)
    return csv.DictReader(fh, delimiter=delimiter, fieldnames=fieldnames)


def _num(v):
    """NCES counts -> plain number string; '' for missing/not-applicable codes."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if f < 0:                      # -1 missing, -2 not applicable, -9 suppressed
        return ""
    return str(int(f)) if f == int(f) else f"{f:.2f}"


def build_public():
    members = {r["NCESSCH"]: r["STUDENT_COUNT"]
               for r in _zip_reader(FILES["membership"])
               if r["TOTAL_INDICATOR"] == "Education Unit Total"}
    teachers = {r["NCESSCH"]: r["TEACHERS"] for r in _zip_reader(FILES["staff"])
                if r["TOTAL_INDICATOR"] == "Education Unit Total"}
    lunch = defaultdict(dict)
    for r in _zip_reader(FILES["lunch"]):
        prog = r["LUNCH_PROGRAM"]
        if r["DATA_GROUP"] == "Direct Certification":
            lunch[r["NCESSCH"]]["direct"] = r["STUDENT_COUNT"]
        elif prog == "Free lunch qualified":
            lunch[r["NCESSCH"]]["free"] = r["STUDENT_COUNT"]
        elif prog == "Reduced-price lunch qualified":
            lunch[r["NCESSCH"]]["reduced"] = r["STUDENT_COUNT"]
    edge = {r["NCESSCH"]: r for r in
            _zip_reader(FILES["edge_public"], ".TXT", "|", EDGE_COLUMNS)}

    rows, coords, skipped = [], [], defaultdict(int)
    for d in _zip_reader(FILES["directory"]):
        if d["SY_STATUS_TEXT"] not in OPERATING:
            skipped[d["SY_STATUS_TEXT"]] += 1
            continue
        sid, g = d["NCESSCH"], edge.get(d["NCESSCH"], {})
        students, fte = _num(members.get(sid)), _num(teachers.get(sid))
        ratio = (f"{float(students) / float(fte):.2f}"
                 if students and fte and float(fte) > 0 else "")
        locale = (g.get("LOCALE") or "").strip()
        charter = d["CHARTER_TEXT"] if d["CHARTER_TEXT"] in ("Yes", "No") else ""
        rows.append({
            "NCES School ID": sid, "State School ID": d["ST_SCHID"],
            "NCES District ID": d["LEAID"], "State District ID": d["ST_LEAID"],
            "Low Grade": d["GSLO"] if d["GSLO"] not in ("N", "M") else "",
            "High Grade": d["GSHI"] if d["GSHI"] not in ("N", "M") else "",
            "School Name": d["SCH_NAME"], "District": d["LEA_NAME"],
            "County Name": g.get("NMCNTY", ""), "Street Address": d["LSTREET1"],
            # Location state: CCD files Bureau of Indian Education schools under
            # ST = "BI"; LSTATE is where the school physically is.
            "City": d["LCITY"], "State": d["LSTATE"] or d["ST"], "ZIP": d["LZIP"],
            "ZIP 4-digit": d["LZIP4"], "Phone": d["PHONE"],
            "Locale Code": locale, "Locale": LOCALE_LABEL.get(locale, ""),
            "Charter": charter, "Students": students, "Teachers": fte,
            "Student Teacher Ratio": ratio,
            "Free Lunch": _num(lunch[sid].get("free")),
            "Reduced Lunch": _num(lunch[sid].get("reduced")),
            "Directly Certified": _num(lunch[sid].get("direct")),
            "Type": TYPE_LABEL.get(d["SCH_TYPE_TEXT"], d["SCH_TYPE_TEXT"]),
            "Status": d["SY_STATUS_TEXT"],
        })
        if g.get("LAT") and g.get("LON"):
            coords.append((sid, g["LAT"], g["LON"], g.get("CNTY", ""), f"EDGE public {YEAR}"))

    os.makedirs(os.path.dirname(PUBLIC_OUT), exist_ok=True)
    with open(PUBLIC_OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PUBLIC_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"public: {len(rows):,} operating schools -> {PUBLIC_OUT}")
    print(f"  skipped by status: {dict(skipped)}")
    print(f"  with enrollment {sum(bool(r['Students']) for r in rows):,}, "
          f"teachers {sum(bool(r['Teachers']) for r in rows):,}, "
          f"county {sum(bool(r['County Name']) for r in rows):,}")
    return coords


def private_coords():
    return [(r["PPIN"], r["LATITUDE24"], r["LONGITUDE24"],
             (r["PSTANSI"] + r["PCNTY"]) if r.get("PSTANSI") and r.get("PCNTY") else "",
             "PSS public-use 2324")
            for r in _zip_reader(FILES["pss"])
            if r.get("LATITUDE24") and r.get("LONGITUDE24")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--download", action="store_true", help="fetch missing bulk files first")
    args = ap.parse_args()
    if args.download:
        download()
    coords = build_public() + private_coords()
    os.makedirs(os.path.dirname(COORDS_OUT), exist_ok=True)
    with open(COORDS_OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["school_id", "lat", "lon", "county_fips", "source"])
        w.writerows(sorted(coords))
    print(f"coordinates: {len(coords):,} schools -> {COORDS_OUT}")


if __name__ == "__main__":
    main()
