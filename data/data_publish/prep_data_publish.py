# Author: Boxuan Shan + support from Claude Opus 4.8
#!/usr/bin/env python3
"""Build the final `articles` dataset for publishing to Hugging Face.

Combines two pipeline artifacts into one row per school, following the `articles`
schema in `Publish OSS Dataset.md` (§1):

  inputs
    1. Generated articles JSONL  (data/nces_crawl/output_generated_articles/*.jsonl)
       one line per school: {school_id, school_name, sector, state, article}
    2. Wiki<->NCES match CSV      (data_publish/output/wiki_nces_matches.csv)
       gives, per matched school: nces_school_id, wiki_title, wiki_wikidata_qid

  output row (one per school)
    nces_id, name, state, sector, text, from_wikipedia (0/1),
    wikipedia_title, wikidata_qid, wikipedia_revid

Text policy (decided): `text` is the deterministic NCES-generated article for
EVERY school. `from_wikipedia` is 1 when the school has a matched Wikipedia
article (from the match CSV) and 0 otherwise; for from_wikipedia=1 rows we fill
`wikipedia_title` / `wikidata_qid` as attribution pointers. `wikipedia_revid` is
left blank until Wikipedia article text is ingested (a later step may replace the
text of from_wikipedia=1 rows with the real Wikipedia extract).

Writes `output/articles.parquet` (for HF) + `output/articles.jsonl` (human-read).

Usage:
    python data_publish.py
    python data_publish.py --articles /path/to/articles.jsonl --matches /path/out.csv
    python data_publish.py --out articles           # -> output/articles.{parquet,jsonl}
"""

import argparse
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "output")
DEFAULT_ARTICLES = os.path.join(HERE, "..", "nces_crawl",
                                "output_generated_articles")
DEFAULT_MATCHES = os.path.join(OUT_DIR, "wiki_nces_matches.csv")

# Output column order — matches the `articles` schema in Publish OSS Dataset.md §1.
FIELDS = ["nces_id", "name", "state", "sector", "text", "from_wikipedia",
          "wikipedia_title", "wikidata_qid", "wikipedia_revid"]


def load_generated(path):
    """Read generated-article JSONL (a file or a dir of *.jsonl) ->
    dict[nces_id] = {name, state, sector, text}. First occurrence wins."""
    files = ([path] if os.path.isfile(path)
             else sorted(glob.glob(os.path.join(path, "*.jsonl"))))
    if not files:
        sys.exit(f"no generated-article JSONL found at {path}\n"
                 f"  run: cd ../data/nces_crawl/generate_articles && "
                 f"python run_samples.py --n -1")
    out, dups = {}, 0
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                sid = (r.get("school_id") or "").strip()
                text = (r.get("article") or "").strip()
                if not sid or not text or "{{" in text:   # drop empty/placeholder
                    continue
                if sid in out:
                    dups += 1
                    continue
                out[sid] = {
                    "name": r.get("school_name") or "",
                    "state": r.get("state") or "",
                    "sector": r.get("sector") or "",
                    "text": text,
                }
    sys.stderr.write(f"generated articles: {len(out):,} schools "
                     f"from {len(files)} file(s)"
                     f"{f' ({dups} dup ids skipped)' if dups else ''}\n")
    return out


def load_matches(path):
    """Read the wiki<->NCES match CSV -> dict[nces_id] = {title, qid}."""
    if not os.path.exists(path):
        sys.exit(f"match CSV not found at {path}\n"
                 f"  run: python match_wiki_nces.py")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sid = (r.get("nces_school_id") or "").strip()
            if sid:
                out[sid] = {
                    "title": (r.get("wiki_title") or "").strip(),
                    "qid": (r.get("wiki_wikidata_qid") or "").strip(),
                }
    sys.stderr.write(f"wiki matches: {len(out):,} schools have a Wikipedia article\n")
    return out


def build_rows(generated, matches):
    rows = []
    for sid, g in generated.items():
        m = matches.get(sid)
        rows.append({
            "nces_id": sid,
            "name": g["name"],
            "state": g["state"],
            "sector": g["sector"],
            "text": g["text"],
            "from_wikipedia": 1 if m else 0,
            "wikipedia_title": m["title"] if m else "",
            "wikidata_qid": m["qid"] if m else "",
            "wikipedia_revid": "",
        })
    return rows


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_parquet(path, rows):
    """Write Parquet if a backend is available; return True on success."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception:
        sys.stderr.write("  (pyarrow not installed — skipping Parquet; "
                         "pip install pyarrow)\n")
        return False
    cols = {f: [r[f] for r in rows] for f in FIELDS}
    schema = pa.schema([
        (f, pa.int8() if f == "from_wikipedia" else pa.string()) for f in FIELDS
    ])
    pq.write_table(pa.table(cols, schema=schema), path)
    return True


def main():
    ap = argparse.ArgumentParser(description="Build the articles dataset for Hugging Face.")
    ap.add_argument("--articles", default=DEFAULT_ARTICLES,
                    help="generated-article JSONL file or dir (default: "
                         "nces_crawl/output_generated_articles)")
    ap.add_argument("--matches", default=DEFAULT_MATCHES,
                    help="wiki<->NCES match CSV (default: output/wiki_nces_matches.csv)")
    ap.add_argument("--out", default="articles",
                    help="output basename in output/ (default: articles)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    generated = load_generated(args.articles)
    matches = load_matches(args.matches)
    rows = build_rows(generated, matches)

    base = args.out if os.path.dirname(args.out) else os.path.join(OUT_DIR, args.out)
    write_jsonl(base + ".jsonl", rows)
    ok = write_parquet(base + ".parquet", rows)

    n_wiki = sum(r["from_wikipedia"] for r in rows)
    n = len(rows)
    sys.stderr.write(
        f"\nwrote {n:,} rows -> {base}.jsonl"
        f"{' + ' + base + '.parquet' if ok else ''}\n"
        f"  from_wikipedia=1 : {n_wiki:,} ({100 * n_wiki / max(n, 1):.1f}%)\n"
        f"  from_wikipedia=0 : {n - n_wiki:,}\n"
    )


if __name__ == "__main__":
    main()
