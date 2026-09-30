#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Build the `articles` release of the us-k12-schools Hugging Face dataset.

One row per NCES school. Inputs:

  1. NCES all-schools master  (data/nces_crawl/output_all_schools/all_schools_master.csv)
     every row's NCES text is rendered from it at build time with the
     deterministic generator, so it can never be stale (--articles uses a
     pre-rendered JSONL instead)
  2. Wiki<->NCES match CSV      (output/wiki_nces_matches.csv, from match_wiki_nces.py)
  3. Wikipedia article text    (data/wiki_crawl/output/wiki_articles.jsonl, from
     wiki_crawl/fetch_article_text.py) {pageid, title, revid, text}

Output row (the schema documented in README.md, the dataset card):

  nces_id, name, state, sector, text, from_wikipedia (int8), wikipedia_title,
  wikidata_qid, wikipedia_revid, source, license

Text policy: a matched school whose Wikipedia text is usable (>= --min-chars,
and not an article about a closed school — see describes_closed_school) gets
that full article text, `from_wikipedia = 1`, license CC-BY-SA-4.0, and the
article URL as `source`. Every other school gets the generated NCES text,
`from_wikipedia = 0`, license CC0-1.0, and `NCES CCD|PSS <year>` as `source`
(wiki fields blank) — including matched schools whose article is missing or
too short.

Writes the upload-ready tree to output/dist/ (Parquet shards under
data/articles/, articles.jsonl, and CHANGELOG.md / LICENSE copied from this
directory, and README.md — the dataset card — rendered from this directory's
template with the build's own numbers) plus output/build_manifest.json, which records the git commit and
the sha256 of every input so a release can be traced and rebuilt.

Usage:
    python prep_data_publish.py
    python prep_data_publish.py --state CA          # single-state slice
    python prep_data_publish.py --skip-match        # NCES-only subset, no Wikipedia
    python validate_publish.py                      # always run before uploading
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "output")
DIST_DIR = os.path.join(OUT_DIR, "dist")
DEFAULT_MASTER = os.path.join(HERE, "..", "nces_crawl", "output_all_schools",
                              "all_schools_master.csv")
DEFAULT_MATCHES = os.path.join(OUT_DIR, "wiki_nces_matches.csv")
DEFAULT_WIKI_TEXT = os.path.join(HERE, "..", "wiki_crawl", "output", "wiki_articles.jsonl")
CARD_FILES = ("README.md", "CHANGELOG.md", "LICENSE")

sys.path.insert(0, os.path.join(HERE, "..", "nces_crawl", "generate_articles"))
from generate_article import DATA_YEAR, render_article  # noqa: E402
sys.path.insert(0, os.path.join(HERE, ".."))
from common.states import USPS_TO_NAME  # noqa: E402

FIELDS = ["nces_id", "name", "state", "sector", "text", "from_wikipedia",
          "wikipedia_title", "wikidata_qid", "wikipedia_revid", "source", "license"]
NCES_SOURCE = {"public": f"NCES CCD {DATA_YEAR['public']}",
               "private": f"NCES PSS {DATA_YEAR['private']}"}
WIKI_LICENSE, NCES_LICENSE = "CC-BY-SA-4.0", "CC0-1.0"


