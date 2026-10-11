#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Turn per-school fact sheets into data for the school pages.

Each fact sheet is a Markdown file whose English part starts with a bold title
line containing "Fact Sheet" and holds a numbered table:

    | # | Fact | Value we found | Source | ✅ / ❌ + correction |

Only that table is read; everything else in the file is ignored. The school is
identified by the NCES id in the table's NCES links (school_detail.asp?ID=...).

Output: web/public/data/school_fact_sheets.json
  { nces_id: { asOf: "YYYY-MM-DD",
               facts: [ { f: fact, v: value, s: [[label, url], ...] }, ... ],
               missing: [ fact, ... ] } }
  `facts` holds only rows with a value; rows whose value starts with "Not found"
  or "None found" go to `missing`, so the page can ask the school for them.
  The sheets are written to the school ("your website writes ..."); that wording
  is rewritten to third person, since the output is shown on public pages.

Usage:
    python build_fact_sheets.py <fact-sheet-dir> [--as-of YYYY-MM-DD]
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "web", "public", "data", "school_fact_sheets.json")
SCHOOLS = os.path.join(HERE, "..", "web", "public", "data", "schools.json")

TITLE = re.compile(r"^\*\*[^*\n]*Fact Sheet[^*\n]*\*\*$", re.M)
ROW = re.compile(r"^\|\s*\d+\s*\|")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
NCES_ID = re.compile(r"school_detail\.asp\?ID=(\w+)")
NOT_FOUND = re.compile(r"^\*?(not found|none found)\b", re.I)


def english_table(text):
    """Rows of the English fact table: [(fact, value, source_cell), ...]."""
    m = TITLE.search(text)
    if not m:
        return None, []
    part = text[m.start():].split("\n---", 1)[0]
    rows = []
    for line in part.splitlines():
        if ROW.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4:
                rows.append((cells[1], cells[2], cells[3]))
    ids = set(NCES_ID.findall(part))
    return (ids.pop() if len(ids) == 1 else None), rows


def plain(value):
    """Markdown cell -> plain text: links keep their text, emphasis goes, and
    "your website" (addressed to the school) becomes "the school website"."""
    value = LINK.sub(r"\1", value)
    value = re.sub(r"\byour website('s)?", lambda m: "the school website" + (m.group(1) or ""),
                   value, flags=re.I)
    return re.sub(r"\*+", "", value).strip()


def parse(path):
    with open(path, encoding="utf-8") as fh:
        sid, rows = english_table(fh.read())
    if not sid:
        return None, None
    facts, missing = [], []
    for fact, value, source in rows:
        if NOT_FOUND.match(value.strip()):
            missing.append(plain(fact))
            continue
        facts.append({"f": plain(fact), "v": plain(value),
                      "s": [[label, url] for label, url in LINK.findall(source)]})
    return sid, {"facts": facts, "missing": missing}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir", help="folder of fact-sheet .md files")
    ap.add_argument("--as-of", default=datetime.date.today().isoformat(),
                    help="date the facts were compiled (default: today)")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    with open(SCHOOLS, encoding="utf-8") as fh:
        known = {s["i"] for s in json.load(fh)}

    out, skipped = {}, []
    for path in sorted(glob.glob(os.path.join(args.dir, "*.md"))):
        sid, sheet = parse(path)
        name = os.path.basename(path)
        if not sid:
            skipped.append(f"{name}: no English fact table with one NCES id")
        elif sid not in known:
            skipped.append(f"{name}: NCES id {sid} is not in schools.json")
        else:
            out[sid] = {"asOf": args.as_of, **sheet}

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    sys.stderr.write(f"{len(out)} fact sheets -> {args.out}\n")
    for s in skipped:
        sys.stderr.write(f"  skipped {s}\n")


if __name__ == "__main__":
    main()
