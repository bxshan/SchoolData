#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Fetch the full readable plaintext of each finalized school's Wikipedia article.

Reads the enriched crawl (output/schools_enriched.csv) and pulls each article's
full body as plaintext via the MediaWiki API's TextExtracts extension
(prop=extracts&explaintext=1, no exintro), together with the current revision id
(prop=revisions) so every text is pinned to the exact revision it came from.
Markup, infoboxes, tables, and references are stripped, and any surviving
`{{templates}}`, `[[wikilinks]]` and `[12]` citation markers are removed, leaving
readable prose suitable for downstream NLP/LLM use. One JSON record per article
is streamed to output/wiki_articles.jsonl.

--matches restricts the fetch to articles that matched an NCES school (the only
ones the published dataset uses), e.g. ../data_publish/output/wiki_nces_matches.csv.

TextExtracts returns only ONE full-content extract per request, so this makes one
API call per article (~15k sequential requests with --matches). The api_get()
helper from the crawler handles retries, rate limiting (429/503), and maxlag
backoff.

The output JSONL doubles as the checkpoint: on start we read it, skip pageids
already fetched, and append. Flushing after each write means an interrupt loses
nothing -- just re-run to resume.

Usage:
    python fetch_article_text.py --matches ../data_publish/output/wiki_nces_matches.csv
    python fetch_article_text.py                 # every enriched article
    python fetch_article_text.py --in schools_enriched.csv --out wiki_articles.jsonl
    python fetch_article_text.py --delay 0.2 --timeout 60

Only dependency beyond the standard library is `requests`:
    pip install requests
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

# The shared polite API client (retry/backoff/maxlag/rate-limit).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common.wiki_api import USER_AGENT, api_get  # noqa: E402

# Trailing/reference sections to drop entirely (matched case-insensitively on the
# heading text). Their subsections are dropped with them.
BOILERPLATE_SECTIONS = {
    "references", "external links", "external link", "see also", "notes",
    "notes and references", "further reading", "bibliography", "sources",
    "citations", "footnotes", "gallery",
}

# A wiki-format section heading line, e.g. "== References ==" or "=== Alumni ===".
_HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1$")


def clean_text(text):
    """Drop boilerplate sections and flatten to a single whitespace-normalized line.

    Sections are detected via their "== Heading ==" markers (exsectionformat=wiki).
    A boilerplate heading removes that section and every deeper subsection under it.
    All section headings are dropped (both the "==" markers and the title text);
    only body text is kept. All runs of whitespace (including successive newlines)
    collapse to single spaces.
    """
    kept = []
    skip_at_level = None  # drop lines until a heading at this level or shallower
    for line in text.split("\n"):
        m = _HEADING_RE.match(line.strip())
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            if skip_at_level is not None and level > skip_at_level:
                continue  # still inside a dropped section's subsection
            skip_at_level = None
            if title.lower() in BOILERPLATE_SECTIONS:
                skip_at_level = level
            continue  # drop the heading line itself, keep the section's body
        elif skip_at_level is None:
            kept.append(line)
    text = " ".join(kept)
    # explaintext occasionally leaks markup from unexpanded templates.
    for _ in range(3):                                   # nested {{a|{{b}}}}
        text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)   # [[a|b]] -> b
    text = re.sub(r"\[\[|\]\]|\{\{|\}\}", " ", text)                 # unbalanced leftovers
    text = re.sub(r"\[(?:\d+|[a-z]|citation needed|clarification needed)\]", "", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_extract(session, pageid, timeout):
    """Return (cleaned plaintext, revid, current title) for a pageid; text is ""
    when the page is missing or has no extract."""
    data = api_get(
        session,
        {
            "action": "query",
            "prop": "extracts|revisions",
            "explaintext": "1",
            "exsectionformat": "wiki",
            "rvprop": "ids",
            "pageids": str(pageid),
        },
        timeout=timeout,
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return "", "", ""
    page = pages[0]
    revs = page.get("revisions") or [{}]
    return (clean_text(page.get("extract", "") or ""),
            str(revs[0].get("revid", "")), page.get("title", ""))


def load_done(out_path):
    """Collect pageids already present in the output JSONL so we can resume."""
    done = set()
    if not os.path.exists(out_path):
        return done
    with open(out_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(int(json.loads(line)["pageid"]))
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    return done


# Inputs/outputs live in output/ (a sibling of the scripts). Bare --in/--out
# names resolve there; pass a path with a separator to use another location.
OUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def _out(name):
    return name if os.path.dirname(name) else os.path.join(OUT_DIR, name)


def reclean(path):
    """Apply the current clean_text to every stored record, in place."""
    changed, rows = 0, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            text = clean_text(r["text"])
            if text != r["text"]:
                changed += 1
                r["text"], r["chars"] = text, len(text)
            rows.append(r)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    sys.stderr.write(f"recleaned {len(rows):,} records ({changed:,} changed) -> {path}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", default="schools_enriched.csv")
    ap.add_argument("--out", default="wiki_articles.jsonl")
    ap.add_argument("--matches", default=None,
                    help="only fetch articles whose pageid is in this match CSV "
                         "(column wiki_pageid)")
    ap.add_argument("--delay", type=float, default=0.1,
                    help="seconds to sleep between requests (be polite)")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--reclean", action="store_true",
                    help="re-run clean_text over the existing --out file (after a "
                         "cleaning fix) without re-fetching, then exit")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    args.inp, args.out = _out(args.inp), _out(args.out)
    if args.reclean:
        reclean(args.out)
        return

    with open(args.inp, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if args.matches:
        with open(args.matches, encoding="utf-8") as fh:
            wanted = {r["wiki_pageid"] for r in csv.DictReader(fh)}
        rows = [r for r in rows if r.get("pageid") in wanted]

    done = load_done(args.out)
    todo = [r for r in rows if r.get("pageid") and int(r["pageid"]) not in done]
    sys.stderr.write(
        f"{len(rows)} articles in {args.inp}; {len(done)} already fetched; "
        f"{len(todo)} to go (delay={args.delay}s).\n"
    )

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    fetched = empty = 0
    with open(args.out, "a", encoding="utf-8") as out:
        for i, r in enumerate(todo, 1):
            pageid = int(r["pageid"])
            try:
                text, revid, cur_title = fetch_extract(session, pageid, args.timeout)
            except (RuntimeError, requests.RequestException) as exc:
                sys.stderr.write(f"  ! pageid {pageid} failed: {exc}\n")
                continue
            if not text:
                empty += 1
            record = {
                "pageid": pageid,
                "title": cur_title or r.get("title", ""),
                "url": r.get("url", ""),
                "revid": revid,
                "text": text,
                "chars": len(text),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            fetched += 1
            if i % 100 == 0:
                sys.stderr.write(
                    f"  [{i}/{len(todo)}] fetched, {empty} empty so far\n"
                )
            if args.delay:
                time.sleep(args.delay)

    sys.stderr.write(
        f"DONE. {fetched} written this run ({empty} empty), output -> {args.out}\n"
    )


if __name__ == "__main__":
    main()
