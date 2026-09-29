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

# US K–12 Schools — Open Dataset for the AI Era

One encyclopedic paragraph for **every one of the 122,675 K–12 schools in the United
States**, ready to use as pretraining text.

Ask a language model about a large suburban high school and it will answer. Ask it about
the K–8 school in a rural county of 4,000 people and it has nothing to say — because
nothing about that school was ever written down on the open web. Only about **12%** of
American schools have a Wikipedia article at all, and **11.3%** of the rows here carry
Wikipedia text once unreliable matches are excluded. This dataset covers the rest too,
by deterministically rendering public federal data into prose, so that every school is
visible to a model at the point where models actually learn: the corpus.

```python
from datasets import load_dataset
ds = load_dataset("SchoolData/us-k12-schools", "articles", split="train")
```

## Dataset Summary

| | |
|---|---|
| Rows (one per school) | **122,675** |
| `from_wikipedia = 1` (Wikipedia text) | 13,853 (11.3%) |
| `from_wikipedia = 0` (generated from NCES) | 108,822 (88.7%) |
| Public / private | 100,435 / 22,240 |
| States and territories | 56 |
| Total text | ~59.8M characters |

A single config, `articles`. One row per school, keyed by NCES school ID. Every row has a
`text` field; `from_wikipedia` tells you where that text came from.

## Data Fields

| Field | Type | Description |
|---|---|---|
| `nces_id` | string | NCES school ID — the primary key, unique across the dataset |
| `name` | string | School name as recorded by NCES |
| `state` | string | Two-letter state or territory code |
| `sector` | string | `public` (CCD) or `private` (PSS) |
| `text` | string | The school's encyclopedic paragraph |
| `from_wikipedia` | int8 | `1` = text derived from Wikipedia, `0` = generated from NCES |
| `wikipedia_title` | string | Source article title (`from_wikipedia = 1` only) |
| `wikidata_qid` | string | Wikidata item for the school (`from_wikipedia = 1` only) |
| `wikipedia_revid` | string | Exact source revision id (`from_wikipedia = 1` only) |
| `source` | string | Article URL, or `NCES CCD/PSS 2023-24` |
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
permissive = ds.filter(lambda r: r["from_wikipedia"] == 0)   # 108,822 rows, CC0-1.0
```

### Wikipedia Attribution

> Rows with `from_wikipedia = 1` contain text derived from English Wikipedia, licensed
> **CC BY-SA 4.0**. Each such row links to its source article via `wikipedia_title` /
> `wikidata_qid` / `wikipedia_revid`; authorship is the article's revision history. Text
> was **extracted, trimmed, and cleaned** — it is not verbatim full articles. This dataset
> is redistributed under **CC BY-SA 4.0**.

Concretely, the changes made to Wikipedia content are: only the **lead section** was taken
(via the MediaWiki `extracts` API with `exintro`, not the full article); it was converted
to plain text; and surviving markup — unexpanded `{{templates}}`, raw `[[wikilinks]]`, and
inline `[12]` citation markers — was stripped. Wikipedia content was retrieved on
**2026-09-07**; `wikipedia_revid` pins the exact revision each row was taken from.

### Non-Wikipedia rows

The 108,822 rows with `from_wikipedia = 0` are rendered from NCES public-domain data by a
deterministic template — no language model, no randomness, no inference. Every clause is
optional and appears only when the underlying field exists, so a missing value produces a
shorter sentence rather than a guess. Nothing in these rows is invented.

## Limitations & Biases

**Wikipedia coverage is unevenly distributed, and that is the problem this project exists
to document.** Coverage ranges from 0.2% (Puerto Rico), 3.9% (South Dakota) and 5.5%
(Montana) up to 17.6% (Ohio) and 22.2% (Arkansas). Schools in rural and under-resourced
communities are markedly less likely to have an article. Training on `from_wikipedia = 1`
alone would inherit that bias wholesale.

**Generated rows are thin by construction.** They contain only what NCES records —
location, grade range, district, enrollment, staffing, and for private schools religious
affiliation, demographics and facilities. No history, no notable alumni, no local context.
They establish that a school exists and state verifiable facts about it; they are not a
substitute for a written article.

**Wikipedia matching is imperfect.** Articles are linked to NCES schools by Wikidata NCES
ID (11,254 matches), exact name + state (2,725), or fuzzy name similarity within a state
(1,268). The fuzzy tier is the weakest: a June 2026 audit found it matching high-school
articles to same-named elementary schools, because the matcher strips "high"/"elementary"
as generic tokens before scoring. This release therefore **rejects any match whose
Wikipedia level cannot overlap the school's actual NCES grade range** — 522 matches were
dropped on that basis and those schools fall back to generated text. Residual risk
remains on rows the gate cannot judge: articles that state no level, and schools with no
usable grade range. Treat fuzzy-tier rows as the least reliable part of the dataset.

**A few articles describe an institution larger than the school.** Some Catholic parish
schools link to an article covering the parish church and its school together, so the text
includes material about the church. This affects a small number of rows.

**The data is a snapshot.** NCES figures are from the **2023–24** CCD and PSS collections;
Wikipedia text was retrieved 2026-09-07. Schools open, close, and merge; enrollment moves.

**Text length is modest.** Median 376 characters for Wikipedia rows, 498 for generated
rows — these are paragraphs, not long-form articles.

## Provenance & Fiscal Host

| Source | Contributes | Original license |
|---|---|---|
| NCES Common Core of Data (CCD) 2023–24 | Public school records | US federal work, public domain |
| NCES Private School Survey (PSS) 2023–24 | Private school records | US federal work, public domain |
| Wikidata | NCES ID linkage, QIDs | CC0 |
| English Wikipedia | Lead-section text for 13,853 schools | CC BY-SA 4.0 |

This is a non-profit, community-verified civic data project, fiscally sponsored by
**Hack Club Bank**, a 501(c)(3) organization.

## Reproducing this release

Every stage of this dataset — the NCES crawl, the Wikipedia crawl and matcher, and the
release build — is open source at **[github.com/bxshan/SchoolData](https://github.com/bxshan/SchoolData)**.

The release is a pure function of the repository's data products: same inputs, identical
output, no model and no randomness.

```bash
git clone https://github.com/bxshan/SchoolData
cd SchoolData/data/data_publish

python fetch_wikipedia_extracts.py     # Wikipedia lead sections + revision ids
python prep_data_publish.py            # -> output/dist/data/articles/*.parquet
python validate_publish.py --expect-rows 122000
```

`prep_data_publish.py --state CA` builds a single-state slice; `--skip-match` builds the
NCES-only subset with no Wikipedia join. See `CHANGELOG.md` for the input commit hashes
behind each version.

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
