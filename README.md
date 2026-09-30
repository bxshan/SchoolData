# SchoolData

**Make every school visible in the age of AI.**

SchoolData is an open-source, student-led initiative — fiscally sponsored by
**Hack Club Bank, a 501(c)(3) nonprofit** — that maps every US K–12 school and
closes the gap leaving thousands of them invisible to the systems shaping our future.

Large language models (ChatGPT, Gemini, …) and search engines learn the world
largely from **Wikipedia and structured web data**. Thousands of US schools have no
comprehensive digital profile — so they are **underrepresented or entirely absent**
from the datasets that train modern AI. We call this the school **"data desert."**

- **~122,000** US K–12 schools — about 100,000 public and 22,000 private.
- Only **about 1 in 8 (≈12%)** has an English Wikipedia article — *visible* to AI.
- The other **~107,000** have **no article at all** — *invisible* to the algorithms.

*Current exact counts, by state, are in the
[dataset card](https://huggingface.co/datasets/SchoolData/us-k12-schools).*

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
Crawl the Wikipedia school-article category tree, verify each article really is a
current school (dropping people, events, districts, colleges and closed schools),
then match articles back to NCES schools — by Wikidata NCES id, name + state,
fuzzy name, or coordinates, each checked against the school's city and grade
span. Every school is flagged `has_wikipedia: 0|1`.

### 3 · Fill the gap — community verification
Federal stats can't capture a school's true legacy. Anyone can open a school and
**verify, not author**: we show the facts we already have (from NCES + Wikipedia)
read-only, and contributors do two high-trust, low-friction things:
1. **Add sources** we can cite — school homepage, news coverage, official materials.
2. **Flag incorrect facts** — every correction must carry a source link.

### 4 · Close the loop — publish an open dataset for AI
Package the curated, community-verified profiles as an **open dataset on
[Hugging Face](https://huggingface.co/datasets/SchoolData/us-k12-schools)**, formatted and licensed for **foundation model
training and fine-tuning**. Instead of waiting for schools to trickle into web
crawls, we put their verified data *directly* into the corpus models learn from —
making every school visible to AI at the source, and turning the data desert into a
reusable public good.

---

## Repository

| Directory | What's there |
|---|---|
| [`data/`](data/README.md) | the data pipeline — NCES, Wikipedia crawl + matching, and the Hugging Face release (`make` builds everything) |
| [`website/`](website/README.md) | the map: Next.js + Deck.gl frontend and the script that builds its data |

## Credits

Boxuan Shan, with support from Claude (Anthropic). Per-change authorship is in
the git history (`Co-Authored-By` trailers).
