#!/usr/bin/env bash
# Full Wikipedia K-12 crawl -> tag -> filter -> enrich -> fetch article text, to NEW files only.
# Run ONCE, detached:   nohup bash run.sh > crawl_new.log 2>&1 &
# Watch:                tail -f crawl_new.log
# Do NOT launch a second copy while one is running (concurrent crawls corrupt
# the shared raw file + checkpoint and trigger 429 rate-limits).
set -euo pipefail
cd /home/bxshan/src/SchoolData/data/wiki_crawl

echo "[1/4] $(date '+%H:%M:%S') full crawl + Wikidata tagging -> schools_new.csv ..."
python crawl_k12_schools.py --out schools_new.csv --max-depth 6 --delay 0.5

echo "[2/4] $(date '+%H:%M:%S') CSV-safe filter (validation==school) -> schools_new_clean.csv ..."
python -c "import csv,sys; r=csv.DictReader(open('schools_new.csv')); \
w=csv.DictWriter(sys.stdout,fieldnames=r.fieldnames); w.writeheader(); \
[w.writerow(x) for x in r if x['validation']=='school']" > schools_new_clean.csv

echo "[3/4] $(date '+%H:%M:%S') enrich -> schools_new_enriched.csv ..."
python enrich_schools.py --in schools_new_clean.csv --out schools_new_enriched.csv

echo "[4/4] $(date '+%H:%M:%S') fetch article plaintext -> schools_new_articles.jsonl ..."
python fetch_article_text.py --in schools_new_enriched.csv --out schools_new_articles.jsonl --delay 0.5

echo "DONE $(date '+%H:%M:%S'). Files: schools_new.csv (all, tagged), schools_new_clean.csv (schools only), schools_new_enriched.csv, schools_new_articles.jsonl (article plaintext)"
