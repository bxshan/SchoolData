# SchoolData

Every US K-12 public school on one map — **red = no Wikipedia article yet**.
An open dataset and a call to action for closing the school "data desert."

Live data: **102,130** NCES public schools · **~16.5%** currently have an English
Wikipedia article (matched by name + state against a full category crawl).

## Architecture

"Local heavy-lifting writes, lightweight web reads" — the browser never queries a
database to draw the map.

```
schooldata/
├── pipeline/                 # Python — runs locally / on your workstation
│   ├── crawl_k12_schools.py  #  crawl Wikipedia category tree -> schools.csv
│   ├── enrich_schools.py     #  add state/level/Wikidata/NCES-id/coords/pageviews
│   ├── diag.py               #  category-tree diagnostics
│   └── build_dataset.py      #  pull NCES (102k, lat/lon) + flag has_wikipedia
│                             #  -> web/public/data/schools.json
├── data/                     # intermediate artifacts
│   ├── schools.csv           #  Wikipedia school articles (~23k)
│   ├── schools_enriched.csv  #  enriched version
│   ├── state_counts.json
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

```bash
cd pipeline
pip install requests
python build_dataset.py            # regenerates web/public/data/schools.json
```

`build_dataset.py` pulls the NCES public-school directory from the Urban
Institute Education Data API (free, no key) and flags `has_wikipedia` by matching
each school against `../data/schools.csv`.

## Run the website (local)

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

## Deploy to Vercel

1. Push this repo to GitHub (public repo, e.g. `SchoolData-Web`).
2. On Vercel: **Add New Project** → import the repo → set **Root Directory** to
   `schooldata/web` → Deploy. Zero config; `git push` auto-redeploys.
3. (Later) Bind a custom domain like `schooldata.org`.

## Roadmap

- [ ] Improve Wikipedia matching (use Wikidata `nces_id` + fuzzy geo/name).
- [ ] Add private schools (NCES PSS).
- [ ] Supabase table for `contact_status` + `ai_generated_draft` (write side).
- [ ] Sidebar shows AI-generated draft wikitext to copy-paste.
- [ ] Viewport-based loading (PMTiles / tiled JSON) if dataset outgrows static file.
