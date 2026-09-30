# Wikipedia school articles

Finds US K-12 school articles on English Wikipedia, verifies that each one really
is a school, enriches it with Wikipedia/Wikidata facts, and fetches the article
text for those that match an NCES school. Matching itself lives in
[`../data_publish/match_wiki_nces.py`](../data_publish/match_wiki_nces.py); the
whole pipeline is driven by [`../Makefile`](../README.md).

## Steps

| Step | Script | Reads | Writes (in `output/`) | Time |
|---|---|---|---|---|
| 1. crawl | `crawl_k12_schools.py` | Wikipedia category tree + Wikidata | `schools.csv` | hours |
| 2. enrich | `enrich_schools.py` + `revalidate_rules.py` | `schools.csv`, NCES coordinates | `schools_enriched.csv` | ~40 min (rules alone: seconds) |
| 3. match | `../data_publish/match_wiki_nces.py` | `schools_enriched.csv`, NCES master | `../data_publish/output/wiki_nces_matches.csv` | seconds |
| 4. text | `fetch_article_text.py` | `schools_enriched.csv`, the matches | `wiki_articles.jsonl` | ~1.8 s / article |

```bash
cd ..                      # data/
make crawl                 # step 1  (python wiki_crawl/crawl_k12_schools.py --include-defunct)
make enrich                # step 2
make                       # steps 3-4 and the release, incrementally
```

Scripts read and write `output/` by default (a bare `--in`/`--out` name resolves
there). All network access goes through `../common/wiki_api.py` (retries,
429/503 `Retry-After`, `maxlag` backoff, one User-Agent). `crawl` and `enrich`
take `--proxy http://127.0.0.1:7890`.

## 1. Crawl — `crawl_k12_schools.py`

Breadth-first walk from 15 seed categories ("Schools in the United States", level-,
private-, Catholic-, charter-, boarding- …) down to depth 6, entering only
subcategories named like schools and skipping universities, alumni, sports,
buildings, "established in YEAR" and similar branches. `--include-defunct` also
seeds "Defunct schools in the United States" (the release uses it). Candidates
are de-duplicated by pageid; the run checkpoints and resumes with `--resume`.

Every candidate is then tagged from its Wikidata item (`instance_of`, dissolution
date) — nothing is dropped:

| `validation` | Meaning |
|---|---|
| `school` | a school type in Wikidata, no dissolution date |
| `defunct` | a school type with a dissolution date |
| `out_of_scope` | a school district or higher-education institution |
| `non_school` | anything else: people, events (school shootings), buildings, … |
| `unverified` | no Wikidata item or no usable type |

## 2. Enrich — `enrich_schools.py`

- **Resolve redirects.** A redirect to another crawled school (a renamed school)
  collapses onto it. A title that only redirects to its town or district — the
  school has no article of its own — is kept under its own title as
  `validation=redirect` with `redirect_to` set, so the town page never poses as
  a school.
- **Add facts** from Wikipedia (coordinates, description, 60-day pageviews,
  thumbnail, categories) and Wikidata (all types, NCES id, district, founded,
  website, postal code, country, dissolution).
- **Revalidate** (`revalidate_rules.py`, re-runnable offline with
  `--revalidate-only` / `make revalidate`; `--refresh-leads` / `make leads`
  re-fetches only the first sentences). The article's own first sentence
  (`lead`) decides first — "X is a ... school" vs "X was a ..."; every change
  is explained in `validation_note`:
  - fill a missing `state` from the description, then from the nearest NCES
    school to the article's coordinates;
  - `defunct` for pages in a defunct/former/closed-school category (Wikidata
    often lacks the dissolution date);
  - `out_of_scope` for networks/districts, colleges/universities and non-US
    schools (unless a US state is known — Wikidata's country is sometimes wrong);
  - `unverified` → `school` when the description names a school;
  - `operating` = `no` for dissolved, defunct-category, historic-building or
    "former …" articles, else `yes`.

Output columns: `title, url, pageid, state, level, description, instance_of,
founded, website, school_district, nces_id, postal_code, wikidata_qid, lat, lon,
pageviews_60d, thumbnail, source_category, validation, redirect_to,
defunct_category, country, dissolved, operating, validation_note`.

The matcher uses only `validation=school` rows by default and writes the rest of
the kept schools, with a reason, to `../data_publish/output/wiki_unmatched.csv`.

## 4. Article text — `fetch_article_text.py`

One request per article (TextExtracts can't batch full extracts): the full body
as plain text plus the revision id. Trailing sections (References, External
links, See also, Notes, …) and headings are dropped, whitespace is collapsed, and
leftover `{{templates}}`, `[[links]]` and `[12]` citation markers are stripped.

```bash
python fetch_article_text.py --matches ../data_publish/output/wiki_nces_matches.csv
python fetch_article_text.py --reclean     # re-apply cleaning after a fix, no refetch
```

The output doubles as the checkpoint: pages already present are skipped, so a
re-run after new matches fetches only the new articles. Each line:
`{pageid, title, url, revid, text, chars, fetched_at}`.

## Notes

- Filter the CSVs with a CSV-aware tool, never `awk -F,`: titles contain commas
  (`"… High School (Cedar Rapids, Iowa)"`).
- Tests: `pytest` from `data/` runs every suite; the one test that calls the live
  API is marked `integration` and runs only with `pytest -m integration`.
