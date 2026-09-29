#!/usr/bin/env python3
"""Fetch the full readable plaintext of each finalized school's Wikipedia article.

Reads the enriched crawl (schools_new_enriched.csv) and, for every row, pulls the
full article body as plaintext via the MediaWiki API's TextExtracts extension
(prop=extracts&explaintext=1, no exintro). Markup, infoboxes, tables, and
references are stripped, leaving readable prose suitable for downstream NLP/LLM
use. One JSON record per article is streamed to schools_new_articles.jsonl.

TextExtracts returns only ONE full-content extract per request, so this makes one
API call per article (~19k sequential requests). The api_get() helper from the
crawler handles retries, rate limiting (429/503), and maxlag backoff.

The output JSONL doubles as the checkpoint: on start we read it, skip pageids
already fetched, and append. Flushing after each write means an interrupt loses
nothing -- just re-run to resume.

Usage:
    python fetch_article_text.py                                  # enriched -> articles.jsonl
    python fetch_article_text.py --in schools_new_enriched.csv --out schools_new_articles.jsonl
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

# Reuse the crawler's polite API client (retry/backoff/maxlag/rate-limit).
from crawl_k12_schools import API_URL, USER_AGENT, api_get

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
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def fetch_extract(session, pageid, timeout):
    """Return the cleaned plaintext extract for a pageid, or "" if unavailable."""
    data = api_get(
        session,
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "exsectionformat": "wiki",
            "pageids": str(pageid),
        },
        timeout=timeout,
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return ""
    return clean_text(pages[0].get("extract", "") or "")


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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", default="schools_new_enriched.csv")
    ap.add_argument("--out", default="schools_new_articles.jsonl")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds to sleep between requests (be polite)")
    ap.add_argument("--timeout", type=float, default=60)
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

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
                text = fetch_extract(session, pageid, args.timeout)
            except (RuntimeError, requests.RequestException) as exc:
                sys.stderr.write(f"  ! pageid {pageid} failed: {exc}\n")
                continue
            if not text:
                empty += 1
            record = {
                "pageid": pageid,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
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
