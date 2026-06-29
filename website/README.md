# SchoolData

Every US K-12 school (public + private) on one map — **red = no Wikipedia article
yet**. An open dataset and a call to action for closing the school "data desert."

Live data: **122,618** NCES schools (102,130 public + 20,488 private) · **12.2%**
have an English Wikipedia article — matched by exact Wikidata NCES-id + name/state +
audited fuzzy against a validation-tagged Wikipedia category crawl (the cleaned
crawl drops school-shooting events, people, districts, and other non-school pages
that inflated earlier counts). Private schools are placed via U.S. Census batch
geocoding of their NCES addresses (Wikidata coords as fallback).

## Architecture

"Local heavy-lifting writes, lightweight web reads" — the browser never queries a
database to draw the map.

```
schooldata/
├── pipeline/                 # Python — runs locally / on your workstation
│   ├── crawl_k12_schools.py  #  crawl Wikipedia category tree -> schools.csv
│   │                         #  (two-phase: discover + Wikidata `validation` tag)
│   ├── enrich_schools.py     #  add state/level/Wikidata/NCES-id/coords/pageviews
│   ├── match_wiki_nces.py    #  match clean wiki set -> NCES (id + name + fuzzy)
│   ├── geocode_private.py    #  Census batch-geocode NCES private schools -> coords
│   ├── diag.py               #  category-tree diagnostics
│   └── build_dataset.py      #  pull NCES public (102k, lat/lon) + flag has_wikipedia
│                             #  from wiki_nces_matches.csv; --add-private merges the
│                             #  geocoded private schools -> web/public/data/schools.json
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
Institute Education Data API (free, no key) and flags `has_wikipedia` by an exact
join on the NCES id against `../data/wiki_nces_matches.csv` (the audited matcher
output). To re-flag an existing `schools.json` without re-pulling the API:

```bash
python build_dataset.py --reflag
```

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

- [x] Improve Wikipedia matching (use Wikidata `nces_id` + fuzzy geo/name).
- [x] Add private schools (NCES PSS) to the map (geocoded via U.S. Census batch
      geocoder; `build_dataset.py --add-private` merges them into `schools.json`).
- [ ] Supabase table for `contact_status` + `ai_generated_draft` (write side).
- [ ] Sidebar shows AI-generated draft wikitext to copy-paste.
- [ ] Viewport-based loading (PMTiles / tiled JSON) if dataset outgrows static file.
