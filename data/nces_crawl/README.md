# NCES School Data Scraper

Downloads and combines U.S. K-12 school data from the National Center for
Education Statistics (NCES) into unified master CSVs.

- **Public schools**: NCES Common Core of Data (CCD) — enrollment/staffing
  2024-25, directory (name/address/phone) 2025-26 preliminary
- **Private schools**: NCES Private School Survey (PSS), 2023-24

Last downloaded 2026-09-28.

## Structure

- `download_schools.py` — scraper for public and private schools
- `combine_all_schools.py` — merges downloaded files into the unified all-K-12 master
- `generate_articles/` — deterministically renders a Wikipedia-style article per
  school from the master (see below)
- `{public,private}_school_downloads/` — downloaded Excel files (created at run time)
- `output_{public,private,all}_schools/` — master CSVs
- `output_generated_articles/` — generated article JSONL (git-ignored contents)

## Usage

```bash
# Download (public | private | all). `all` also builds the unified master.
python3 download_schools.py --type all

# Merge already-downloaded files into the unified master (stdlib only, no pandas).
python3 combine_all_schools.py
```

`combine_all_schools.py` normalizes public/private fields to a shared core, adds a
`sector` column, and preserves all sector-specific columns (blank for the other
sector). Grades keep their native encodings — public uses `PK`/`KG`/`01`–`12`,
private uses PSS numeric codes; no cross-sector conversion is applied.

## Output

| File | Schools | Columns | Coverage |
|---|---|---|---|
| `output_public_schools/public_schools_master.csv` | 100,282 | 26 | 50 states + DC + 5 territories |
| `output_private_schools/private_schools_master.csv` | 22,239 | 71 | 50 states + DC |
| `output_all_schools/all_schools_master.csv` | 122,521 | 85 | union of the above |

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
python run_samples.py --n 10                         # 10 random schools -> stdout
python run_samples.py --n -1 --out all_articles.jsonl   # all schools -> output_generated_articles/
```

`run_samples.py` writes JSONL (`{school_id, school_name, sector, state, article}`)
to the fixed `output_generated_articles/` dir (a sibling of `output_all_schools/`) — ready to
seed the open dataset or draft Wikipedia stubs. Pass a bare `--out` name to land it
there; a path with a separator writes elsewhere.

The "As of the <year> school year" clause uses `DATA_YEAR` in
`generate_article.py` (per sector; currently public 2024-25, private 2023-24).
Update it when you re-download a newer NCES release, or pass `--year` for a
one-off run.

## Notes

- Downloaded files are HTML tables saved as `.xls`, parsed with the stdlib
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
- Dependencies: `pip install pandas selenium webdriver-manager`
  (`combine_all_schools.py` and `generate_articles/` need none).

## Author

Boxuan Shan + support from Claude Opus 4.8
