# Wikipedia K-12 School Crawler

Crawls Wikipedia for U.S. K-12 school articles, enriches them, and matches them
against the NCES master to measure Wikipedia coverage.

- **Source**: Wikipedia category tree via the MediaWiki API + Wikidata
- **Goal**: flag which NCES schools have an English Wikipedia article

## Structure

- `crawl_k12_schools.py` — walk the Wikipedia category tree → tagged `schools.csv`
- `enrich_schools.py` — clean + add state/level/Wikidata QID/coordinates
- `match_wiki_nces.py` — match the clean wiki set to NCES (id + name/state + fuzzy)
- `output/` — all generated CSVs (git-ignored)
- `tests/` — pytest suite for the crawler

## Usage

```bash
# 1. Crawl (all rows, each tagged in a `validation` column; nothing dropped).
python crawl_k12_schools.py

#    Emit only verified schools directly (CSV-safe):
python crawl_k12_schools.py --out schools_clean.csv --write-status school

# 2. Enrich → adds state, level, Wikidata QID, lat/lon.
python enrich_schools.py

# 3. Match against the NCES master.
python match_wiki_nces.py
```

Every script reads and writes in `output/` by default (a bare `--in`/`--out`/
`--wiki` name resolves there; pass a path with a separator to use another
location). The three stages chain with no flags: `output/schools.csv` →
`output/schools_enriched.csv` → `output/wiki_nces_matches.csv`.

Only dependency beyond the standard library is `requests` (`pip install requests`).
All scripts accept `--proxy http://127.0.0.1:7890` for a local proxy.

## Output (in `output/`)

| File | Produced by | Contents |
|---|---|---|
| `schools.csv` | `crawl_k12_schools.py` | ~23k rows, each tagged in `validation` |
| `schools_enriched.csv` | `enrich_schools.py` | resolved + state/level/QID/coords |
| `wiki_nces_matches.csv` | `match_wiki_nces.py` | wiki→NCES matches with confidence score |

The `validation` column tags every crawled row — `school`, `unverified`,
`defunct`, `out_of_scope`, or `non_school`. Nothing is dropped at crawl time;
leaks are **labeled, not removed**, so the clean set is reproduced by filtering
on `validation == school` (keep `unverified` too while reviewing).

Matching is tiered — exact Wikidata NCES-ID → exact name+state → fuzzy name
similarity within the same state (rapidfuzz, `difflib` fallback). The score
column lets low-confidence rows be reviewed or filtered.

## Notes

- **Filter with a CSV-aware tool** — never `awk -F,`. School titles contain commas
  (e.g. `"... High School (Cedar Rapids, Iowa)"`) and a naive split silently drops
  real schools. CSV-safe one-liner to filter an existing `schools.csv`:
  ```bash
  python -c "import csv,sys; r=csv.DictReader(open('schools.csv')); \
  w=csv.DictWriter(sys.stdout,fieldnames=r.fieldnames); w.writeheader(); \
  [w.writerow(x) for x in r if x['validation']=='school']" > schools_clean.csv
  ```
- The crawler prunes off-topic branches (universities, alumni, sports, buildings,
  "established in YEAR", …) to stay on K-12; results are de-duplicated by pageid.
