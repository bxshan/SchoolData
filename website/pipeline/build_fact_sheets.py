#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Turn the fact-sheet research files into data for the school pages.

Reads fact-sheet/research/<nces_id>.json (see fact-sheet/README.md) and builds
its 15 rows with fact-sheet/build_sheets.py's own build_rows(): rows 1-7 from
the NCES master and the CDE directory, rows 8-15 from the research. So a page
always shows exactly the rows of the sheet sent to the school.

Output: web/public/data/school_fact_sheets.json
  { nces_id: { asOf: "YYYY-MM-DD",
               facts: [ { f: fact, v: value, s: [[label, url], ...] }, ... ],
               missing: [ fact, ... ] } }
  `facts` holds only rows with a value; rows whose value starts with "Not found"
  or "None found" go to `missing`, so the page can ask the school for them.
  Values are plain text (Markdown links keep their text). The research is
  written for the school ("your website writes ..."); that wording is rewritten
  to third person, since the output is shown on public pages.

Usage:
    python build_fact_sheets.py [research-dir]   # default: ../../fact-sheet/research
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FACT_SHEET = os.path.join(HERE, "..", "..", "fact-sheet")
OUT = os.path.join(HERE, "..", "web", "public", "data", "school_fact_sheets.json")
SCHOOLS = os.path.join(HERE, "..", "web", "public", "data", "schools.json")

sys.path.insert(0, FACT_SHEET)
from build_sheets import CDE, NOT_FOUND, build_rows, load_master  # noqa: E402

LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def plain(value):
    """Markdown value -> plain text: links keep their text, emphasis goes, and
    "your website" (addressed to the school) becomes "the school website"."""
    value = LINK.sub(r"\1", value)
    value = re.sub(r"\byour website('s)?", lambda m: "the school website" + (m.group(1) or ""),
                   value, flags=re.I)
    return re.sub(r"\*+", "", value).strip()


def page_data(r, row, cde):
    facts, missing = [], []
    for fact, value, sources in build_rows(r, row, cde):
        if NOT_FOUND.match(value):
            missing.append(fact)
            continue
        facts.append({"f": fact, "v": plain(value),
                      "s": [[s["label"], s["url"]] for s in sources if s.get("url")]})
    return {"asOf": r["compiled"], "facts": facts, "missing": missing}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir", nargs="?", default=os.path.join(FACT_SHEET, "research"),
                    help="folder of research/<nces_id>.json files")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    research = []
    for path in sorted(glob.glob(os.path.join(args.dir, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            research.append(json.load(fh))
    with open(SCHOOLS, encoding="utf-8") as fh:
        on_map = {s["i"] for s in json.load(fh)}
    master = load_master({r["nces_id"] for r in research})
    cde_all = {}
    if os.path.exists(CDE):
        with open(CDE, encoding="utf-8") as fh:
            cde_all = json.load(fh)

    out, skipped = {}, []
    for r in research:
        sid = r["nces_id"]
        if sid not in master:
            skipped.append(f"{sid}: not in the NCES master")
        elif sid not in on_map:
            skipped.append(f"{sid}: not in schools.json")
        else:
            out[sid] = page_data(r, master[sid], cde_all.get(sid))

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    sys.stderr.write(f"{len(out)} fact sheets -> {args.out}\n")
    for s in skipped:
        sys.stderr.write(f"  skipped {s}\n")


if __name__ == "__main__":
    main()
