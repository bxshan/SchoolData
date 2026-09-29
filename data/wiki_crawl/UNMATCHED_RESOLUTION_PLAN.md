# Wikipedia ↔ NCES Unmatched Schools — Analysis & Resolution Plan

**Date:** 2026-06-29
**Full analysis:** [`docs/unmatched-wiki-nces-analysis.md`](../docs/unmatched-wiki-nces-analysis.md)
**Status:** recommendations only — no code changed yet.

> **Status (2026-09-29, branch `data-pipeline-improvements`).** Most of this plan
> is implemented; numbers below are from the June 2026 run and paths have moved
> (`wiki_crawl/output/schools_enriched.csv`, `data_publish/output/wiki_nces_matches.csv`,
> `nces_crawl/output_all_schools/all_schools_master.csv`).
>
> | Item | Where |
> |---|---|
> | #7 grade-band guard | `match_wiki_nces.py`: NCES grade span vs article level, all name tiers |
> | name_state city conflicts | `match_wiki_nces.py`: `city_compatible` in tiers 2–4 |
> | #8 redirect collapse | `enrich_schools.py`: redirects to non-school pages kept as `validation=redirect` |
> | #9 location extraction | `enrich_schools.py` `revalidate`: state from Wikidata description, then nearest NCES school (P131 not used) |
> | #10 rescue QID-no-P31 | `revalidate`: `unverified` rows whose description names a school |
> | #11 + A2 universities / networks | `revalidate`: higher-ed and network/district descriptions -> `out_of_scope` |
> | A3 foreign (P17) | `revalidate`: non-US country and no US state -> `out_of_scope` |
> | A1 `operating` flag | `revalidate` (P576 / historic P31 / description) + past-tense article lead in `prep_data_publish.py` |
> | B1 geo tier, stale-id crosswalk | `match_wiki_nces.py` tiers `geo` and `nces_id_stale` |
> | B2 `no_nces_record` label | `data_publish/output/wiki_unmatched.csv` with a `reason` column |
> | #12 `--include-defunct` | the September re-crawl uses it (defunct rows are tagged, not matched) |

## TL;DR

Of the **19,469** clean Wikipedia school articles, **15,247 (78%)** match an NCES
record and **4,222 (22%)** do not. The 4,222 split into two families:

- **Family A — not a current US K-12 school (≈2,408, 57%).** These *cannot* match by
  definition (NCES lists only US K-12 schools open in 2023-24). The right move is to
  **filter / label them, not force a match.**
- **Family B — open US K-12 school, unmatched (≈1,814, 43%).** ~700 *are* in NCES
  under a variant name (a fixable **matcher gap**); ~1,100 are genuinely absent from
  NCES (an unfixable **coverage gap** — accept and label).

**Net:** of the 4,222, roughly **~700 are recoverable by improving the matcher**,
**~600 should be filtered out upstream** (foreign + non-school entities), and the
rest (~2,900) are correctly unmatched and should be **labeled, not matched**.

---

## Category-by-category resolution

