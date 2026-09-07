# NCES School Data Scraper

Downloads and combines U.S. K-12 school data from the National Center for
Education Statistics (NCES) into unified master CSVs.

- **Public schools**: NCES Common Core of Data (CCD), 2023-24
- **Private schools**: NCES Private School Survey (PSS), 2023-24

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
| `output_public_schools/public_schools_master.csv` | 100,771 | 27 | 50 states + DC + 5 territories |
| `output_private_schools/private_schools_master.csv` | 22,756 | 72 | 50 states + DC |
| `output_all_schools/all_schools_master.csv` | ~122,936 | 85 | union of the above |

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
python run_samples.py --n 10                         # 10 random schools -> stdout
python run_samples.py --n -1 --out all_articles.jsonl   # all schools -> output_generated_articles/
```

`run_samples.py` writes JSONL (`{school_id, school_name, sector, state, article}`)
to the fixed `output_generated_articles/` dir (a sibling of `output_all_schools/`) — ready to
seed the open dataset or draft Wikipedia stubs. Pass a bare `--out` name to land it
there; a path with a separator writes elsewhere.

## Notes

- Downloaded files are HTML tables saved as `.xls`, parsed with pandas
  `read_html()` (`lxml`). Large states (e.g. California, ~10k schools) need longer
  popup/download timeouts.
- Dependencies: `pip install pandas lxml selenium webdriver-manager`
  (`combine_all_schools.py` needs none).

## Author

Boxuan Shan + support from Claude Opus 4.8