def render_generated(master_path):
    """Render every master row with the deterministic article generator
    -> {nces_id: row} (same shape as load_generated)."""
    out = {}
    with open(master_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sid = r["school_id"].strip()
            if sid and sid not in out:
                out[sid] = {"name": r["school_name"], "state": r["state"],
                            "sector": r["sector"], "text": render_article(r)}
    sys.stderr.write(f"rendered NCES articles: {len(out):,} schools from {master_path}\n")
    return out


def check_matches_against_master(matches, generated):
    """Every matched NCES id must exist in this build's master; otherwise the
    match CSV was built from an older master and must be regenerated."""
    stale = sorted(set(matches) - set(generated))
    if stale:
        sys.exit(f"{len(stale):,} matched NCES ids are not in the current master "
                 f"(e.g. {stale[:3]}) — the match CSV is stale.\n"
                 f"  re-run: python match_wiki_nces.py")


def load_generated(path):
    """Generated-article JSONL (a file or a dir of *.jsonl) -> {nces_id: row}.
    First occurrence wins."""
    files = ([path] if os.path.isfile(path)
             else sorted(glob.glob(os.path.join(path, "*.jsonl"))))
    if not files:
        sys.exit(f"no generated-article JSONL found at {path}\n"
                 f"  or omit --articles to render from the master")
    out, dups = {}, 0
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                sid = (r.get("school_id") or "").strip()
                text = (r.get("article") or "").strip()
                if not sid or not text:
                    continue
                if sid in out:
                    dups += 1
                    continue
                out[sid] = {"name": r.get("school_name") or "",
                            "state": r.get("state") or "",
                            "sector": r.get("sector") or "", "text": text}
    sys.stderr.write(f"generated articles: {len(out):,} schools from {len(files)} "
                     f"file(s){f' ({dups} dup ids skipped)' if dups else ''}\n")
    return out


def load_matches(path):
    """Match CSV -> {nces_id: {pageid, title, qid, url}}."""
    if not os.path.exists(path):
        sys.exit(f"match CSV not found at {path}\n  run: python match_wiki_nces.py")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sid = (r.get("nces_school_id") or "").strip()
            if sid:
                out[sid] = {"pageid": r["wiki_pageid"], "title": r["wiki_title"],
                            "qid": r["wiki_wikidata_qid"], "url": r["wiki_url"],
                            "method": r.get("match_method", "")}
    sys.stderr.write(f"wiki matches: {len(out):,} schools\n")
    return out


def load_wiki_text(path):
    """fetch_article_text.py JSONL -> {pageid: {title, revid, text, url}}."""
    if not os.path.exists(path):
        sys.exit(f"Wikipedia text not found at {path}\n"
                 f"  run: cd ../wiki_crawl && python fetch_article_text.py "
                 f"--matches ../data_publish/output/wiki_nces_matches.csv\n"
                 f"  (or pass --skip-match for an NCES-only build)")
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                out[str(r["pageid"])] = r            # last fetch of a page wins
    sys.stderr.write(f"wikipedia texts: {len(out):,} articles\n")
    return out


# Opening sentence in the past tense ("X was a public high school ...") means the
# article describes a school that no longer operates; NCES lists only schools
# operating in the reference year, so such a match is almost certainly a
# same-named current school and the article must not supply its text.
_OPENING_WAS = re.compile(r"^[^.]{0,200}?\b(was|were)\s+(a|an|the)\b", re.I)
_OPENING_IS = re.compile(r"^[^.]{0,200}?\b(is|are)\s+(a|an|the)\b", re.I)


def describes_closed_school(text):
    """True when the article's first sentence says the school *was* something."""
    first = (text or "")[:300]
    return bool(_OPENING_WAS.search(first)) and not _OPENING_IS.search(first)


def build_rows(generated, matches, wiki_text, min_chars, state):
    rows, stats = [], {"no_text": 0, "short_text": 0, "closed_school": 0}
    for sid in sorted(generated):
        g = generated[sid]
        if state and g["state"] != state:
            continue
        row = {"nces_id": sid, "name": g["name"], "state": g["state"],
               "sector": g["sector"], "text": g["text"], "from_wikipedia": 0,
               "wikipedia_title": "", "wikidata_qid": "", "wikipedia_revid": "",
               "source": NCES_SOURCE.get(g["sector"], "NCES"),
               "license": NCES_LICENSE}
        m = matches.get(sid)
        if m:
            w = wiki_text.get(m["pageid"])
            if not w or not w.get("text"):
                stats["no_text"] += 1
            elif len(w["text"]) < min_chars:
                stats["short_text"] += 1
            elif describes_closed_school(w["text"]):
                stats["closed_school"] += 1
            else:
                title = w.get("title") or m["title"]
                row.update({
                    "text": w["text"], "from_wikipedia": 1,
                    "wikipedia_title": title, "wikidata_qid": m["qid"],
                    "wikipedia_revid": str(w.get("revid") or ""),
                    "source": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                    "license": WIKI_LICENSE,
                })
        rows.append(row)
    return rows, stats


def card_values(rows, matches, wiki_text, stats):
    """Numbers for the dataset card template (README.md @@tokens@@)."""
    import statistics
    n = len(rows)
    wiki = [r for r in rows if r["from_wikipedia"] == 1]
    ids = {r["nces_id"] for r in rows}
    methods = {}
    for sid, m in matches.items():
        if sid in ids:
            methods[m["method"]] = methods.get(m["method"], 0) + 1
    per_state = {}
    for r in rows:
        t = per_state.setdefault(r["state"], [0, 0])
        t[0] += 1
        t[1] += r["from_wikipedia"]
    cov = sorted((w / t, st) for st, (t, w) in per_state.items() if t >= 100)

    def fmt(items):
        names = [f"{100 * c:.1f}% ({USPS_TO_NAME.get(st, st)})"
                 for c, st in items]
        return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)

    used = {r["wikipedia_title"] for r in wiki}
    dates = sorted((w.get("fetched_at") or "")[:10] for w in wiki_text.values()
                   if w.get("title") in used and w.get("fetched_at"))
    fetched = (dates[0] if dates and dates[0] == dates[-1]
               else f"{dates[0]} to {dates[-1]}" if dates else "n/a")
    pct = lambda k: f"{100 * k / max(n, 1):.1f}"                       # noqa: E731
    return {
        "rows": f"{n:,}", "wiki_n": f"{len(wiki):,}", "wiki_pct": pct(len(wiki)),
        "nces_n": f"{n - len(wiki):,}", "nces_pct": pct(n - len(wiki)),
        "matched_pct": pct(sum(methods.values())),
        "public": f"{sum(r['sector'] == 'public' for r in rows):,}",
        "private": f"{sum(r['sector'] == 'private' for r in rows):,}",
        "states": str(len(per_state)),
        "text_m": f"{sum(len(r['text']) for r in rows) / 1e6:.1f}",
        "ccd_year": DATA_YEAR["public"], "pss_year": DATA_YEAR["private"],
        "fetched": fetched,
        "coverage_low": fmt(cov[:3]) if cov else "n/a",
        "coverage_high": fmt(cov[-2:]) if cov else "n/a",
        **{f"m_{k}": f"{methods.get(k, 0):,}"
           for k in ("nces_id", "nces_id_stale", "name_state", "fuzzy", "geo")},
        "closed_n": f"{stats['closed_school']:,}",
        "notext_n": f"{stats['no_text'] + stats['short_text']:,}",
        "median_wiki": f"{statistics.median(len(r['text']) for r in wiki):,.0f}" if wiki else "n/a",
        "median_nces": f"{statistics.median(len(r['text']) for r in rows if not r['from_wikipedia']):,.0f}",
    }