### A1 · Historical / closed schools — ≈1,819 (43%)
**Problem.** NRHP school buildings, one-room/Rosenwald schools, and schools that
closed or merged. NCES only tracks schools operating in the reference year, so no
current record can exist.
**Resolvable?** No — and we should *not* try. Forcing a match would create false
links.
**Recommendation.** Detect and **label** them as `status = historical/closed`, and
**exclude them from any "data-desert" coverage denominator** (they're not gaps in
NCES; they're history).
**Plan.**
1. In `enrich_schools.py`, add an `operating` flag derived from the article lead:
   `"X was a …"` (past-tense defining verb) + closed/merged/`in operation from…to`
   regexes → `operating = False`. (`is a` ⇒ operating.)
2. Also treat `instance_of ∈ {school building, one-room school, Rosenwald School,
   Labor school}` as historical.
3. Emit the flag as a column; downstream coverage stats filter to `operating=True`.
4. *(Optional, larger)* match historical articles against **older NCES CCD years**
   (downloadable) or NRHP datasets for completeness — separate pipeline.
**Effort:** Low (labeling). **Impact:** removes ~43% of the "unmatched" noise from
coverage metrics.

### A2 · Not an individual K-12 school — ≈579 (14%)
**Problem.** School *districts*, *colleges/universities/seminaries* (NCES tracks
these via **IPEDS**, not CCD/PSS), school **networks/management orgs** (Cristo Rey,
Great Hearts, Noble Schools, Fairfax County Public Schools), and outright non-schools
mis-tagged `instance_of=school` in Wikidata (the *Chicago Public Schools boycott*
event, athletic associations, a student newspaper, *Clown Conservatory*).
**Resolvable?** Yes — these are an **upstream validation leak**; they shouldn't be in
the clean set at all.
**Recommendation.** Tighten the crawler's validation tagger so these are tagged
`out_of_scope` / `non_school` and never reach the clean dataset.
**Plan** (in `crawl_k12_schools.py`, `classify_validation` + regex constants):
1. Add to the higher-ed/out-of-scope guard: `seminary`, `theological`,
   `community college`, `educational institution` **when not** also K-12.
2. Add a **network/district detector**: title ends in `Public Schools` / `Academies`
   / `Schools` **and** the lead says "network/organization/group of schools", or
   `instance_of ∈ {organization, nonprofit organization, voluntary association,
   business}` → `out_of_scope`.
3. Extend `NON_SCHOOL_RE` with event/edge types already seen: `boycott`, `protest`,
   `association`, `newspaper`, `conservatory`.
4. Re-run crawl→enrich; ~579 entities drop out, raising dataset purity.
**Effort:** Medium. **Impact:** removes ~14% false "schools"; also improves the
public map's denominator.

### A3 · Foreign (non-US) schools — ≈10 (0.2%)
**Problem.** UK/China/Canada/Colombia/etc. schools leaked through US-seeded category
crawls. NCES is US-only.
**Resolvable?** Yes — trivially.
**Recommendation.** Filter by Wikidata **country (P17)**: keep only US/territories.
**Plan.**
1. `enrich_schools.py` already hits Wikidata — also pull **P17** and drop rows whose
   country ∉ {USA, PR, GU, VI, AS, MP}.
2. **Guard the known Wikidata bug**: country is occasionally wrong (e.g. *French High
   School*, TX tagged "France"). Only drop as foreign when there is **no US state**
   derivable from the article's categories/title; otherwise trust the US state.
**Effort:** Low. **Impact:** removes ~10 now + prevents future foreign leakage.

### B1 · In NCES under a variant name — matcher gap — ≈700 (17%, bounded 220–1,280)
**Problem.** A real NCES record exists, but the matcher missed it: informal/short
titles, retained former names, athletic/program noise in the title
(*"Auburn High School Tigers"*), or names too different for the fuzzy threshold
(*Harwood Union HS*). **This is the highest-ROI fix — these are recoverable matches.**
**Resolvable?** Yes.
**Recommendation.** Strengthen `match_wiki_nces.py` along four axes.
**Plan.**
1. **Normalization** — expand abbreviations both sides (`Sr/Jr High`→senior/junior,
   `El/Elem`→elementary, `HS/MS`→high/middle, `St.`→Saint, `Mt.`→Mount, `&`→and),
   and strip trailing **athletic/program noise** from titles (`… Tigers`, `…
   football`, `… (alternative program)`).
2. **Geo matching** — the wiki rows have **lat/lon (3,757 of 4,222)**; add a tier that
   matches to the **nearest NCES school within ~1 km** whose name shares ≥1 core
   token. Geography disambiguates where names diverge.
3. **Stale NCES-id crosswalk** — 171 rows carry a Wikidata NCES-id (P2484) that isn't
   in the 2023-24 master (renamed/re-IDed). Resolve via the NCES ID-change crosswalk
   (or match the *old* id to the master's `State School ID`).
4. **City/address-confirmed lower threshold** — when city or coords agree, accept
   fuzzy core scores down to ~80 (today 88/96).
**Effort:** Medium-High. **Impact:** recovers ~700 (up to ~1,280) genuine matches;
lifts overall match rate from 78% toward ~82-85%.

### B2 · Genuinely absent from NCES — coverage gap — ≈1,100 (26%)
**Problem.** Operating US K-12 schools with **no** federal record: private schools
missing from the PSS survey (most of this bucket — 432 "private", Catholic/Christian/
boarding/yeshiva), Puerto Rico private schools (PSS gap), online/micro/Sudbury
schools, and brand-new schools opened after the snapshot.
**Resolvable?** No — NCES does not contain them; matching cannot succeed.
**Recommendation.** **Accept and label** as `nces_status = no_record (notable, not in
NCES)`. Do **not** force matches. Optionally enrich private ones from a secondary
directory.
**Plan.**
1. Tag the residual (post-A/B1 filtering) as `no_nces_record`.
2. *(Optional)* cross-reference private schools against a non-NCES source (state
   private-school registries, NCES PSS is biennial — try the newer release) to fill
   some gaps.
3. These have Wikipedia articles but no NCES point, so they **correctly do not appear
   on the public map** (which is NCES-driven); document that as expected.
**Effort:** Low (labeling). **Impact:** clarifies that ~26% are a *data-source* gap,
not a pipeline defect.

---

## Cross-cutting fixes

- **Location-extraction gap** (~79 rows had no state even when the article states it).
  Harden `enrich_schools.py` state extraction: use Wikidata **P131** (located in
  admin entity) and **reverse-geocode coords**, not just title/category text. Without
  this, real open schools silently fall out of matching.
- **Trust multiple location signals** over any single Wikidata field (P17/P131 +
  coords + category text), since Wikidata has both country and instance-of errors.

## Recommended roadmap (priority order)

| # | Action | Category | Effort | Payoff |
|---|---|---|---|---|
| 1 | Wikidata **country (P17)** filter + bug guard | A3 | Low | removes foreign leakage |
| 2 | Harden **location extraction** (P131 + coords) | cross-cutting | Low | stops silent match drop-out |
| 3 | Tighten **validation** (districts/networks/colleges/events) | A2 | Med | −~579 false schools |
| 4 | Add **`operating` flag**; exclude historical from coverage | A1 | Low | honest coverage metric |
| 5 | Matcher upgrades: **normalization + geo + id-crosswalk** | B1 | Med-High | +~700 matches |
| 6 | Label **`no_nces_record`** residual; optional private enrich | B2 | Low | clarity, not a "bug" |

**Bottom line:** after items 1–5, the ~4,222 unmatched would resolve to roughly
**~700 newly matched**, **~600 filtered out** (foreign + non-school), and **~2,900
correctly labeled** as historical or genuinely-absent — leaving essentially **zero
*unexplained* unmatched articles**, which is the real goal.

---

# Appendix — Full-pipeline audit, agent-verified (recall & precision per stage)

Each stage was **empirically verified** by deploying one auditor agent per stage plus
an adversarial cross-checker (5 agents, ~160 data/API lookups). Verification
**corrected several claims from an earlier hand-pass** — corrections are flagged
inline. Stage counts: `23,366 raw → 19,501 tagged "school" → 19,469 enriched →
15,247 matched`.

## Step 1 — Discovery (`crawl_k12_schools.py`)

**⚠ Correction.** An earlier hand-pass claimed the permit regex
(`_PERMIT_RE = school|academ|yeshiv`) misses many schools via "Education in <state>",
seminary, gymnasium, etc. branches. **Empirically this is ~zero K-12 impact**: those
categories hold policy/concept articles, and every school-named subcategory is also
reachable through the seed-driven "Schools in <state>" hierarchy. (The cited example
"Walnut Grove Elementary School" was *wrong* — no such Wikipedia article exists.) The
`seminar` and `art school` blocklist entries are effectively **dead code** (already
blocked by the permit regex).

**Left out (recall) — the real gap.** The crawl was run **without `--include-defunct`**,
so all 51 "Defunct schools in <state>" categories are pruned → **426 articles absent**
(29.4% of those categories; per-state reproduced: Iowa 39/57, PA 39/86, NY 35/78,
OH 34/89). These are **historical** schools, so they mostly couldn't match current
NCES anyway — **fix = re-run with `--include-defunct`**, no code change. *(High
confidence.)*

**Let in (precision).** The over-broad collection is cleaned downstream by design.
Residual leak into the clean set: **~30 universities tagged `school`** (Tuskegee
University, Georgia Military College, Xavier University of Louisiana — 0.15%, from
Wikidata P31 tie-breaks), plus **~1,079 historic-type** rows (school building /
one-room / Rosenwald — 5.5%; real schools but historical).

## Step 2 — Validation tagging (`classify_validation`)

Four buckets are **excluded before matching ever runs**: `unverified` (1,234),
`non_school` (1,156), `out_of_scope` (977), `defunct` (498).

**⚠ Correction.** An earlier hand-pass implied the whole `unverified` bucket loses
many real schools. The cross-check found the **no-QID half (603) is ~99.7%
redirects** (mostly to school districts), not lost stubs — so that half is *not* a
recall gap (and it overlapped the enrich redirect issue below — a double-count now
removed).

**Left out (recall) — quantified.** The genuine loss is the **QID-bearing-but-no-P31
half**: ≈ **150–190 real active US K-12 schools** wrongly excluded because their
Wikidata item lacks/mistags `instance_of` (confirmed: *Serviam Girls Academy*,
*Starting Gate School*, *Bridge School (CA)*). **Fix:** rescue these via a lead-text
pass ("X is a … school" + US location) and a P31 title-override. *(Medium confidence.)*

**Precision of exclusion — good (≈99%).** Verified: `non_school` = people (373
`human`), churches, `school shooting` events, **disambiguation pages** (*Eminence
High School* is a disambig — correctly out); `out_of_scope` = **887 districts + 82
universities/colleges**. `defunct` (498) correctly isolates historical schools. No
systematic precision leak here.

## Step 3 — Enrich (CLEAN → RESOLVE → ENRICH, `enrich_schools.py`)

This is the pipeline's **largest net recall loss** — verified and quantified.

**Left out (recall).** **131 `school`-tagged articles are dropped** at the RESOLVE step
(redirect-collapse + de-dup by resolved pageid). A 33-article sample found **85% (≈111)
are real schools genuinely lost** (confirmed: *Joliet Montessori School*, *Seacoast
Waldorf School*, *Immaculate Conception Catholic Regional School*); only ~6% are valid
same-school merges. *(High confidence.)*

**Let in (precision) — NEW finding (missed by the hand-pass).** The *same*
redirect-collapse **injects ~99 non-school pages** (≈43 school districts, plus cities
and list-articles) **into** the enriched set. Net change is −131 + 99 = **−32** — so
enrich simultaneously **drops real schools and adds junk**. **Fix:** in
`resolve_and_enrich`, only collapse a redirect when its target is itself a school in
the set — otherwise keep the original and never adopt a non-school target.

- The `CLEAN` church/cemetery filter is **not** a problem — it drops only 4 actual
  churches and keeps all 335 "Catholic … School" titles.
- **146** enriched rows have **no state** (not ~79) though the article states it; ~99
  have a US location in their Wikidata description → they then fail matching. Fix:
  Wikidata **P131** + reverse-geocode (cross-cutting item above).

## Step 4 — Match (`match_wiki_nces.py`)

**⚠ Correction.** An earlier hand-pass said the matcher's precision was "verified
clean." **It is not.** The **fuzzy tier has ~169 hard false positives (13.3% of its
1,268 matches)** — Wikipedia **high-school** articles matched to NCES **elementary**
schools whose grade range has no 9–12; **167 of them score exactly 100.0**. Cause:
the matcher strips generic words including "high"/"elementary", so it ignores level
entirely. *(High confidence — these are wrong points on the public map.)* Plus ~50–70
`name_state` city-conflict misassignments (medium confidence).

**Recall.** ~169 unmatched rows carry a **stale `nces_id`** not in the 2023-24 master.
The body's B1 "~700 recoverable" is an **upper** bound; the verified per-sample
recoverable rate (~8% on 25) puts the realistic figure at a **few hundred**. **Fix:**
add a grade-band/level compatibility guard (never match HS↔elementary; reject a
score-100 with a level mismatch).

## Verified magnitudes & confidence

| Gap | Direction | Magnitude (verified) | Conf. | Fix |
|---|---|---|---|---|
| Match fuzzy HS↔elementary false matches | precision | **~169** (13% of fuzzy) | high | grade-band guard |
| Enrich redirect-collapse drops real schools | recall | **~111** | high | keep school target only |
| Enrich redirect-collapse injects non-schools | precision | **~99** | high | reject non-school targets |
| Validation excludes QID-no-P31 real schools | recall | **~150–190** | med | P31 rescue/override |
| Discovery defunct-guard omits historical | recall | **~426** (historical) | high | `--include-defunct` |
| Enrich empty-state rows blocking match | recall→match | **~99 of 146** | high | P131 + reverse-geocode |
| Universities leaked into clean | precision | **~30** | high | P31 tie-break fix |

Discovery-defunct (426), in-crawl `defunct` (498), and historical-in-`unverified` are
**disjoint** populations — no double-counting.

## Roadmap (revised, by net value)

| # | Action | Step | Effort | Payoff |
|---|---|---|---|---|
| 7 | **Matcher grade-band guard** (reject HS↔elementary) | 4 Match | Low | −~169 wrong matches (bad map points) |
| 8 | **Fix RESOLVE redirect-collapse** (keep school target; drop junk inject) | 3 Enrich | Low-Med | +~111 recall, −~99 precision junk |
| 9 | Harden **location extraction** (P131 + reverse-geocode) | 3 Enrich | Low | unblocks ~99 from matching |
| 10 | **Rescue QID-no-P31** `unverified` schools + P31 title-override | 2 Validation | Med | +~150–190 recall |
| 11 | P31 tie-break: keep `university` as `out_of_scope` | 2 Validation | Low | −~30 precision junk |
| 12 | Re-run with `--include-defunct` (optional) | 1 Discovery | Low | +426 historical (won't match current NCES) |

**Verified takeaway.** Agent verification flipped the headline. The biggest **precision**
problem is the **matcher's ~169 HS↔elementary false matches** (wrong points on the
live map); the biggest **recall** problem is the **enrich redirect-collapse (~111 real
schools dropped, ~99 junk injected)** — *not* the discovery permit regex (~0 impact)
or the `unverified` no-QID half (redirects), which the hand-pass over-weighted.
**Items 7–9 are the high-value, low-effort fixes.**
