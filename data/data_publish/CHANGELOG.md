# Changelog

All notable changes to the `us-k12-schools` dataset. Versions correspond to git tags in
the [SchoolData](https://github.com/bxshan/SchoolData) source repository; each entry
records the exact inputs the release was built from so any version can be rebuilt.

## [v0.2] — 2026-09-30

Rebuilt from scratch with a pipeline that now lives entirely in the source repository
(`make baseline` in `data/`), on newer NCES data and full Wikipedia articles.

### Contents
- **122,476 rows**, one per NCES school ID (100,237 public / 22,239 private, 56 states
  and territories).
- **15,163 rows (12.4%)** with `from_wikipedia = 1` — **full** English Wikipedia articles
  (median 1,978 characters; v0.1 used lead sections only, median 376).
- **107,313 rows (87.6%)** with `from_wikipedia = 0` — rendered from NCES data
  (median 490 characters).
- ~98.4M characters of text total (v0.1: ~59.8M).

### Changes from v0.1
- **NCES data.** Public schools now come from the CCD **2024-25** bulk files (directory,
  membership, staff, lunch) plus NCES EDGE geocodes, instead of the CCD search tool —
  one consistent school year, schools operating that year. Private schools remain the
  PSS **2023-24**. Enrollment excludes adult-education students; addresses are the
  location address (the search tool exported mailing addresses, often PO boxes).
  Bureau of Indian Education schools are placed in their physical state.
- **Rows.** 122,302 schools are in both versions; 373 v0.1 school IDs are not among
  the schools operating in 2024-25 (closed, inactive, or re-issued IDs) and 174 are
  new.
- **Wikipedia text.** Full article body as plain text (trailing References / External
  links / See also / Notes sections and headings removed; leftover templates, links and
  citation markers stripped), each pinned by `wikipedia_revid`. Retrieved 2026-09-30.
- **Which schools carry Wikipedia text.** 13,412 schools have it in both versions;
  1,691 gain it and 440 lose it; 45 keep it from a different article. Audits of these
  changes found v0.1 errors being corrected: articles about closed schools or listed
  historic buildings attached to a current same-named school, same-named schools in
  another city, high-school articles on elementary schools, a non-profit's article on a
  school, and schools whose article was renamed or merged.
- **Article generator.** Per-sector data years in the text ("As of the 2024-25 school
  year" for public, 2023-24 for private); a "New" school reads "It opened in the …
  school year" instead of a raw NCES status code; no duplicated "located" phrasing.
- **`source`** for NCES rows names the sector and year: `NCES CCD 2024-25` /
  `NCES PSS 2023-24`.

### Inputs
| Input | Provenance |
|---|---|
| Source repository | commit `fb79f08` (clean working tree) |
| NCES master | `data/nces_crawl/output_all_schools/all_schools_master.csv`, sha256 `1bd68f4f…` — CCD 2024-25 bulk files (`ccd_sch_029/052/059/033_2425`, EDGE 2425), PSS 2023-24 |
| Wikipedia crawl | category tree crawled 2026-09-30 with `--include-defunct` — 24,048 candidates, Wikidata-tagged |
| Matches | `data_publish/output/wiki_nces_matches.csv`, sha256 `0fc09a85…` — 15,164 matches |
| Wikipedia text | `wiki_crawl/output/wiki_articles.jsonl`, sha256 `10734c9b…` — 15,164 articles, retrieved 2026-09-30 |

Full sha256 values and counts are in `build_manifest.json` from the build.

### Match quality decisions
- **Only verified, current schools are matched.** Each crawled article is tagged from
  Wikidata and then revalidated from its own first sentence: "X is a … school" is open;
  "X was a …", "is a historic … building", or a defunct/disestablished category (when
  the first sentence doesn't say otherwise) is closed. Closed schools, listed buildings,
  people, events, school districts and networks (judged by the head noun of the first
  sentence: "a public charter school network" vs "a public high school in the … school
  district"), colleges, concept articles ("a type of school") and titles that only
  redirect to a town are not matched.
- **Tiers:** Wikidata NCES id (11,213), re-issued NCES id (69), exact name + state
  (2,605), fuzzy name (697), and nearest NCES school within 1 km sharing a distinctive
  name word (580).
- **Checks on every candidate:** the article's level words must fit the school's NCES
  grade span (all tiers, including Wikidata ids — 4 ids pointing at a different-level
  school were rejected); the title's city must not contradict the school's; same-named
  schools are resolved by city or coordinates, never by file order; in the fuzzy and geo
  tiers, school-type words must agree ("Blue Valley Academy" is not "Blue Valley Virtual
  Program"), and a program housed in a school is not that school's article.
- **One article per school:** strongest tier, then score, then pageviews.
- Unmatched verified schools are listed with a reason in `wiki_unmatched.csv`
  (1,648 open schools with no NCES record or a very different name; 1,500 closed or
  historic; 60 lost to a stronger match; 12 with no location).

### Reproducibility
v0.1 was built by scripts outside the source repository and cannot be rebuilt exactly.
From v0.2 every step is in the repository: `cd data && make baseline` rebuilds the
release and compares it state by state with the version on Hugging Face. A full rebuild
from scratch reproduced the NCES masters byte for byte and the match set exactly, apart
from one Wikipedia article created between runs.

### Known limitations
Wikipedia coverage remains heavily skewed (see the dataset card). The fuzzy and geo tiers
are the least reliable: an audit of matches new in this version found about 3% wrong
after the final tightening, mainly where names differ only in generic words. About 1,650
open schools with Wikipedia articles are still unmatched, an estimated 40% of them in
NCES under a substantially different name.

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
