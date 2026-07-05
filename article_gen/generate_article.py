#!/usr/bin/env python3
"""Deterministically render a Wikipedia-style plaintext article for a US K-12
school using ALL available NCES metadata.

Reads the full 85-column NCES master (nces_crawl/all_schools_output/
all_schools_master.csv) — not the trimmed schools.json — so it can use every
descriptive field: location + county, locale, school type, grade range, district,
enrollment, staffing and ratio, Title I (free/reduced lunch) for public schools,
and for private (PSS) schools the religious affiliation, coeducational status,
racial composition, library, session length, and association memberships.

Pure function of the record — identical input yields identical output (no model,
no randomness). Every clause is optional: the article stays coherent for any
subset of fields. Codes that cannot be decoded confidently (PSS_ORIENT
denomination, PSS_COMM_TYPE) are omitted rather than guessed.

Usage:
    python generate_article.py --id 010135002667
    python generate_article.py --name "A C Moore Primary School"
    python generate_article.py --demo
"""

import argparse
import csv
import os
import re

HERE = os.path.dirname(__file__)
MASTER = os.path.join(HERE, "..", "nces_crawl", "all_schools_output",
                      "all_schools_master.csv")

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "the District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
    "GU": "Guam", "AS": "American Samoa", "MP": "the Northern Mariana Islands",
    "VI": "the U.S. Virgin Islands",
}

# Public CCD `type` labels -> adjective for the lead ("Regular" carries no word).
PUB_TYPE_ADJ = {"Regular": "", "Other/Alternative": "alternative ",
                "Special Education": "special-education ", "Vocational": "vocational "}
# Public CCD `Locale` labels -> a natural setting phrase.
PUB_LOCALE = {
    "City, Large": "a large city", "City, Midsize": "a midsize city",
    "City, Small": "a small city", "Suburban, Large": "a large suburb",
    "Suburban, Midsize": "a midsize suburb", "Suburban, Small": "a small suburb",
    "Town, Fringe": "a town on the urban fringe", "Town, Distant": "a distant town",
    "Town, Remote": "a remote town", "Rural, Fringe": "a rural area near a city",
    "Rural, Distant": "a distant rural area", "Rural, Remote": "a remote rural area",
}
# NCES 12-category locale codes (used by PSS_LOCALE) -> same phrasing.
LOCALE_CODE = {
    "11": "a large city", "12": "a midsize city", "13": "a small city",
    "21": "a large suburb", "22": "a midsize suburb", "23": "a small suburb",
    "31": "a town on the urban fringe", "32": "a distant town", "33": "a remote town",
    "41": "a rural area near a city", "42": "a distant rural area", "43": "a remote rural area",
}
# PSS private-school codes (NCES Private School Survey codebook).
PSS_TYPE_ADJ = {"1": "", "2": "Montessori ", "3": "special-program ",
                "4": "special-education ", "5": "career and technical ",
                "6": "alternative ", "7": "early-childhood "}
PSS_RELIG = {"1": "Catholic", "2": "religiously affiliated", "3": "nonsectarian"}
PSS_COED = {"1": "coeducational", "2": "all-boys", "3": "all-girls"}
PSS_LEVEL_WORD = {"1": "elementary", "2": "secondary", "3": ""}  # 3=combined (grades carry it)

