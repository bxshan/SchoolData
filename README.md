# SchoolData

**A consistent, sourced, openly reusable record of every US K–12 school.**

SchoolData is an open-source, student-led initiative — fiscally sponsored by
**Hack Club Bank, a 501(c)(3) nonprofit** — that maps every US K–12 school and
builds one consistent, sourced layer of information about each of them.

Information about US schools already exists, but it is **fragmented**: federal
statistics in NCES, state directories, district and school websites, local news.
It is **inconsistently structured**, and it is **unevenly represented** in the
public knowledge systems that search engines and AI models draw on most,
Wikipedia and Wikidata:

- **~122,000** US K–12 schools — about 100,000 public and 22,000 private.
- About **1 in 8 (≈12%)** has an English Wikipedia article, and most of those are
  high schools: fewer than **2%** of middle and elementary schools have one.
- On Wikidata, only about **12,800** US school items carry an NCES id.

*Current exact counts, by state, are in the
[dataset card](https://huggingface.co/datasets/SchoolData/us-k12-schools).*

So a large high school may have a detailed, cited article, while the middle school
down the road has little beyond a directory listing — and the directory itself can
be out of date. Whether this gap also follows locale or school poverty is something
we are measuring, not assuming.

### What SchoolData adds beyond NCES

NCES already publishes good federal statistics; re-formatting them is not the point.
SchoolData adds the layer around them:

- **Measuring representation** — which schools have a Wikipedia article or a
  Wikidata item, matched to NCES ids, school by school.
- **Reconciling sources** — NCES, state directories and school websites are
  compared, and conflicts are flagged (for example, outdated website links in a
  state directory).
- **Provenance** — every fact carries a link to a public source that states it.
- **Verification** — schools confirm or correct their own fact sheets; contributors
  add sources and flag errors, with a source for every correction.
- **Facts NCES does not carry** — year opened, namesake, former names, mascot,
  programs, awards — only when a public source states them.
- **Reusable outputs** — an open dataset and tools that researchers and developers
  can use, and, where the Wikidata community agrees it fits, structured facts
  contributed back to Wikidata.

---

## Implementation stages

### 1 · Establish the ground truth — federal data
Build the full **NCES** directory — the Common Core of Data bulk files for ~100k
public schools and the Private School Survey for ~22k private schools, with NCES's
own coordinates. For each school we capture location, district, grade span,
enrollment, teaching staff (→ student–teacher ratio), charter status, and phone.
See [`data/`](data/README.md).

### 2 · Measure the gap — Wikipedia coverage
Crawl the Wikipedia school-article category tree, verify each article really is a
current school (dropping people, events, districts, colleges and closed schools),
then match articles back to NCES schools — by Wikidata NCES id, name + state,
fuzzy name, or coordinates, each checked against the school's city and grade
span. Every school is flagged `has_wikipedia: 0|1`.

### 3 · Fill the gap — sourced fact sheets and verification
Federal statistics can't capture a school's history or programs. For each school we
compile a short **fact sheet** — NCES and state-directory facts plus researched
facts, each with its source — and ask the school to confirm it (see
[`fact-sheet/`](fact-sheet/README.md)). Anyone can also open a school and
**verify, not author**: we show the facts we already have (from NCES + Wikipedia)
read-only, and contributors do two high-trust, low-friction things:
1. **Add sources** we can cite — school homepage, news coverage, official materials.
2. **Flag incorrect facts** — every correction must carry a source link.

### 4 · Close the loop — publish an open dataset
Package the curated profiles as an **open dataset on
[Hugging Face](https://huggingface.co/datasets/SchoolData/us-k12-schools)**, one
consistent record per school with its provenance, licensed for research and for
model training. Researchers and developers get the same baseline of sourced facts
for every school, not only for the ones that already have a Wikipedia article.

---

## Repository

| Directory | What's there |
|---|---|
| [`data/`](data/README.md) | the data pipeline — NCES, Wikipedia crawl + matching, and the Hugging Face release (`make` builds everything) |
| [`fact-sheet/`](fact-sheet/README.md) | per-school fact sheets: research inputs, generated sheets (by NCES id), and the Google Doc filler used for school verification |
| [`website/`](website/README.md) | the map: Next.js + Deck.gl frontend and the script that builds its data |
| [`k12-ai-index/`](k12-ai-index/README.md) | K12 AI Index (K12-AII): research code that tests how well major LLMs know schools with vs. without a Wikipedia article |

## Credits

Boxuan Shan, with support from Claude (Anthropic). Per-change authorship is in
the git history (`Co-Authored-By` trailers).
