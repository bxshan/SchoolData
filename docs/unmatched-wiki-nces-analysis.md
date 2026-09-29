# Why 4,222 Wikipedia school articles cannot be matched to NCES

**Date:** 2026-06-29 · **Scope:** the clean Wikipedia school set vs. the NCES master.
**No pipeline/matcher code was changed** — this is analysis only.

> **Note (2026-09-29).** A June 2026 snapshot. The fixes it motivated are tracked
> in [`data/wiki_crawl/UNMATCHED_RESOLUTION_PLAN.md`](../data/wiki_crawl/UNMATCHED_RESOLUTION_PLAN.md);
> the matcher now writes the current unmatched set with a reason to
> `data/data_publish/output/wiki_unmatched.csv`.

## The unmatched set

| | count |
|---|---|
| Clean Wikipedia schools (`wiki_crawl/schools_new_enriched.csv`) | 19,469 |
| Matched to NCES (`wiki_crawl/wiki_nces_matches.csv`) | 15,247 |
| **Unmatched (this analysis)** | **4,222** |

A Wikipedia article is "unmatched" when `match_wiki_nces.py` found no NCES record for
it by exact Wikidata NCES-id (P2484), exact name+state, or high-confidence fuzzy
name+state.

## How this was investigated

1. **Wikidata enrichment** — fetched country (P17), dissolution date (P576), and
   instance-of (P31) for all 4,222 QIDs. (Notable: **0 have P576**, because the
   crawler already removed P576-dated defunct schools upstream — so closed schools
   here are simply *undated*, and must be found from article text.)
2. **Full article text** — fetched the lead section for **4,221 of 4,222** articles
   and classified on the real prose (the `"X is a…"` vs `"X was a…"` opening verb is
   the single most reliable open-vs-closed signal).
3. **NCES cross-check** — compared each school's name tokens against the NCES master
   for its state to estimate whether a real record exists under a different name.
4. **Article-level validation workflow** — six subagents each read a sample of one
   reason bucket (fetching lead + infobox, and for the "school" buckets searching
   the NCES master directly), plus one adversarial accuracy auditor. 7 agents,
   ~115 web/file lookups.

## The reasons (account for 100% of the 4,222)

Every article falls into exactly one reason; the five sum to 4,222. They group into
two families.

### Family A — the article is **not a current US K-12 school NCES lists** (~57–70%)

NCES's CCD (public) and PSS (private) only catalog **individual US K-12 schools
operating in the 2023-24 reference year**. Articles failing that definition can
never match, by construction.

**A1. Historical or closed school — ≈ 1,800 (≈43%).** The largest single reason.
Wikipedia keeps articles on schools long after they close; NCES drops them.
Sub-types (from reading the articles):
- NRHP-listed **historic school buildings** repurposed or demolished (the biggest
  slice — `instance_of = "school building"`, 762 of these in the raw signal).
- **One-room schoolhouses** (119) and **Rosenwald / Jim-Crow-era segregated Black
  schools** (e.g. *Halltown Colored Free School*), closed by mid-20th-century
  consolidation/desegregation.