GRADE_ORDER = ["PK", "K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
PSS_ENROLL_COLS = [("PK", "PSS_ENROLL_PK"), ("K", "PSS_ENROLL_K")] + \
                  [(str(g), f"PSS_ENROLL_{g}") for g in range(1, 13)]
RACE_PCT = [("White", "PSS_WHITE_PCT"), ("Black", "PSS_BLACK_PCT"),
            ("Hispanic", "PSS_HISP_PCT"), ("Asian", "PSS_ASIAN_PCT"),
            ("American Indian", "PSS_INDIAN_PCT"),
            ("Pacific Islander", "PSS_PACISL_PCT"),
            ("two or more races", "PSS_TWOMORE_PCT")]


def _num(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _f1(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


_KEEP_UPPER = {"US", "USA", "DC", "II", "III", "IV", "JR", "SR",
               "ISD", "USD", "SD", "CSD", "ESD", "RSD", "UFSD", "CUSD", "ISD",
               "HS", "MS", "JSHS", "STEM", "STEAM", "NCEA", "YMCA", "MLK", "JFK",
               "ROTC", "AP", "IB"}


def _titlecase(s):
    """Title-case an ALL-CAPS string, keeping known acronyms uppercase. Single
    letters (initials like 'A C Moore') stay capitalized; two-letter words become
    'El'/'La'/'St'. No-op on already-mixed-case strings."""
    if not s or not s.isupper():
        return s
    out = []
    for w in s.split():
        core = w.strip(".,")
        out.append(w if core in _KEEP_UPPER else w.capitalize())
    return " ".join(out)


def _grade(code):
    """Normalize a public CCD grade code: '01'->'1', 'KG'->'K', 'PK'->'PK'."""
    c = (code or "").strip().upper()
    if c in ("KG", "K"):
        return "K"
    if c == "PK":
        return "PK"
    c = c.lstrip("0")
    return c


def _public_grades(r):
    lo, hi = _grade(r.get("low_grade")), _grade(r.get("high_grade"))
    return (lo, hi) if lo and hi else ("", "")


def _private_grades(r):
    present = [label for label, col in PSS_ENROLL_COLS if _num(r.get(col))]
    return (present[0], present[-1]) if present else ("", "")


def _level_word(lo, hi):
    """Coarse level word from a normalized grade span."""
    idx = {g: i for i, g in enumerate(GRADE_ORDER)}
    li, hi_i = idx.get(lo), idx.get(hi)
    if li is None or hi_i is None:
        return ""
    if hi_i <= idx["5"]:
        return "elementary "
    if hi_i <= idx["8"] and li >= idx["4"]:
        return "middle "
    if hi_i >= idx["9"] and li >= idx["7"]:
        return "high "
    return ""  # combined / mixed — the grade range conveys it


def _state(r):
    return STATE_NAMES.get(r.get("state", ""), (r.get("state") or "").strip())


def _place(city, county, state):
    parts = [p for p in (city, county, state) if p]
    if not parts:
        return ""
    return " in " + ", ".join(parts)


def _size_sentence(r, year):
    e = _num(r.get("total_students"))
    t = _num(r.get("teachers"))
    if not e:
        return ""
    s = f"As of the {year} school year, it enrolled {e:,} students"
    if t:
        ratio = _f1(r.get("student_teacher_ratio")) or round(e / t, 1)
        s += f" and employed about {t} teachers, a student–teacher ratio of roughly {ratio}:1"
    return s + "."


def _clean_district(d):
    """Trim NCES's verbose/truncated legal district names, e.g.
    'School District No. 3 in the county of El Paso and State of' -> '...No. 3'."""
    d = (d or "").strip()
    d = re.sub(r"\s+in the (county|city|borough|parish|town) of .*$", "", d, flags=re.I)
    return d.strip().rstrip(",")


def _district_phrase(d):
    d = (d or "").strip()
    if not d:
        return ""
    low = d.lower()
    already = any(w in low for w in ("district", "isd", "usd", "csd", "schools",
                                     "unified", "diocese", "archdiocese"))
    name = d if already else f"{d} school district"
    return name if low.startswith("the ") else f"the {name}"


def _render_public(r, year):
    name = _titlecase((r.get("school_name") or "").strip()) or "This school"
    city = _titlecase(r.get("city", "").strip())
    county = _titlecase(r.get("county", "").strip())
    state = _state(r)
    lo, hi = _public_grades(r)
    level = _level_word(lo, hi)
    charter = "charter " if r.get("Charter") == "Yes" else ""
    type_adj = PUB_TYPE_ADJ.get(r.get("type", ""), "")
    grades = f", serving grades {lo}–{hi}" if lo and hi else ""
    sentences = [f"{name} is a public {charter}{type_adj}{level}school{_place(city, county, state)}{grades}."]

    district = _titlecase(_clean_district(r.get("District")))
    dphrase = _district_phrase(district)
    if dphrase and district.lower() not in name.lower():
        sentences.append(f"It is part of {dphrase}.")

    loc = PUB_LOCALE.get(r.get("Locale", ""))
    if loc:
        sentences.append(f"The school is located in {loc}.")

    status = (r.get("Status") or "").strip()
    if status and status not in ("Open", ""):
        sentences.append(f"In federal records it is listed with a status of \"{status}\".")

    size = _size_sentence(r, year)
    if size:
        sentences.append(size)

    free, red, tot = _num(r.get("Free Lunch")), _num(r.get("Reduced Lunch")), _num(r.get("total_students"))
    if tot and (free or red):
        pct = round((((free or 0) + (red or 0)) / tot) * 100)
        sentences.append(f"About {pct}% of students were eligible for free or "
                         f"reduced-price lunch.")

    addr, zc = _titlecase(r.get("address", "").strip()), r.get("zip", "").strip()
    if addr and city and state:
        loc_line = f"The school is located at {addr}, {city}, {r.get('state','')}"
        if zc:
            loc_line += f" {zc}"
        ph = (r.get("phone") or "").strip()
        sentences.append(loc_line + (f", and can be reached at {ph}." if ph else "."))
    return sentences


def _render_private(r, year):
    name = _titlecase((r.get("school_name") or "").strip()) or "This school"
    city = _titlecase(r.get("city", "").strip())
    county = _titlecase(r.get("county", "").strip())
    state = _state(r)
    lo, hi = _private_grades(r)
    level = (PSS_LEVEL_WORD.get(r.get("PSS_LEVEL", ""), "") or "").strip()
    level = f"{level} " if level else ""
    coed = PSS_COED.get(r.get("PSS_COED", ""), "")
    relig = PSS_RELIG.get(r.get("PSS_RELIG", ""), "")
    type_adj = PSS_TYPE_ADJ.get(r.get("type", ""), "")
    lead_adj = " ".join(w for w in (coed, relig) if w)
    lead_adj = f"{lead_adj} " if lead_adj else ""
    grades = f", serving grades {lo}–{hi}" if lo and hi else ""
    county_p = f"{county} County" if county and "county" not in county.lower() else county
    sentences = [f"{name} is a {lead_adj}private {type_adj}{level}school"
                 f"{_place(city, county_p, state)}{grades}."]

    loc = LOCALE_CODE.get((r.get("PSS_LOCALE") or "").strip())
    if loc:
        sentences.append(f"It is located in {loc}.")

    size = _size_sentence(r, year)
    if size:
        sentences.append(size)

    demo = [(lbl, _f1(r.get(col))) for lbl, col in RACE_PCT if (_f1(r.get(col)) or 0) > 0]
    demo.sort(key=lambda x: -x[1])
    if demo:
        parts = [f"{p:g}% {lbl}" for lbl, p in demo]
        joined = ", ".join(parts[:-1]) + (f", and {parts[-1]}" if len(parts) > 1 else parts[0])
        sentences.append(f"Its student body was {joined}.")

    ops = []
    lib = r.get("PSS_LIBRARY")
    if lib in ("Yes", "No"):
        ops.append("has a library" if lib == "Yes" else "does not have a library")
    days, hrs = _num(r.get("PSS_SCH_DAYS")), _f1(r.get("PSS_STU_DAY_HRS"))
    if days:
        ops.append(f"is in session about {days} days a year"
                   + (f", {hrs:g} hours a day" if hrs else ""))
    if ops:
        sentences.append("The school " + " and ".join(ops) + ".")

    assoc = sorted({(r.get(f"PSS_ASSOC_{i}") or "").strip()
                    for i in range(1, 16)} - {""})
    if assoc:
        joined = ", ".join(assoc[:-1]) + (f", and {assoc[-1]}" if len(assoc) > 1 else assoc[0])
        sentences.append(f"It reports affiliation with {joined}.")

    addr, zc = _titlecase(r.get("address", "").strip()), r.get("zip", "").strip()
    if addr and city and state:
        line = f"The school is located at {addr}, {city}, {r.get('state','')}"
        sentences.append(line + (f" {zc}." if zc else "."))
    return sentences


def render_article(r, year="2021-22"):
    """Full plaintext article for one NCES master record (public or private)."""
    sentences = (_render_private if r.get("sector") == "private"
                 else _render_public)(r, year)
    return re.sub(r"\s+", " ", " ".join(sentences)).replace(" ,", ",").strip()


def _load(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--id", help="NCES school_id")
    ap.add_argument("--name", help="exact school name (first match)")
    ap.add_argument("--year", default="2021-22")
    ap.add_argument("--demo", action="store_true",
                    help="render a public and a private example")
    args = ap.parse_args()
    rows = _load(args.master)

    if args.id:
        picks = [r for r in rows if r["school_id"] == args.id][:1]
    elif args.name:
        picks = [r for r in rows if (r["school_name"] or "").lower() == args.name.lower()][:1]
    elif args.demo:
        pub = next(r for r in rows if r["sector"] == "public" and r.get("Locale")
                   and _num(r.get("total_students")) and r.get("District"))
        pri = next(r for r in rows if r["sector"] == "private" and r.get("PSS_RELIG"))
        picks = [pub, pri]
    else:
        ap.error("give --id, --name, or --demo")

    if not picks:
        print("no matching school found.")
        return
    for i, r in enumerate(picks):
        if i:
            print("\n" + "=" * 78 + "\n")
        print(render_article(r, args.year))


if __name__ == "__main__":
    main()
