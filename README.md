# SchoolData

**Make every school visible in the age of AI.**

SchoolData is an open-source, student-led initiative — fiscally sponsored by
**Hack Club Bank, a 501(c)(3) nonprofit** — that maps every US K–12 school and
closes the gap leaving thousands of them invisible to the systems shaping our future.

Large language models (ChatGPT, Gemini, …) and search engines learn the world
largely from **Wikipedia and structured web data**. Thousands of US schools have no
comprehensive digital profile — so they are **underrepresented or entirely absent**
from the datasets that train modern AI. We call this the school **"data desert."**

- **122,618** US K–12 schools — 102,130 public + 20,488 private.
- **14,980 (12.2%)** have an English Wikipedia article — *visible* to AI.
- **107,638 (87.8%)** have **no article at all** — *invisible* to the algorithms.

*As of the stats on June 28, 2026.*

This isn't cosmetic. When a school is missing from the open web, it is effectively
**erased from the AI era**: it can't be summarized, recommended, cited, or
remembered by the tools students, parents, and researchers increasingly rely on.
The cost falls hardest on under-resourced communities, compounding existing
inequity into **algorithmic bias**.

**SchoolData exists to fix the data, not just to flag the problem.** We turn cold
federal statistics into living, community-verified profiles and put every school
back on the public record — so no school is left off the map.

---

## Implementation stages

### 1 · Establish the ground truth — federal data
Build the full **NCES** directory — the Common Core of Data bulk files for ~100k
public schools and the Private School Survey for ~22k private schools, with NCES's
own coordinates. For each school we capture location, district, grade span,
enrollment, teaching staff (→ student–teacher ratio), charter status, and phone.
See [`data/`](data/README.md).

### 2 · Measure the gap — Wikipedia coverage
Crawl the Wikipedia school-article category tree, then match articles back to NCES
schools by exact Wikidata `nces_id` + name/state + audited fuzzy matching (dropping
non-school pages that inflated naive counts). Every school is flagged
`has_wikipedia: 0|1`.

### 3 · Fill the gap — community verification
Federal stats can't capture a school's true legacy. Anyone can open a school and
**verify, not author**: we show the facts we already have (from NCES + Wikipedia)
read-only, and contributors do two high-trust, low-friction things:
1. **Add sources** we can cite — school homepage, news coverage, official materials.
2. **Flag incorrect facts** — every correction must carry a source link.

### 4 · Close the loop — publish an open dataset for AI
Package the curated, community-verified profiles as an **open dataset on
[Hugging Face](https://huggingface.co/datasets)**, formatted and licensed for **foundation model
training and fine-tuning**. Instead of waiting for schools to trickle into web
crawls, we put their verified data *directly* into the corpus models learn from —
making every school visible to AI at the source, and turning the data desert into a
reusable public good.
