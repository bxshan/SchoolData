# Author: Boxuan Shan + support from Claude Opus 4.8
#!/usr/bin/env python3
"""Run the deterministic article generator over N schools from the NCES master.

  --n K   render K random schools  (reproducible via --seed)
  --n -1  render ALL schools in the master

Small runs print to stdout; large runs (or --out) write JSONL, one record per
line: {school_id, school_name, sector, state, article}. Files land in the fixed
output_generated_articles/ dir (a sibling of output_all_schools/) unless --out has a path.

Usage:
    python run_samples.py --n 10                          # -> stdout
    python run_samples.py --n 10 --sector private --seed 3
    python run_samples.py --n 25 --out sample.jsonl       # -> output_generated_articles/sample.jsonl
    python run_samples.py --n -1 --out all_articles.jsonl # -> output_generated_articles/all_articles.jsonl
"""

import argparse
import json
import os
import random
import sys
import time

import generate_article as ga

# Generated articles land in a fixed output dir, a sibling of output_all_schools/
# (../output_generated_articles relative to this script). A bare --out filename is placed
# here too; pass a path with a separator to write elsewhere.
HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "..", "output_generated_articles")


def resolve_out(name):
    """Put a bare filename in OUT_DIR; respect any path the user gives."""
    return name if os.path.dirname(name) else os.path.join(OUT_DIR, name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True,
                    help="number of schools to render; -1 = all")
    ap.add_argument("--out", help="JSONL filename (bare name -> output_generated_articles/; "
                                  "default: stdout for small runs, "
                                  "output_generated_articles/articles.jsonl for large ones)")
    ap.add_argument("--sector", choices=["public", "private", "all"], default="all")
    ap.add_argument("--year", default="2021-22")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed for sampling")
    ap.add_argument("--master", default=ga.MASTER)
    args = ap.parse_args()

    if args.n < -1:
        ap.error("--n must be -1 (all) or a non-negative count")

    rows = ga._load(args.master)
    if args.sector != "all":
        rows = [r for r in rows if r.get("sector") == args.sector]
    total = len(rows)

    if args.n == -1:
        picks = rows
    else:
        n = min(args.n, total)
        random.seed(args.seed)
        picks = random.sample(rows, n)
    sys.stderr.write(f"master: {total:,} {args.sector} schools | rendering {len(picks):,}\n")

    # stdout for small ad-hoc runs; a file in output_generated_articles/ for anything sizable
    out_path = args.out or ("articles.jsonl" if len(picks) > 50 else None)
    if out_path:
        out_path = resolve_out(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            for i, r in enumerate(picks, 1):
                f.write(json.dumps({
                    "school_id": r.get("school_id"),
                    "school_name": r.get("school_name"),
                    "sector": r.get("sector"),
                    "state": r.get("state"),
                    "article": ga.render_article(r, args.year),
                }, ensure_ascii=False) + "\n")
                if i % 10000 == 0:
                    sys.stderr.write(f"  {i:,}/{len(picks):,}\n")
        sys.stderr.write(f"wrote {len(picks):,} articles -> {out_path} "
                         f"({time.time() - t0:.1f}s)\n")
    else:
        for i, r in enumerate(picks):
            if i:
                print("\n" + "=" * 78 + "\n")
            print(ga.render_article(r, args.year))


if __name__ == "__main__":
    main()
