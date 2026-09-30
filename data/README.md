# SchoolData — data pipeline

Builds one row per US K–12 school (NCES) with encyclopedic text — the full
Wikipedia article where a verified one exists, otherwise a paragraph rendered
from NCES data — and publishes it as the Hugging Face dataset
[`SchoolData/us-k12-schools`](https://huggingface.co/datasets/SchoolData/us-k12-schools).
The website map (`../website/`) is built from the same NCES data and matches.

## Quick start

```bash
pip install -r requirements.txt
brew install git-lfs && git lfs install && git lfs pull   # data CSVs live in LFS
make            # build data_publish/output/dist/ and validate it
make test       # all test suites
make status     # which outputs exist, and which steps are stale
```

`make` rebuilds a step whenever one of its inputs is newer than its output.
The slow network steps run only when their output is missing; rebuild them on
purpose with `make crawl` (Wikipedia, hours), `make enrich` (~40 min),
`make private` (NCES private schools, ~5 min, Chrome) or `make nces`.

## Pipeline

```
NCES bulk files (CCD 2024-25, EDGE, PSS PUF) ─ build_from_bulk ─▶ public master + coordinates ─┐
NCES PSS search export ─ download_schools --type private ─▶ private master ─────────────────────┤
                                                                   combine_all_schools ◀────────┘
                                                                            │ all_schools_master.csv
Wikipedia categories ─ crawl_k12_schools ─▶ schools.csv (validation-tagged) │
                       enrich_schools ─────▶ schools_enriched.csv ──────────┤
                                                        match_wiki_nces ◀───┘
                                                            │ wiki_nces_matches.csv
                       fetch_article_text ◀─────────────────┤ (+ wiki_unmatched.csv)
                            │ wiki_articles.jsonl           │
                            └──────────▶ prep_data_publish ◀┘ (renders NCES text from the master)
                                              │ output/dist/ + build_manifest.json
                                         validate_publish  → upload dist/ to Hugging Face
```

| Directory | Does | Key outputs |
|---|---|---|
| [`nces_crawl/`](nces_crawl/README.md) | NCES masters, coordinates, NCES article generator | `output_all_schools/all_schools_master.csv`, `school_coordinates.csv` |
| [`wiki_crawl/`](wiki_crawl/README.md) | find, verify and enrich Wikipedia school articles; fetch their text | `output/schools_enriched.csv`, `output/wiki_articles.jsonl` |
| `data_publish/` | match articles to NCES schools; build, validate and document the release | `output/wiki_nces_matches.csv`, `output/dist/` |
| `common/` | shared code: state names/codes/FIPS, the Wikipedia/Wikidata API client | — |

`data_publish/README.md` is the **dataset card template** (what Hugging Face
shows), not developer documentation: `prep_data_publish.py` fills its
`@@tokens@@` with the build's own numbers. `CHANGELOG.md` and `LICENSE` there
ship with the release too.

## Guarantees the build enforces

- **No stale inputs.** NCES text is rendered from the current master at build
  time; a match CSV whose NCES ids aren't all in that master is refused.
- **Match precision.** Only articles verified as schools are matched; name
  matches must agree with the title's city and the school's NCES grade span;
  same-named schools are never picked at random; a closed school's article
  never supplies a current school's text. See `match_wiki_nces.py`'s docstring.
- **Release gate.** `validate_publish.py` checks schema, unique ids, provenance
  and licensing per row, leftover wiki markup, one article per school, level
  conflicts, the rendered card, and (with `--baseline`) per-state row counts
  against the previous release (±5%).
- **Traceability.** `build_manifest.json` records the git commit and the sha256
  of every input; `wikipedia_revid` pins each Wikipedia text.

## Releasing

1. `make` — build and validate.
2. `python data_publish/validate_publish.py --baseline <previous release>` —
   compare state by state against the last published version.
3. Add a `CHANGELOG.md` entry (inputs, counts, what changed), rebuild.
4. Upload `data_publish/output/dist/` to the Hugging Face dataset repo.
