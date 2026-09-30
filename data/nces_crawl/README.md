# NCES School Data

Builds U.S. K-12 school data from the National Center for Education Statistics
(NCES) into unified master CSVs.

- **Public schools**: NCES Common Core of Data (CCD) **2024-25** bulk files
  (directory, membership, staff, lunch) + NCES EDGE geocodes — one consistent
  school year, schools operating that year
- **Private schools**: NCES Private School Survey (PSS) **2023-24**, via the PSS
  search export; coordinates from the PSS public-use file

Last built 2026-09-29.

## Structure

- `build_from_bulk.py` — **public master from NCES bulk files** (default) + the
  coordinates file for public and private schools
- `download_schools.py` — search-tool scraper; used for **private** schools, and
  kept as a fallback for public ones (slow: ~2 h, see Notes)
- `combine_all_schools.py` — merges the two masters into the unified all-K-12 master
- `bulk_downloads/` — NCES bulk zips (git-ignored)
- `generate_articles/` — deterministically renders a Wikipedia-style article per
  school from the master (see below)
- `private_school_downloads/` — the scraper's per-state `.xls` files (git-ignored)
- `output_{public,private,all}_schools/` — master CSVs

## Usage

```bash
python3 build_from_bulk.py --download        # public master + coordinates (~1 min)
python3 download_schools.py --type private   # private master (~5 min, Chrome)
python3 combine_all_schools.py               # unified master (stdlib only)
```

Or from `data/`: `make nces`, `make private`, and `make` rebuilds the unified
master whenever either input changes.

To move to a new school year, update `YEAR` and the file URLs in
`build_from_bulk.py` (listed at https://nces.ed.gov/ccd/files.asp) and
`DATA_YEAR` in `generate_articles/generate_article.py`.

`combine_all_schools.py` normalizes public/private fields to a shared core, adds a
`sector` column, and preserves all sector-specific columns (blank for the other
sector). Grades keep their native encodings — public uses `PK`/`KG`/`01`–`12`,
private uses PSS numeric codes; no cross-sector conversion is applied.

## Output

As of the 2026-09-29 build:

| File | Schools | Columns | Coverage |
|---|---|---|---|
| `output_public_schools/public_schools_master.csv` | 100,237 | 26 | 50 states + DC + 5 territories |
| `output_private_schools/private_schools_master.csv` | 22,239 | 71 | 50 states + DC |
| `output_all_schools/all_schools_master.csv` | 122,476 | 85 | union of the above |
| `output_all_schools/school_coordinates.csv` | 122,747 | 4 | lat/lon for public (EDGE) + private (PSS) |

Public numbers are plain values; blank means NCES reported the value missing or
not applicable. (Masters built by the older search scrape used the NCES symbols
`†` / `–` / `‡` instead; the downstream readers accept both.)

Common core fields: school/district IDs, name, grade range, address, phone,
enrollment, teachers, student-teacher ratio, type. Public adds charter status,
locale, and Title I (free/reduced lunch); private adds enrollment by grade,
race/ethnicity, religious affiliation, coed status, and associations.

## Article generation (`generate_articles/`)

Renders a plain-prose, Wikipedia-style article for any school straight from the
master — **deterministic** (same record → same text) and **no invented facts**
(fields absent from NCES are simply omitted). Uses every descriptive column,
including the private-school PSS fields (religious affiliation, coed status,
race/ethnicity, associations, …).

```bash
cd generate_articles
python generate_article.py --id 010135002667        # one school by NCES id
python generate_article.py --name "A C Moore Primary School"
python generate_article.py --demo --year 2022-23      # override the data vintage
python generate_article.py --sample 10 --sector private --seed 3   # random schools
python generate_article.py --sample -1 --jsonl all.jsonl           # every school -> JSONL
```

The sentence-by-sentence rules (which field drives each clause) are in the
module docstring of `generate_article.py`. The release build
(`data_publish/prep_data_publish.py`) calls `render_article()` for every school
directly, so no pre-generated file is needed.

The "As of the <year> school year" clause uses `DATA_YEAR` in
`generate_article.py` (per sector; currently public 2024-25, private 2023-24).
Update it when you re-download a newer NCES release, or pass `--year` for a
one-off run.

## Notes

- The bulk membership zip uses Deflate64, which Python's zipfile can't read;
  `build_from_bulk.py` extracts with the system `unzip`.
- Search-tool downloads are HTML tables saved as `.xls`, parsed with the stdlib
  `html.parser` in `combine_all_schools.py` (no lxml needed).
- The NCES public search is slow (a state's results can take minutes). The
  scraper blocks page assets, polls up to 5 min for results, retries each state
  3× on a fresh Chrome, and **resumes**: finished `<State>_<FIPS>.xls` files are
  reused, so re-running after an interruption only fetches what's missing
  (`--fresh` re-downloads everything). If any state still fails, the master is
  written as `*.partial.csv` and the existing one is left untouched.
- A full public run takes ~2 h; private ~5 min.
- Scripts resolve their download/output dirs next to themselves, so they can be
  run from any working directory.
- Dependencies: `../requirements.txt` (only the scraper needs pandas/selenium;
  `build_from_bulk.py`, `combine_all_schools.py` and `generate_articles/` are
  stdlib-only).
