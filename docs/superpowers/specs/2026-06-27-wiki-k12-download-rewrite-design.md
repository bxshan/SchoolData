# Design: Rewrite Wikipedia K-12 School Downloader (`crawl_k12_schools.py`)

**Date:** 2026-06-27
**Status:** Approved design — pending implementation plan
**Reference:** `bxshan/research2026` → `data/full_download_scripts/DownloadWikiHighSchoolsALL.py`

## Problem

The current `wiki_crawl/crawl_k12_schools.py` produces a school list that **leaks
non-school pages**. An audit of the downstream `schools_enriched.csv` (22,942 rows)
found **~747 confirmed non-schools (3.3%)** plus **612 rows with blank
`instance_of`** of unknown status. Confirmed leaks include:

- **School-violence events** — e.g. "2017 Goyases School shooting"
  (`instance_of=massacre`), from seed category *"Columbine High School massacre
  copycat crimes"*.
- **People** — alumni/staff/officials (`instance_of=human`), from categories like
  *"Bryn Mawr School people"*, *"Boston School Committee members"*,
  *"Superintendents of Chicago Public Schools"*.
- **Misc** — films, novels, cities, museums, legal cases, disambiguation pages.

**Root cause (verified in code):** `should_descend()` permits any subcategory whose
name contains "school", so `"… School people"`, `"… School Committee members"`, and
`"Columbine High School massacre copycat crimes"` all pass the filter and their
member pages get collected. Separately, `enrich_schools.py` *computes* `instance_of`
(Wikidata P31) but **never filters on it**, so the non-school rows survive to the
final CSV.

## Goal

Rewrite `crawl_k12_schools.py` into a **two-phase downloader** that emits a
comprehensive list of US K-12 school candidates (public + private, all grade
levels), where **every row is tagged with a verification status** so leaks can be
identified and removed by a later, reversible filter.

## Guiding principle — non-destructive

**The downloader labels; it never silently deletes.** A classifier mistake that
keeps a junk row is cheap (a human deletes it later); a mistake that removes a real
school is expensive (it silently disappears from the dataset). Therefore the default
output **contains every discovered candidate**, each carrying a `validation` status.
Producing the "clean" dataset is then a one-line, auditable filter
(`validation == "school"`) — applied when the user is ready, not baked irreversibly
into the crawl.

## Scope (how each entity type is tagged)

Decided with the user. Note "tagged", not "dropped" — all are written by default:

| Entity type | `validation` tag |
|---|---|
| Operating K-12 schools (public + private, all levels) | `school` |
| Prep / boarding / magnet / charter / college-prep schools | `school` |
| School districts (`instance_of=school district`) | `out_of_scope` |
| Defunct / historical schools (has Wikidata P576 dissolution date) | `defunct` |
| Higher-ed (college, university, law/medical/graduate/business school) | `out_of_scope` |
| Confirmed non-schools (`human`, `*shooting`, `film`, `city`, …) | `non_school` |
| No resolvable Wikidata P31 | `unverified` |

## Architecture

One script, two phases:

```
SEED CATEGORIES
      │
      ▼
┌─────────────────────┐   candidates: {pageid, title, source_category}
│ PHASE 1 — DISCOVER  │   (BFS category walk, light pruning, dedup by pageid)
└─────────────────────┘
      │
      ▼
┌─────────────────────┐   resolve QID → fetch P31 + P576 → assign validation tag
│ PHASE 2 — TAG       │   (no rows dropped; every candidate is written)
└─────────────────────┘
      │
      ▼
  schools.csv (all rows, tagged)
      │
      ▼
  filter validation=="school"  ──▶  enrich_schools.py ──▶ schools_enriched.csv
```

### Phase 1 — Discover

1. **Expand seed roots** to cover all K-12 levels and types. Add to the existing
   High/Secondary/Private/Public/Charter/Catholic + "Schools … by state" master:
   - Middle schools / Junior high schools in the United States
   - Elementary schools / Primary schools in the United States
   - Magnet schools in the United States
   - Boarding schools in the United States
   - Preparatory schools (college-prep) in the United States

2. **`should_descend()` — light, recall-safe pruning only.** Keep the existing
   blocklist that avoids drifting into clearly-irrelevant branches (sports, films,
   buildings-and-structures, by-year buckets, templates/wikiproject meta). We do
   **not** add aggressive person/event category blocks here, because Phase 2 now
   tags those safely — and over-pruning descent risks missing a real school filed
   only under an unusual category. Descent pruning is about crawl efficiency, not
   about deleting candidates.

3. **Title heuristics — minimal.** Keep the existing `List of / Lists of / Index of
   / Outline of / Timeline of` prefix blocklist (these are never individual school
   articles). Do **not** drop year-prefixed or parenthetical-media titles at this
   stage; Phase 2 tags them `non_school` instead, preserving the audit trail.

Phase 1 output: candidate set deduped by `pageid`, each carrying its
`source_category` (first category that found it).

### Phase 2 — Tag (label every candidate; drop nothing)

Mirrors the proven Wikidata logic already in `enrich_schools.py`:

1. **Resolve** each candidate (batch of 50, `redirects=1`) to its Wikidata QID via
   `prop=pageprops&ppprop=wikibase_item`.
2. **Fetch claims** via `wbgetentities` (batch of 50) for:
   - **P31** (instance of) — resolve referenced QIDs to English labels.
   - **P576** (dissolved/abolished/demolished date) — presence ⇒ defunct.
   - **P571** (inception) — best-effort `founded` year.
