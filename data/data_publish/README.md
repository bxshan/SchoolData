---
license: cc-by-sa-4.0
language: [en]
pretty_name: "US K–12 Schools — Open Dataset for the AI Era"
size_categories: ["100K<n<1M"]
task_categories: [text-generation]
tags: [education, schools, nces, wikipedia, civic-data, k12, united-states]
configs:
  - config_name: articles
    data_files: data/articles/*.parquet
---
<!-- Template: prep_data_publish.py fills every @@token@@ from the build and writes
     the finished card to output/dist/README.md. Edit the prose here, never the
     numbers. -->

# US K–12 Schools — Open Dataset for the AI Era

Encyclopedic text for **every one of the @@rows@@ K–12 schools in the United States**,
ready to use as pretraining text.

Ask a language model about a large suburban high school and it will answer. Ask it about
the K–8 school in a rural county of 4,000 people and it has nothing to say — because
nothing about that school was ever written down on the open web. Only about
**@@matched_pct@@%** of American schools have a Wikipedia article at all, and
**@@wiki_pct@@%** of the rows here carry Wikipedia text once unreliable matches are
excluded. This dataset covers the rest too, by deterministically rendering public federal
data into prose, so that every school is visible to a model at the point where models
actually learn: the corpus.

```python
from datasets import load_dataset
ds = load_dataset("SchoolData/us-k12-schools", "articles", split="train")
```

## Dataset Summary

| | |
|---|---|
| Rows (one per school) | **@@rows@@** |
| `from_wikipedia = 1` (Wikipedia text) | @@wiki_n@@ (@@wiki_pct@@%) |
| `from_wikipedia = 0` (generated from NCES) | @@nces_n@@ (@@nces_pct@@%) |
| Public / private | @@public@@ / @@private@@ |
| States and territories | @@states@@ |
| Total text | ~@@text_m@@M characters |

A single config, `articles`. One row per school, keyed by NCES school ID. Every row has a
`text` field; `from_wikipedia` tells you where that text came from.

## Data Fields

| Field | Type | Description |
|---|---|---|
| `nces_id` | string | NCES school ID — the primary key, unique across the dataset |
| `name` | string | School name as recorded by NCES |
| `state` | string | Two-letter state or territory code (where the school is located) |
| `sector` | string | `public` (CCD) or `private` (PSS) |
| `text` | string | The school's encyclopedic text |
| `from_wikipedia` | int8 | `1` = text from Wikipedia, `0` = generated from NCES |
| `wikipedia_title` | string | Source article title (`from_wikipedia = 1` only) |
| `wikidata_qid` | string | Wikidata item for the school (`from_wikipedia = 1` only) |
| `wikipedia_revid` | string | Exact source revision id (`from_wikipedia = 1` only) |
| `source` | string | Article URL, or `NCES CCD @@ccd_year@@` / `NCES PSS @@pss_year@@` |
| `license` | string | `CC-BY-SA-4.0` or `CC0-1.0` — see Licensing |

## Licensing

**The dataset as a whole is distributed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).**

It mixes two license regimes, and the per-row `license` field records which applies:

| Rows | Origin | Row license |
|---|---|---|
| `from_wikipedia = 1` | English Wikipedia | `CC-BY-SA-4.0` |
| `from_wikipedia = 0` | NCES CCD / PSS — US federal works, public domain | `CC0-1.0` |

Because Wikipedia text is included, ShareAlike propagates to the combined distribution, so
the whole dataset ships as CC BY-SA 4.0. If you need a permissively licensed subset,
filter it out:

```python
permissive = ds.filter(lambda r: r["from_wikipedia"] == 0)   # @@nces_n@@ rows, CC0-1.0
```

### Wikipedia Attribution

> Rows with `from_wikipedia = 1` contain text derived from English Wikipedia, licensed
> **CC BY-SA 4.0**. Each such row links to its source article via `wikipedia_title` /
> `wikidata_qid` / `wikipedia_revid`; authorship is the article's revision history. Text
> was **extracted and cleaned** — it is the article's prose, not its verbatim wikitext.
> This dataset is redistributed under **CC BY-SA 4.0**.

Concretely, the changes made to Wikipedia content are: the **full article body** was taken
as plain text via the MediaWiki `extracts` API (infoboxes, tables and references are not
part of the extract); the *References*, *External links*, *See also*, *Notes*, *Further
reading* and similar trailing sections were dropped; section headings were removed and
whitespace collapsed to single spaces; and surviving markup — unexpanded `{{templates}}`,
raw `[[wikilinks]]`, and inline `[12]` citation markers — was stripped. Wikipedia content
was retrieved on **@@fetched@@**; `wikipedia_revid` pins the exact revision each row was
taken from.

### Non-Wikipedia rows

The @@nces_n@@ rows with `from_wikipedia = 0` are rendered from NCES public-domain data by a
deterministic template — no language model, no randomness, no inference. Every clause is
optional and appears only when the underlying field exists, so a missing value produces a
shorter sentence rather than a guess. Nothing in these rows is invented.

## Limitations & Biases

**Wikipedia coverage is unevenly distributed, and that is the problem this project exists
to document.** Among states with at least 100 schools, coverage ranges from
@@coverage_low@@ up to @@coverage_high@@. Schools in rural and under-resourced communities
are markedly less likely to have an article. Training on `from_wikipedia = 1` alone would
inherit that bias wholesale.

**Generated rows are thin by construction.** They contain only what NCES records —
location, grade range, district, enrollment, staffing, and for private schools religious
affiliation, demographics and facilities. No history, no notable alumni, no local context.
They establish that a school exists and state verifiable facts about it; they are not a
substitute for a written article.

**Wikipedia matching is imperfect.** Articles are linked to NCES schools by Wikidata NCES
ID (@@m_nces_id@@ matches, plus @@m_nces_id_stale@@ through re-issued ids), exact name +
state (@@m_name_state@@), fuzzy name similarity within a state (@@m_fuzzy@@), or the
nearest NCES school within 1 km sharing a name word (@@m_geo@@). Only articles verified as
schools are matched: people, events, districts, networks, colleges, closed schools and
titles that merely redirect to a town page are excluded before matching. Every name-based
match must be consistent with the title's city and with the school's NCES grade span — a
high-school article is never attached to a K–5 school. Articles whose first sentence says
the school *was* something (a closed school) never supply text to a current school
(@@closed_n@@ such matches fell back to generated text, as did @@notext_n@@ matches with a
missing or very short article). Residual risk remains where an article states no level or
place; treat fuzzy- and geo-tier rows as the least reliable part of the dataset.

**A few articles describe an institution larger than the school.** Some Catholic parish
schools link to an article covering the parish church and its school together, so the text
includes material about the church. This affects a small number of rows.

**The data is a snapshot.** Public-school figures are from the **@@ccd_year@@** CCD, private
schools from the **@@pss_year@@** PSS; Wikipedia text was retrieved @@fetched@@. Schools
open, close, and merge; enrollment moves.

**Text length varies by source.** Median @@median_wiki@@ characters for Wikipedia rows (full
articles), @@median_nces@@ for generated rows.

## Provenance & Fiscal Host

| Source | Contributes | Original license |
|---|---|---|
| NCES Common Core of Data (CCD) @@ccd_year@@ + EDGE geocodes | Public school records | US federal work, public domain |
| NCES Private School Survey (PSS) @@pss_year@@ | Private school records | US federal work, public domain |
| Wikidata | NCES ID linkage, QIDs | CC0 |
| English Wikipedia | Article text for @@wiki_n@@ schools | CC BY-SA 4.0 |

This is a non-profit, community-verified civic data project, fiscally sponsored by
**Hack Club Bank**, a 501(c)(3) organization.

## Reproducing this release

Every stage of this dataset — the NCES build, the Wikipedia crawl and matcher, and the
release build — is open source at **[github.com/bxshan/SchoolData](https://github.com/bxshan/SchoolData)**.
Given the same inputs the build is deterministic (no model, no randomness);
`build_manifest.json` in the release records the source commit and the sha256 of every
input.

```bash
git clone https://github.com/bxshan/SchoolData && cd SchoolData/data
git lfs pull                                   # data CSVs are stored in Git LFS

# NCES masters (public from bulk files, private from the PSS search export)
python nces_crawl/build_from_bulk.py --download
python nces_crawl/download_schools.py --type private
python nces_crawl/combine_all_schools.py
python nces_crawl/generate_articles/run_samples.py --n -1 --out articles.jsonl

# Wikipedia: crawl -> enrich -> match -> article text
python wiki_crawl/crawl_k12_schools.py --include-defunct
python wiki_crawl/enrich_schools.py
python data_publish/match_wiki_nces.py
python wiki_crawl/fetch_article_text.py --matches data_publish/output/wiki_nces_matches.csv

# Release
python data_publish/prep_data_publish.py       # -> data_publish/output/dist/
python data_publish/validate_publish.py --expect-rows 120000
```

`prep_data_publish.py --state CA` builds a single-state slice; `--skip-match` builds the
NCES-only subset with no Wikipedia join. See `CHANGELOG.md` for the inputs behind each
version.

## Citation

```bibtex
@misc{us_k12_schools,
  title  = {US K--12 Schools: An Open Dataset for the AI Era},
  author = {Shan, Boxuan and {The School Data Project}},
  year   = {2026},
  url    = {https://huggingface.co/datasets/SchoolData/us-k12-schools},
  note   = {CC BY-SA 4.0. Contains text from English Wikipedia.}
}
```
