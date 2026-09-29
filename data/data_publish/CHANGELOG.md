# Changelog

All notable changes to the `us-k12-schools` dataset. Versions correspond to git tags in
the [SchoolData](https://github.com/bxshan/SchoolData) source repository; each entry
records the exact inputs the release was built from so any version can be rebuilt.

## [v0.1] — 2026-09-07

First public release. Single `articles` config: one encyclopedic paragraph per US K–12
school.

### Contents
- **122,675 rows**, one per NCES school ID (100,435 public / 22,240 private, 56 states
  and territories).
- **13,853 rows (11.3%)** with `from_wikipedia = 1` — English Wikipedia lead sections.
- **108,822 rows (88.7%)** with `from_wikipedia = 0` — deterministically rendered from
  NCES public-domain metadata.
- ~59.8M characters of text total.

### Licensing
- Distributed under **CC BY-SA 4.0** (Wikipedia inclusion triggers ShareAlike).
- Per-row `license`: `CC-BY-SA-4.0` for Wikipedia rows, `CC0-1.0` for NCES-generated rows.

### Inputs
| Input | Provenance |
|---|---|
| `data/nces_crawl/output_all_schools/all_schools_master.csv` | commit `420c897` — NCES CCD + PSS, 2023–24 |
| `website/data/wiki_nces_matches.csv` | commit `28614eb` (2026-06-28) — 15,247 Wikipedia↔NCES matches |
| `data/nces_crawl/generate_articles/generate_article.py` | commit `420c897` |
| Wikipedia lead sections | retrieved from the MediaWiki API on **2026-09-07**; per-row `wikipedia_revid` pins each revision |
| Source repo HEAD at build time | `e3acc60` |

### Match quality decisions
- **Level gate applied to all match tiers.** A match is rejected when the Wikipedia
  article's level (elementary / middle / high) cannot overlap the school's NCES grade
  range; the school falls back to generated text. **522 matches dropped.** This targets
  the false-positive class found in the June 2026 pipeline audit, where the matcher's
  stripping of "high"/"elementary" as generic tokens scored `Lincoln High School` at 100
  against `Lincoln Elementary School`.
- Grade ranges are read from the NCES master, never from the matches CSV: private (PSS)
  rows encode grades as opaque numeric codes, so the span is derived from the per-grade
  `PSS_ENROLL_*` columns.
- **164 duplicate NCES ids** resolved by tier priority (`nces_id` > `name_state` >
  `fuzzy`), then match score, then article title. The gate runs before deduplication so a
  rejected top-tier match yields to its runner-up rather than costing the school its text.
- **708 schools** had a Wikipedia match but no usable extract (page deleted or lead too
  short) and fall back to generated text.

### Text processing
- Wikipedia: lead section only (`exintro`), plain text, with unexpanded `{{templates}}`,
  raw `[[wikilinks]]` and inline `[12]` citation markers stripped.
- Generated: deterministic template over NCES fields; clauses omitted when data is absent,
  never guessed.

### Known limitations
See the **Limitations & Biases** section of the dataset card. In brief: Wikipedia coverage
is heavily skewed against rural and under-resourced communities (0.2% in PR vs 22.2% in
AR); generated rows contain only NCES-verifiable facts; fuzzy-tier matches carry residual
risk on rows the level gate cannot judge; NCES data is a 2023–24 snapshot.