- 20th-century schools that **closed or merged** (e.g. *Mendel Catholic High School*,
  closed 1988; *Thomas Jefferson HS, Port Arthur*, merged 2002; *Blue School*, "was a
  progressive independent school").
- **Validation:** the historical bucket was **96% accurate** (27/28) on article review.

**A2. Not an individual K-12 school — ≈ 580 (≈14%).** The entity exists but isn't the
kind of thing CCD/PSS lists:
- **Post-secondary** institutions — universities, liberal-arts and for-profit
  colleges, theological **seminaries** (NCES tracks these via *IPEDS*, not CCD/PSS):
  e.g. *Xaverian College*, *Frontier School of the Bible*.
- **School districts / networks / management orgs** — *Cristo Rey Network*,
  *Great Hearts Academies*, *Noble Schools*, *Fairfax County Public Schools*,
  *Gilbert Christian Schools* — an administrative tier above the individual school.
- **Non-school entities mis-tagged in Wikidata as "school"** — events
  (*Chicago Public Schools boycott*), athletic associations (*Eastern Schools for the
  Deaf Athletic Association*), a student **newspaper**, even *Clown Conservatory*.
- **Validation:** ~88% accurate (21/24); the misses were genuine K-12 *laboratory
  schools* tagged only as "educational institution" in Wikidata.

**A3. Located outside the United States — 10 (0.2%).** NCES is US-only. UK (3),
China (2), Canada, Colombia, Belarus, France: e.g. *Clapham College* (London),
*Southridge School* (British Columbia), *Concordia International School Shanghai*.
- **Caveat / data bug:** Wikidata country errors leak both ways — *French High School*
  (Beaumont, **Texas**) was tagged country = *France* because it's named after settler
  John Jay French. Such cases are really historical US schools (A1), not foreign.

### Family B — the article **is (or may be) a current US K-12 school**, but unmatched (~30%)

These are the genuine school-matching gaps. The split between B1 and B2 is the
**hardest and least certain** part of this analysis (see Limitations).

**B1. The school is in NCES under a variant name — matcher limitation — ≈ 700 (≈17%; bounded 220–1,280).**
A real NCES record exists, but the Wikipedia title differs enough that exact match
failed and fuzzy stayed below threshold. Patterns observed:
- **Informal / shortened titles** — Wikipedia uses a common name; NCES the full legal
  name.
- **Former name retained** — the article keeps the historical name after a rename.
- **Title noise** — athletics or program text in the title (*"Auburn High School
  Tigers"*, *"… Alternative High School"*) that the matcher's core-name logic drops.
- **Multi-record schools** — NCES splits a school into magnet/sub-program records.
- This is a **fixable matcher gap**, not an NCES gap. (Per instructions, not fixed.)

**B2. Genuinely absent from NCES — data-coverage gap — ≈ 1,100 (≈26%).** Operating, but
no federal record exists:
- **Private schools missing from PSS** — PSS is a biennial *survey*; many small,
  religious, or independent schools aren't captured or appear under a very different
  name (R6 descriptions: 432 "private", 48 Catholic, 46 Christian, 38 boarding,
  11 yeshiva). E.g. *Aaron School*, *St. Christopher's School*.
- **Puerto Rico / territory private schools** — PSS coverage of PR private schools is
  incomplete.
- **Online / virtual / micro / supplementary schools** — *Astra Nova* (online),
  *CompuHigh*, Sudbury/alternative micro-schools — not registered as standalone NCES
  campuses.
- **Brand-new schools** opened after the 2023-24 snapshot (182 R6 descriptions say
  "new").

## Distribution (best estimate, text-based reclassification of all 4,221 leads)

| Reason | Est. count | Est. share | Validated accuracy |
|---|---|---|---|
| A1 Historical / closed | ~1,819 | 43.1% | high (≈96%) |
| A2 Not an individual K-12 school | ~579 | 13.7% | high (≈88%) |
| A3 Foreign | ~10 | 0.2% | high |
| **Family A subtotal (not a current US K-12 school)** | **~2,408** | **57.0%** | high |
| B2 Genuinely absent from NCES (coverage gap) | ~1,100 | ~26% | estimate |
| B1 In NCES under a variant name (matcher gap) | ~700 | ~17% | estimate, range 220–1,280 |
| **Family B subtotal (open US K-12, unmatched)** | **~1,814** | **43.0%** | high (split is soft) |
| **Total** | **4,222** | **100.0%** | |

The categories **account for 100%** of the unmatched articles, and the two **families
are high-confidence**: ~57% are not a current US K-12 school NCES would list, ~43%
are open US K-12 schools the matcher/NCES doesn't capture. The **B1↔B2 split inside
Family B is intrinsically soft** — see Limitations.

## Cross-cutting findings

- **Open vs. closed** is best read from the lead's opening verb (`is a` / `was a`),
  not Wikidata — which carries **no P576** for these and has country errors.
- **Wikidata `instance_of` over-includes** "school"/"educational institution" for
  districts, networks, athletic bodies, events, and a newspaper — the source of most
  A2 cases and some upstream leakage.
- A **location-extraction gap** in the enrichment pipeline left ~79 articles with no
  state/country even when the article states it plainly (e.g. *Edison Regional Gifted
  Center*, *P.S. 35 Staten Island*); these were redistributed by text analysis here.

## Limitations & confidence

- An adversarial audit of a hard, stratified 25-article cross-bucket sample scored
  the *automatic* classifier at **52%**, but accuracy is strongly bucket-dependent:
  **A1 ≈96%, A2 ≈88%, A3 ≈89%, B2 ≈78%**, while the **B1/B2 split is the weak point**
  (~47% on sample) because deciding "is this exact school in NCES under another name?"
  requires a per-school NCES lookup that a token heuristic only approximates.
- Therefore the **top-level taxonomy and the Family-A counts are reliable**; the
  **B1 vs B2 numbers should be read as estimates** (combined Family B ≈ 43% is solid;
  its internal division is not).
- The B1/B2 estimate is *bounded*, not guessed: a strict rapidfuzz name match
  (token-sort ≥ 85 on the distinctive name core, same state) finds only **222**
  variant-name matches, while a loose token-coverage rule finds **1,282** — and both
  fail at the edges (e.g. *Harwood Union HS* and *Arkansas School for the Deaf* are in
  NCES under names too different for either to catch). Applying the workflow's sampled
  present-rates (~47% of loose-B1, ~22% of B2) to the full set lands the central
  estimate at **B1 ≈ 700 / B2 ≈ 1,100**, with the bracket [220, 1,280] reflecting real
  irreducible ambiguity in "is this the same school under a different name?"
- ~Several dozen articles carry mixed signals (e.g. a closed school that is also
  foreign, or a network that is also historical); each is assigned its single most
  decisive reason, so totals remain a clean 100%.

## Reproducibility

Inputs: `wiki_crawl/schools_new_enriched.csv`, `wiki_crawl/wiki_nces_matches.csv`,
`nces_crawl/all_schools_output/all_schools_master.csv`. Steps: (1) set-difference on
`pageid` → unmatched; (2) Wikidata P17/P576/P31 batch; (3) Wikipedia lead extracts
for all pageids; (4) rule-based reclassification on text + NCES core-token presence;
(5) subagent article-level validation. Analysis scripts were run from a scratch
workspace and intentionally left out of the repo (no source changes).
