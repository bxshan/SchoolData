# SchoolData

Every US K-12 school (public + private) on one map — **red = no Wikipedia article
yet**. An open dataset and a call to action for closing the school "data desert."

Live data: STATS_LINE — the same NCES schools and Wikipedia matches as the
[Hugging Face dataset](https://huggingface.co/datasets/SchoolData/us-k12-schools).
Schools come from NCES (CCD 2024-25 public, PSS 2023-24 private) and are placed
with NCES's own coordinates (EDGE geocodes; the PSS public-use file for private
schools). A school is "on Wikipedia" when the audited matcher in
`../data/data_publish/` links it to a verified Wikipedia school article (Wikidata
NCES id, name + state with city/grade-level checks, fuzzy name, or coordinates).

## Architecture

"Local heavy-lifting writes, lightweight web reads" — the browser never queries a
database to draw the map.

```
../data/                      # the data pipeline (shared with the HF dataset)
│   nces_crawl/               #  NCES masters + school_coordinates.csv
│   wiki_crawl/               #  Wikipedia crawl -> enrich
│   data_publish/             #  matcher -> output/wiki_nces_matches.csv
website/
├── pipeline/                 # Python — runs locally / on your workstation
│   ├── build_dataset.py      #  NCES master + coordinates + matches
│   │                         #  -> web/public/data/schools.json (+ coverage JSON)
│   └── geocode_private.py    #  legacy (Census geocoding; --urban path only)
├── data/                     # legacy intermediate artifacts (June 2026 crawl)
│   └── schools_map.html      #  standalone state choropleth (no build needed)
└── web/                      # Next.js + Deck.gl + MapLibre frontend (deploy to Vercel)
    ├── app/                  #  app router pages
    ├── components/SchoolMap.tsx
    └── public/data/schools.json   # static dataset served by the CDN
```

### Why static JSON instead of live DB queries (for the map)

Deck.gl renders 100k+ points on the GPU effortlessly; the real cost is shipping
100k rows from a database on every page load. So the read path is a single
gzipped static file on Vercel's CDN (≈12 MB raw, ≈3 MB gzipped). A database
(Supabase/Postgres + PostGIS) is the source of truth for the **mutable** workflow
(contact status, AI draft wikitext, multi-contributor edits) — phase 2.

## Run the pipeline (local)

Run the data pipeline first (see `../data/nces_crawl/README.md` and
`../data/data_publish/`), then:

```bash
cd pipeline
python build_dataset.py            # regenerates web/public/data/schools.json
python build_dataset.py --reflag   # only re-flag has_wikipedia from new matches
```

`build_dataset.py` reads `../../data/nces_crawl/output_all_schools/` (the
all-schools master and `school_coordinates.csv`) and flags `has_wikipedia` by an
exact join on the NCES id against `../../data/data_publish/output/wiki_nces_matches.csv`.
`--urban` keeps the older Urban Institute API pull as a fallback.

The data CSVs are stored with Git LFS (`brew install git-lfs; git lfs install`);
`web/public/data/*.json` stays in plain git because Vercel serves it directly.

## Run the website (local)

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

## Deploy to Vercel

1. Push this repo to GitHub (public repo, e.g. `SchoolData-Web`).
2. On Vercel: **Add New Project** → import the repo → set **Root Directory** to
   `website/web` → Deploy. Zero config; `git push` auto-redeploys.
3. (Later) Bind a custom domain like `schooldata.org`.

## Roadmap

- [x] Improve Wikipedia matching (use Wikidata `nces_id` + fuzzy geo/name).
- [x] Add private schools (NCES PSS) to the map.
- [x] One NCES source for the map and the HF dataset (CCD bulk files + EDGE).
- [ ] Supabase table for `contact_status` + `ai_generated_draft` (write side).
- [ ] Sidebar shows AI-generated draft wikitext to copy-paste.
- [ ] Viewport-based loading (PMTiles / tiled JSON) if dataset outgrows static file.