3. **Assign a `validation` tag** (priority order, first match wins):

A P31 label is a **genuine school type** if it matches the school regex **and is
not** a school district, a higher-ed institution, or a violent event/crime.
Evaluate in this order (first match wins):

| Condition on resolved P31 / P576 | `validation` |
|---|---|
| No QID, or no resolvable P31 label | `unverified` |
| Any **genuine school type**, **with** a P576 dissolution date | `defunct` |
| Any **genuine school type**, no P576 | `school` |
| No genuine school type, but some label is a school district / higher-ed | `out_of_scope` |
| Otherwise (`human`, `film`, `city`, violent events, …) | `non_school` |

A genuine school type **wins over** a co-asserted higher-ed label on multi-value
P31 (favoring recall, consistent with the non-destructive design).

**School regex (positive match):**
`school|academ|gymnasium|yeshiv|lyceum|montessori|seminar|kindergarten|preparat|educational institution`

**Disqualifiers (a label matching these is NOT a genuine school type even if it
contains "school"):**
- school district: `school district`
- higher-ed (but never K-12 prep): `college`, `university`, `law/medical/graduate/business/nursing/art school`, `community/junior college` (guarded so `"… preparatory school"` is kept)
- **violent event/crime: `shooting|massacre|bombing|attack|murder|killing|…`** — critical, because the real Wikidata P31 label for a school shooting is literally `"school shooting"`, which would otherwise match the school regex and leak in.

Note: `instance_of=school building` (963 rows — real schools classified as
buildings) is a genuine school type and is tagged `school`.

**No row is discarded.** Every candidate from Phase 1 appears in the output with
exactly one tag. The leaks are still *identifiable* (tagged `non_school` /
`out_of_scope` / `defunct`) but remain in the file for human verification before any
deletion — and a real school the classifier can't confirm is preserved as
`unverified`, never lost.

## Output schema

Superset of the current 4 columns, so `enrich_schools.py` (which reads only the
columns it needs via `DictReader`) keeps working unchanged on a filtered input:

```
title, url, pageid, source_category, instance_of, wikidata_qid, founded, dissolved, validation
```

- `instance_of` — resolved English P31 label (or "" if unresolved)
- `wikidata_qid` — e.g. `Q5`, or "" if no Wikidata item
- `founded` — year from P571 (best-effort, optional)
- `dissolved` — year from P576 (present ⇒ `defunct`)
- `validation` — exactly one of: `school` | `unverified` | `defunct` | `out_of_scope` | `non_school`

## Producing the clean dataset

Because nothing is dropped at crawl time, the clean list is a downstream filter the
user controls:

```bash
# keep only confirmed operating schools — emit directly (CSV-safe via DictWriter)
python crawl_k12_schools.py --out schools_clean.csv --write-status school
```

The filter must be **CSV-aware** — do not use `awk -F,`. School titles and
categories contain commas (e.g. `"... High School (Cedar Rapids, Iowa)"`,
`"High schools in Washington, D.C."`), which a naive comma split mis-reads,
silently dropping real schools at the cleaning boundary — the exact failure this
design exists to prevent. Use `--write-status`, a `csv`-module one-liner, or
`gawk` with `FPAT`.

`enrich_schools.py` is run on the filtered file. This keeps the destructive step
**explicit, reversible, and auditable** rather than hidden inside the crawl.

## CLI & error handling

**Keep all existing flags:** `--out`, `--max-depth`, `--delay`, `--timeout`,
`--proxy`, `--resume`, `--checkpoint`.

**Add:**
- `--no-validate` — skip Phase 2 entirely (legacy behavior: emit raw candidates,
  `validation` column omitted or blank).
- `--write-status s1,s2,…` — *optional* convenience filter to write only the listed
  statuses (e.g. `--write-status school,unverified`). **Default writes all statuses**
  (non-destructive). This is a convenience, not the primary cleaning path.

**Error handling:**
- Reuse the existing `api_get()` backoff for 429 / 503 / `maxlag`.
- A failed Phase-2 batch tags those candidates `unverified` (kept) rather than
  crashing the run — consistent with "never lose a candidate".
- Reuse the existing checkpoint machinery for Phase 1; Phase 2 runs after Phase 1
  completes.

## Verification plan

1. **Every row tagged:** assert the output has no blank `validation` (except under
   `--no-validate`) and the tag set is exactly the five defined values.
2. **Leaks correctly labeled (not lost):** confirm "2017 Goyases School shooting" is
   present and tagged `non_school`; "Bryn Mawr School people" / superintendent rows
   are present and tagged `non_school`; none are tagged `school`.
3. **Real schools kept and labeled:** confirm a sample across levels
   (elementary/middle/high, public/private) is tagged `school`.
4. **Filter yields a clean set:** `validation=="school"` rows, when audited with the
   `instance_of` audit script, show ~0 non-school `instance_of` values.
5. **Counts:** report the `validation` distribution and compare the `school`-tagged
   count against the old 22,942 to quantify leak removal and added-seed recall.

## Out of scope

- No changes to `enrich_schools.py` (it continues to enrich whatever filtered list
  it is given; it will re-fetch P31 — an accepted minor redundancy).
- No article-text download (that is the reference script's job; not this dataset).
- No changes to the NCES pipeline.
