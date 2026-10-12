# Fact sheets

A fact sheet is a short, sourced profile of one school that the school itself is
asked to confirm. It is how SchoolData turns federal statistics into facts a
school has checked: we do the research, and the school only marks each row
correct or incorrect.

```
NCES master (data/nces_crawl/…/all_schools_master.csv) ─┐
CDE directory ─ fetch_cde.py ─▶ cde_directory.json ───────┤
Wikipedia matches (data/data_publish/output/wiki_nces_matches.csv) ─┤
research/<nces_id>.json (hand research) ──────────────────┴─ build_sheets.py ─▶ sheets/<nces_id>.md
                                                                                 └─▶ gdoc_requests.py ─▶ Google Doc sent to the school

research/ + build_sheets.build_rows() ─▶ ../website/pipeline/build_fact_sheets.py ─▶ school pages
```

- `research/` is the **input**: what was found by hand, with a source link for
  every value, plus the three questions for the school. Edit these.
- `sheets/` is the **output** of `build_sheets.py`. Do not edit it by hand.
- `cde_directory.json` is a cache written by `fetch_cde.py`.

Every file is named by the school's 12-digit NCES id.

## The 15 facts

| # | Fact | Where it comes from | Wikidata |
|---|---|---|---|
| 1 | Official name | NCES; the school's own name if it differs | label, P1448 |
| 2 | School type | NCES + CA Dept. of Education directory | P31 |
| 3 | Grades | NCES | P7086 / P7095 |
| 4 | District | NCES (charters are their own NCES district) | P5353 |
| 5 | Address | NCES | P6375, P625 |
| 6 | Enrollment | NCES | P2196 + P585 |
| 7 | Teachers | NCES | P10610 + P585 |
| 8 | Official website | school / district site | P856 |
| 9 | Year opened | school history page, district records, news; state directory open date as a lead only | P571 |
| 10 | Mascot | school website | P822 |
| 11 | School colors | school website | P6364 |
| 12 | Named after | school history page | P138 |
| 13 | Former names | school history page, award lists | P1448 + P582 |
| 14 | Programs | school website | (dataset only) |
| 15 | Awards and recognitions | official award lists only (CDE, ed.gov, ACS WASC) | P166, P5514 |

Rows 1–7 are the federal layer: `build_sheets.py` generates them from the NCES
master with the dataset's own helpers (`generate_article.py`: title-casing,
grade codes, district names, rounding, `DATA_YEAR`), so a sheet always matches
the Hugging Face release. California schools are cross-checked against the CDE
directory. Rows 8–15 need research; whatever is not found becomes a question for
the school.

Not collected, on purpose: staff names, phone numbers, test scores and
rankings, demographics, and anything about individual students.

## Rules for the research

- **Every value needs a source link that states it.** Open the page; do not
  infer. If nothing states it, write `*Not found*` (or `*None found*`) and leave
  the source empty (`—` on the sheet).
- Rating sites (GreatSchools, Niche, U.S. News) are not sources.
- The state directory's "Open Date" is often an administrative record date
  (many older schools show July 1, 1980). Present it as "state directory open
  date" and ask the school.
- If two sources disagree, keep both in the value and ask the school.
- A school's confirmation is recorded with the sheet, but it is never used as a
  Wikidata reference; only public sources are.

## research/&lt;nces_id&gt;.json

```json
{
  "nces_id": "063398008745",
  "name": "La Paz Middle School",
  "cds_code": "27661596118129",
  "compiled": "2026-10-11",
  "questions": ["What are the school colors?", "...", "..."],
  "facts": [
    {"fact": "Official name", "value": "La Paz Middle School",
     "sources": [{"label": "NCES", "url": "https://nces.ed.gov/..."}, {"label": "School website", "url": "https://lpms.salinasuhsd.org/"}]},
    {"fact": "School type", "value": null, "sources": []},
    {"fact": "Official website", "value": "https://lpms.salinasuhsd.org/",
     "sources": [{"label": "School website", "url": "https://lpms.salinasuhsd.org/"}]}
  ]
}
```

- `facts` has the 15 rows in the order above. Values are Markdown: `[text](url)`
  for links, `*Not found*` for missing facts.
- Rows 1–7: leave `"value": null` and the row is generated from NCES. Give a
  value only for what NCES cannot say — the name a school uses for itself, a
  charter's authorizer, TK — and give it its own sources.
- Row 9 (year opened): if not found, `build_sheets.py` appends the CDE "state
  directory open date" as a lead, with a CDE link.
- `questions` are the three things to ask the school: facts that were not found
  or that need confirming. Do not ask about a fact the table already sources.

## fetch_cde.py

The CDE school directory pages block scripts, but CDE publishes the same
directory as an open GIS layer ("California Public Schools", one layer per school
year), keyed by the NCES school id (`FedID`). `fetch_cde.py` queries it for every
California research file and caches, per school: CDS code, school name, status,
open date, low/high grade, charter, magnet, the website the directory lists, and
the directory year. It does not fetch demographics or test data.

`build_sheets.py` uses the cache to link each school's CDE page, add the open
date to row 9, warn where NCES and CDE disagree (charter, grades, status), and
write a "Directory check" section when the directory lists a different website
than the school's own. Open those links before using them in outreach: some old
addresses redirect to the current site, others are dead.

## Build

```bash
python fetch_cde.py                     # refresh cde_directory.json (California)
python build_sheets.py                  # every research file -> sheets/
python build_sheets.py 063398008745     # one school
```

It warns when NCES and the CDE directory disagree, and when a California school
has no CDE record. The header line of each sheet shows the CDS code, the NCES
school year, and the Wikipedia article and Wikidata item the dataset matched.

To refresh the school pages: `python ../website/pipeline/build_fact_sheets.py`. It
reads `research/` directly and builds the rows with `build_sheets.build_rows()`,
so the pages show the same 15 rows as the sheets; then rebuild the website.

## Google Doc for the school

The doc sent to a school is a copy of a formatted template (page setup, fonts,
and a ✅ Correct / ❌ Incorrect / ❓ Not sure dropdown in the "Your review"
column). Dropdowns cannot be created through the API, so every doc starts as a
copy of the template:

1. In Drive, copy the template into the Fact Sheets folder and name it
   `<School name> — Public Fact Sheet (Draft for Review)`.
2. Read the copy with the Docs API (`documents.get`) and save the JSON.
3. `python gdoc_requests.py COPY.json sheets/<nces_id>.md > requests.json`
4. Send `requests.json` as one `documents.batchUpdate`. It replaces the title,
   the three questions and the Fact / Value / Source cells, and keeps the
   dropdowns and all formatting. It is guarded by the copy's revisionId.
5. Read the doc back and check the table before sharing it.

Template: *La Paz Middle School — Public Fact Sheet (Draft for Review)*, owned by
boxuan.shan@gmail.com. Share each doc only with the school it describes.
