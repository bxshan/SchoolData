#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Render each school's fact sheet from NCES, the CDE directory and research.

A fact sheet is a 15-row table a school is asked to confirm (see README.md).
Rows come from three places, the same way the dataset is built:

  rows 1-7  federal layer: generated from the NCES master the Hugging Face
            dataset is built from (data/nces_crawl/output_all_schools/
            all_schools_master.csv), with the same title-casing, grade codes,
            rounding and school year (DATA_YEAR) as the dataset text. California
            schools are cross-checked with the CDE directory (cde_directory.json,
            from fetch_cde.py), which also supplies the CDS code and links.
  rows 8-15 research: research/<nces_id>.json, found by hand with a source
            link for every value. Row 9 gets the state directory open date
            appended when the opening year was not found.
  header    Wikipedia / Wikidata status from data/data_publish/output/
            wiki_nces_matches.csv, the matcher's output for the dataset.

A research file may override a federal row (rows 1-7) by giving that row a
"value"; use it only for what NCES cannot say (a school's own name for itself,
a charter's authorizing district, TK). Leave "value" null to generate the row.

Output: sheets/<nces_id>.md, in the format website/pipeline/build_fact_sheets.py
reads (a bold title line containing "Fact Sheet", then a numbered table whose
NCES links carry the school's id), plus a "Directory check" section listing
where the state directory disagrees with the research (e.g. an outdated
website), for outreach.

Usage:
    python build_sheets.py [nces_id ...]      # default: every research file
"""

import argparse
import csv
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
MASTER = os.path.join(ROOT, "data", "nces_crawl", "output_all_schools", "all_schools_master.csv")
WIKI_MATCHES = os.path.join(ROOT, "data", "data_publish", "output", "wiki_nces_matches.csv")
CDE = os.path.join(HERE, "cde_directory.json")
RESEARCH = os.path.join(HERE, "research")
SHEETS = os.path.join(HERE, "sheets")

sys.path.insert(0, os.path.join(ROOT, "data"))
from nces_crawl.generate_article import (  # noqa: E402  same rules as the dataset text
    DATA_YEAR, PUB_TYPE_ADJ, _clean_district, _grade, _level_word, _num, _titlecase)

FACTS = ["Official name", "School type", "Grades", "District", "Address", "Enrollment",
         "Teachers", "Official website", "Year opened", "Mascot", "School colors",
         "Named after", "Former names", "Programs", "Awards and recognitions"]
NOT_FOUND = re.compile(r"^\*?(not found|none found)\b", re.I)


def load_master(ids):
    """{nces_id: master row} for the requested schools only."""
    out = {}
    with open(MASTER, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["school_id"] in ids:
                out[row["school_id"]] = row
    return out


def load_wiki(ids):
    """{nces_id: (wikipedia url, wikidata qid)} from the dataset's matcher output."""
    out = {}
    if os.path.exists(WIKI_MATCHES):
        with open(WIKI_MATCHES, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["nces_school_id"] in ids:
                    out[row["nces_school_id"]] = (row["wiki_url"], row["wiki_wikidata_qid"])
    return out


def nces_link(sid):
    return {"label": "NCES", "url": f"https://nces.ed.gov/ccd/schoolsearch/school_detail.asp?ID={sid}"}


def cde_link(cde):
    return {"label": "CA Dept. of Education",
            "url": f"https://sd.cde.ca.gov/schooldirectory/details?cdscode={cde['CDSCode']}"}


def _date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def federal_rows(sid, row, cde):
    """Rows 1-7 from the NCES master (+ CDE): [(fact, value, sources)]."""
    nces = [nces_link(sid)]
    both = nces + ([cde_link(cde)] if cde else [])
    year = DATA_YEAR[row["sector"]].replace("-", "–")
    lo, hi = _grade(row["low_grade"]), _grade(row["high_grade"])
    charter = row.get("Charter") == "Yes"
    kind = f"Public {'charter ' if charter else ''}{PUB_TYPE_ADJ.get(row.get('type', ''), '')}" \
           f"{_level_word(lo, hi)}school"
    if not charter and cde and cde.get("Magnet") == "N":
        kind += " (not charter, not magnet)"
    district = _titlecase(_clean_district(row.get("District")))
    if not any(w in district.lower() for w in ("district", "unified", "schools")):
        district += " School District"
    address = f"{_titlecase(row['address'])}, {_titlecase(row['city'])}, {row['state']} {row['zip']}"
    teachers = _num(row.get("teachers"))
    return [
        ("Official name", _titlecase(row["school_name"]), nces),
        ("School type", kind, both),
        ("Grades", f"{lo}–{hi}", both),
        ("District", district, nces),
        ("Address", address, both),
        ("Enrollment", f"{_num(row['total_students']):,} students ({year})", nces),
        ("Teachers", f"{teachers} (full-time equivalent, {year})" if teachers else "*Not found*", nces),
    ]


def source_cell(sources):
    if not sources:
        return "—"
    return "; ".join(f"[{s['label']}]({s['url']})" if s.get("url") else s["label"]
                     for s in sources)


def build_rows(r, row, cde):
    sid = r["nces_id"]
    facts = r["facts"]
    if len(facts) != len(FACTS) or any(not f["fact"].startswith(want) for f, want in zip(facts[:7], FACTS)):
        raise ValueError(f"{sid}: facts must be the 15 rows of README.md, in order")
    rows = []
    for i, (fact, value, sources) in enumerate(federal_rows(sid, row, cde)):
        if facts[i].get("value"):  # research override, keeps its own sources
            value, sources = facts[i]["value"], facts[i]["sources"]
        rows.append((facts[i]["fact"], value, sources))  # keeps labels like "District / charter authorizer"
    for f in facts[7:]:
        value, sources = f["value"], list(f["sources"])
        if f["fact"] == "Year opened" and NOT_FOUND.match(value) and cde and cde.get("OpenDate") \
                and "state directory" not in value:
            value += f" (state directory open date: {_date(cde['OpenDate'])})"
            sources.append(cde_link(cde))
        rows.append((f["fact"], value, sources))
    return rows


def directory_check(r, cde):
    """Where the state directory disagrees with the research, for outreach."""
    notes = []
    site = r["facts"][7]["value"]
    listed = (cde or {}).get("Website") or ""
    host = lambda u: re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower()
    if listed and site and not NOT_FOUND.match(site) and host(listed) != host(site):
        notes.append(f"The state directory lists the website as {listed}; the school's site is {site}.")
    return notes


def render(r, row, cde, wiki):
    sid = r["nces_id"]
    year = DATA_YEAR[row["sector"]]
    wp = (f"Wikipedia: {wiki[0]}" + (f" (Wikidata {wiki[1]})" if wiki[1] else "")) if wiki \
        else "Wikipedia: no article matched"
    meta = [f"NCES ID {sid}"] + ([f"CDS code {cde['CDSCode']}"] if cde else []) + \
           [f"compiled {r['compiled']}", f"NCES figures: {year}", wp]
    lines = [f"**{r['name']} — Public Fact Sheet (draft for your review)**", "",
             " · ".join(meta), "",
             "## Three things we could not find", ""]
    lines += [f"{i}. {q}" for i, q in enumerate(r["questions"], 1)]
    lines += ["", "## Facts", "",
              "| # | Fact | Value we found | Source | Your review | Correction or source link |",
              "| --- | --- | --- | --- | --- | --- |"]
    for i, (fact, value, sources) in enumerate(build_rows(r, row, cde), 1):
        lines.append(f"| {i} | {fact} | {value} | {source_cell(sources)} |  |  |")
    notes = directory_check(r, cde)
    if notes:
        lines += ["", "## Directory check", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def check(r, row, cde):
    """Warnings where NCES and the CDE directory disagree."""
    warn = []
    if cde:
        if (cde["Charter"] == "Y") != (row.get("Charter") == "Yes"):
            warn.append(f"charter: NCES {row.get('Charter')} vs CDE {cde['Charter']}")
        if (_grade(cde["GradeLow"]), _grade(cde["GradeHigh"])) != (_grade(row["low_grade"]), _grade(row["high_grade"])):
            warn.append(f"grades: NCES {row['low_grade']}-{row['high_grade']} vs CDE {cde['GradeLow']}-{cde['GradeHigh']}")
        if cde.get("Status") != "Active":
            warn.append(f"CDE status {cde.get('Status')}")
    return warn


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="*", help="NCES ids (default: all research files)")
    args = ap.parse_args()

    paths = ([os.path.join(RESEARCH, f"{i}.json") for i in args.ids] if args.ids
             else sorted(glob.glob(os.path.join(RESEARCH, "*.json"))))
    research = [json.load(open(p, encoding="utf-8")) for p in paths]
    ids = {r["nces_id"] for r in research}
    master, wiki = load_master(ids), load_wiki(ids)
    cde_all = json.load(open(CDE, encoding="utf-8")) if os.path.exists(CDE) else {}

    os.makedirs(SHEETS, exist_ok=True)
    written = 0
    for r in research:
        sid = r["nces_id"]
        row = master.get(sid)
        if row is None:
            sys.stderr.write(f"skipped {sid}: not in the NCES master\n")
            continue
        cde = cde_all.get(sid)
        if sid.startswith("06") and row["sector"] == "public" and not cde:
            sys.stderr.write(f"  warning {sid}: no CDE record (run fetch_cde.py)\n")
        for w in check(r, row, cde):
            sys.stderr.write(f"  warning {sid}: {w}\n")
        with open(os.path.join(SHEETS, f"{sid}.md"), "w", encoding="utf-8") as fh:
            fh.write(render(r, row, cde, wiki.get(sid)))
        written += 1
    sys.stderr.write(f"{written} fact sheets -> {SHEETS}\n")


if __name__ == "__main__":
    main()