def render_card(template_path, values):
    """Fill README.md's @@token@@ placeholders; drop the template comment."""
    text = open(template_path, encoding="utf-8").read()
    text = re.sub(r"<!-- Template:.*?-->\n", "", text, flags=re.S)
    for k, v in values.items():
        text = text.replace(f"@@{k}@@", v)
    left = sorted(set(re.findall(r"@@(\w+)@@", text)))
    if left:
        sys.exit(f"README.md has unfilled tokens: {left}")
    return text


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_parquet_shards(dirpath, rows, shards):
    """Write rows as `articles-0000i-of-0000N.parquet`; returns the file list."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([(f, pa.int8() if f == "from_wikipedia" else pa.string())
                        for f in FIELDS])
    os.makedirs(dirpath, exist_ok=True)
    for old in glob.glob(os.path.join(dirpath, "*.parquet")):
        os.remove(old)
    shards = max(1, min(shards, len(rows)))
    size = -(-len(rows) // shards)
    paths = []
    for i in range(shards):
        chunk = rows[i * size:(i + 1) * size]
        path = os.path.join(dirpath, f"articles-{i:05d}-of-{shards:05d}.parquet")
        pq.write_table(pa.table({f: [r[f] for r in chunk] for f in FIELDS},
                                schema=schema), path)
        paths.append(path)
    return paths


def _sha256(path):
    h = hashlib.sha256()
    files = ([path] if os.path.isfile(path)
             else sorted(glob.glob(os.path.join(path, "*.jsonl"))))
    for fp in files:
        with open(fp, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
    return h.hexdigest()


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main():
    ap = argparse.ArgumentParser(description="Build the articles dataset for Hugging Face.")
    ap.add_argument("--master", default=DEFAULT_MASTER,
                    help="NCES all-schools master; NCES text is rendered from it")
    ap.add_argument("--articles", default=None,
                    help="use a pre-rendered article JSONL (file or dir) instead of "
                         "rendering from --master")
    ap.add_argument("--matches", default=DEFAULT_MATCHES, help="wiki<->NCES match CSV")
    ap.add_argument("--wiki-text", default=DEFAULT_WIKI_TEXT,
                    help="Wikipedia text JSONL from fetch_article_text.py")
    ap.add_argument("--min-chars", type=int, default=200,
                    help="shorter Wikipedia texts fall back to NCES text (default 200)")
    ap.add_argument("--state", help="build a single-state slice (2-letter code)")
    ap.add_argument("--skip-match", action="store_true",
                    help="NCES-only build: no Wikipedia join, every row CC0")
    ap.add_argument("--shards", type=int, default=3, help="Parquet shard count")
    ap.add_argument("--dist", default=DIST_DIR, help="output tree to upload")
    args = ap.parse_args()
    state = args.state.upper() if args.state else None

    generated = (load_generated(args.articles) if args.articles
                 else render_generated(args.master))
    if args.skip_match:
        matches, wiki_text = {}, {}
    else:
        matches, wiki_text = load_matches(args.matches), load_wiki_text(args.wiki_text)
        check_matches_against_master(matches, generated)
    rows, stats = build_rows(generated, matches, wiki_text, args.min_chars, state)
    if not rows:
        sys.exit("no rows to write")

    if os.path.isdir(args.dist):
        shutil.rmtree(args.dist)
    os.makedirs(args.dist)
    shards = write_parquet_shards(os.path.join(args.dist, "data", "articles"), rows,
                                  args.shards)
    write_jsonl(os.path.join(args.dist, "articles.jsonl"), rows)
    for name in CARD_FILES:
        if name == "README.md":
            card = render_card(os.path.join(HERE, name),
                               card_values(rows, matches, wiki_text, stats))
            with open(os.path.join(args.dist, name), "w", encoding="utf-8") as fh:
                fh.write(card)
        else:
            shutil.copy(os.path.join(HERE, name), os.path.join(args.dist, name))

    n = len(rows)
    n_wiki = sum(r["from_wikipedia"] for r in rows)
    summary = {
        "rows": n,
        "public": sum(r["sector"] == "public" for r in rows),
        "private": sum(r["sector"] == "private" for r in rows),
        "states": len({r["state"] for r in rows}),
        "from_wikipedia_1": n_wiki,
        "from_wikipedia_0": n - n_wiki,
        "matched_without_usable_text": stats["no_text"] + stats["short_text"],
        "matched_to_closed_school_article": stats["closed_school"],
        "text_chars": sum(len(r["text"]) for r in rows),
    }
    inputs = ({"generated_articles": args.articles} if args.articles
              else {"nces_master": args.master})
    if not args.skip_match:
        inputs.update(matches=args.matches, wiki_text=args.wiki_text)
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_head": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "argv": sys.argv[1:],
        "data_year": DATA_YEAR,
        "inputs": {k: {"path": os.path.relpath(v, HERE), "sha256": _sha256(v)}
                   for k, v in inputs.items()},
        "summary": summary,
        "shards": [os.path.relpath(p, args.dist) for p in shards],
    }
    with open(os.path.join(OUT_DIR, "build_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    sys.stderr.write(
        f"\nwrote {n:,} rows -> {args.dist} ({len(shards)} parquet shards + jsonl)\n"
        f"  from_wikipedia=1 : {n_wiki:,} ({100 * n_wiki / n:.1f}%)\n"
        f"  from_wikipedia=0 : {n - n_wiki:,}\n"
        f"  matched but no usable Wikipedia text: {stats['no_text']:,} missing, "
        f"{stats['short_text']:,} under {args.min_chars} chars, "
        f"{stats['closed_school']:,} describe a closed school (-> NCES text)\n"
        f"  total text: {summary['text_chars'] / 1e6:.1f}M chars\n"
        f"  manifest -> {os.path.join(OUT_DIR, 'build_manifest.json')}\n"
        f"next: python validate_publish.py\n"
    )


if __name__ == "__main__":
    main()
