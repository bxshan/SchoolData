#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Release gate for the `articles` dataset: run after prep_data_publish.py and
before uploading output/dist/ to Hugging Face. Exits non-zero if any check fails.

Checks
  schema        the 11 documented columns, from_wikipedia is int8
  rows          at least --expect-rows rows
  keys          nces_id present and unique; sector public|private; 2-letter state
  text          every row has text; Wikipedia rows carry no leftover wiki markup
  provenance    from_wikipedia=1 rows have title/qid/revid, a Wikipedia source URL
                and CC-BY-SA-4.0; from_wikipedia=0 rows have blank wiki fields, an
                NCES source and CC0-1.0
  one article   no Wikipedia article supplies the text of two schools
  level         no Wikipedia row whose article title names a level (high /
                middle / elementary) the school's NCES grade span can't serve
  per state     with --baseline (a previous release's articles.jsonl or parquet
                dir), no state's row count moves more than --max-state-delta — the
                check that catches a truncated state download

Usage:
    python validate_publish.py
    python validate_publish.py --expect-rows 122000 --baseline old/articles.jsonl
"""

import argparse
import collections
import csv
import glob
import json
import os
import random
import re
import sys

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "output", "dist")
MASTER = os.path.join(HERE, "..", "nces_crawl", "output_all_schools", "all_schools_master.csv")
sys.path.insert(0, HERE)
from match_wiki_nces import grade_levels, norm_name, school_levels  # noqa: E402

FIELDS = ["nces_id", "name", "state", "sector", "text", "from_wikipedia",
          "wikipedia_title", "wikidata_qid", "wikipedia_revid", "source", "license"]
MARKUP_RE = re.compile(r"\{\{|\}\}|\[\[|\]\]|\[\d+\]")


def read_release(path):
    """Rows from a parquet dir/file or a JSONL file."""
    if path.endswith(".jsonl"):
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()], None
    files = sorted(glob.glob(os.path.join(path, "**", "*.parquet"), recursive=True)
                   if os.path.isdir(path) else [path])
    if not files:
        sys.exit(f"no parquet files under {path}")
    table = pq.read_table(files)
    return table.to_pylist(), table.schema


class Gate:
    def __init__(self):
        self.failed = 0

    def check(self, name, ok, detail="", examples=()):
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}{': ' + detail if detail else ''}")
        for ex in list(examples)[:5]:
            print(f"           e.g. {ex}")
        self.failed += not ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dist", default=DIST)
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--expect-rows", type=int, default=0)
    ap.add_argument("--baseline", help="previous release (articles.jsonl or parquet dir)")
    ap.add_argument("--max-state-delta", type=float, default=0.05)
    ap.add_argument("--sample", type=int, default=5,
                    help="print N random Wikipedia rows for a human spot-check")
    args = ap.parse_args()

    rows, schema = read_release(os.path.join(args.dist, "data", "articles"))
    g = Gate()
    print(f"validating {len(rows):,} rows from {args.dist}")

    g.check("schema", schema.names == FIELDS and str(schema.field("from_wikipedia").type) == "int8",
            f"{schema.names}")
    g.check("rows", len(rows) >= args.expect_rows,
            f"{len(rows):,} (expected >= {args.expect_rows:,})")

    ids = collections.Counter(r["nces_id"] for r in rows)
    dup_ids = [k for k, v in ids.items() if v > 1 or not k]
    g.check("keys: nces_id unique and present", not dup_ids, f"{len(dup_ids)} bad", dup_ids)
    bad_keys = [r["nces_id"] for r in rows
                if r["sector"] not in ("public", "private") or not re.fullmatch(r"[A-Z]{2}", r["state"] or "")]
    g.check("keys: sector and state valid", not bad_keys, f"{len(bad_keys)} bad", bad_keys)

    empty = [r["nces_id"] for r in rows if not (r["text"] or "").strip()]
    g.check("text: non-empty", not empty, f"{len(empty)} empty", empty)
    wiki = [r for r in rows if r["from_wikipedia"] == 1]
    markup = [f"{r['wikipedia_title']}: ...{MARKUP_RE.search(r['text']).group(0)}..."
              for r in wiki if MARKUP_RE.search(r["text"])]
    g.check("text: no leftover wiki markup", not markup, f"{len(markup)} rows", markup)

    bad_prov = []
    for r in rows:
        if r["from_wikipedia"] == 1:
            ok = (r["wikipedia_title"] and r["wikidata_qid"] and r["wikipedia_revid"]
                  and r["source"].startswith("https://en.wikipedia.org/wiki/")
                  and r["license"] == "CC-BY-SA-4.0")
        else:
            ok = (r["from_wikipedia"] == 0 and not r["wikipedia_title"]
                  and not r["wikidata_qid"] and not r["wikipedia_revid"]
                  and r["source"].startswith("NCES") and r["license"] == "CC0-1.0")
        if not ok:
            bad_prov.append(r["nces_id"])
    g.check("provenance consistent with from_wikipedia", not bad_prov,
            f"{len(bad_prov)} bad", bad_prov)

    titles = collections.Counter(r["wikipedia_title"] for r in wiki)
    reused = [f"{t} x{n}" for t, n in titles.items() if n > 1]
    g.check("one article per school", not reused, f"{len(reused)} articles reused", reused)

    with open(args.master, encoding="utf-8") as fh:
        master = {r["school_id"]: r for r in csv.DictReader(fh)}
    conflicts = []
    for r in wiki:
        wl = school_levels(norm_name(r["wikipedia_title"]))
        nl = grade_levels(master[r["nces_id"]]) if r["nces_id"] in master else set()
        if wl and nl and not (wl & nl):
            m = master[r["nces_id"]]
            conflicts.append(f"{r['wikipedia_title']} -> {r['name']} "
                             f"(grades {m['low_grade']}-{m['high_grade']})")
    g.check("level: article level fits NCES grade span", not conflicts,
            f"{len(conflicts)} conflicts", conflicts)

    if args.baseline:
        base, _ = read_release(args.baseline)
        old = collections.Counter(r["state"] for r in base)
        new = collections.Counter(r["state"] for r in rows)
        moved = sorted(((new[s] - old[s]) / max(old[s], 1), s, old[s], new[s])
                       for s in set(old) | set(new))
        bad = [f"{s} {a:,} -> {b:,} ({d:+.1%})" for d, s, a, b in moved
               if abs(d) > args.max_state_delta and max(a, b) >= 20]
        g.check(f"per state: row counts within ±{args.max_state_delta:.0%} of baseline",
                not bad, f"{len(base):,} -> {len(rows):,} rows", bad)

    card_path = os.path.join(args.dist, "README.md")
    card = open(card_path, encoding="utf-8").read() if os.path.exists(card_path) else ""
    g.check("card: rendered with this build's numbers",
            card.startswith("---") and "@@" not in card and f"{len(rows):,}" in card,
            card_path)

    n_wiki = len(wiki)
    print(f"\n  from_wikipedia=1: {n_wiki:,} ({100 * n_wiki / max(len(rows), 1):.1f}%)  "
          f"text: {sum(len(r['text']) for r in rows) / 1e6:.1f}M chars")
    if wiki and args.sample:
        print("  spot-check (does the article describe this school?):")
        for r in random.Random(0).sample(wiki, min(args.sample, n_wiki)):
            print(f"    {r['name']} ({r['state']}) <- {r['wikipedia_title']}: "
                  f"{r['text'][:110]}...")

    print("\nRESULT:", "FAIL" if g.failed else "PASS")
    sys.exit(1 if g.failed else 0)


if __name__ == "__main__":
    main()
