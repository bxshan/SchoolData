# Author: Boxuan Shan, with support from Claude (Anthropic)
# SchoolData data pipeline. Run from data/:
#
#   make            build the release in data_publish/output/dist/ and validate it
#   make test       run every test suite
#   make status     show which outputs exist and how old they are
#
# make rebuilds a step when any input is newer than its output, so a stale
# intermediate can't slip into the release. The slow network steps only run
# when their output is missing — rebuild them on purpose:
#
#   make crawl      re-crawl Wikipedia                  (hours)
#   make enrich     re-enrich the crawl                 (~40 min)
#   make private    re-scrape NCES private schools      (~5 min, needs Chrome)
#   make nces       re-download NCES bulk files and rebuild the public master
#
# Wikipedia article text (wiki_articles.jsonl) is fetched incrementally: only
# newly matched articles are requested (~1.8 s each).

PY ?= python3

PUBLIC   := nces_crawl/output_public_schools/public_schools_master.csv
PRIVATE  := nces_crawl/output_private_schools/private_schools_master.csv
MASTER   := nces_crawl/output_all_schools/all_schools_master.csv
COORDS   := nces_crawl/output_all_schools/school_coordinates.csv
CRAWL    := wiki_crawl/output/schools.csv
ENRICHED := wiki_crawl/output/schools_enriched.csv
MATCHES  := data_publish/output/wiki_nces_matches.csv
WIKITEXT := wiki_crawl/output/wiki_articles.jsonl
DIST     := data_publish/output/dist/README.md

.PHONY: all release validate test status crawl enrich private nces

all: validate

# --- NCES -------------------------------------------------------------------
# build_from_bulk.py writes both files; COORDS rides along with PUBLIC (written
# this way because macOS ships GNU make 3.81, which lacks grouped targets).
$(PUBLIC): nces_crawl/build_from_bulk.py
	$(PY) nces_crawl/build_from_bulk.py --download
$(COORDS): $(PUBLIC)

$(PRIVATE):
	$(PY) nces_crawl/download_schools.py --type private

$(MASTER): $(PUBLIC) $(PRIVATE) nces_crawl/combine_all_schools.py
	$(PY) nces_crawl/combine_all_schools.py

# --- Wikipedia --------------------------------------------------------------
$(CRAWL):
	$(PY) wiki_crawl/crawl_k12_schools.py --include-defunct

# NCES files are only used to infer a missing state, so they don't force a
# 40-minute re-enrich when they change (order-only prerequisites).
$(ENRICHED): $(CRAWL) | $(MASTER) $(COORDS)
	$(PY) wiki_crawl/enrich_schools.py

$(MATCHES): $(ENRICHED) $(MASTER) $(COORDS) data_publish/match_wiki_nces.py common/states.py
	$(PY) data_publish/match_wiki_nces.py

$(WIKITEXT): $(MATCHES) wiki_crawl/fetch_article_text.py
	$(PY) wiki_crawl/fetch_article_text.py --matches $(MATCHES)
	$(PY) wiki_crawl/fetch_article_text.py --reclean
	touch $@

# --- Release ----------------------------------------------------------------
$(DIST): $(MASTER) $(MATCHES) $(WIKITEXT) data_publish/prep_data_publish.py \
         data_publish/README.md data_publish/CHANGELOG.md \
         nces_crawl/generate_articles/generate_article.py
	$(PY) data_publish/prep_data_publish.py

release: $(DIST)

validate: $(DIST)
	$(PY) data_publish/validate_publish.py --expect-rows 120000

# --- Forced rebuilds of the slow steps --------------------------------------
crawl:
	$(PY) wiki_crawl/crawl_k12_schools.py --include-defunct
enrich:
	$(PY) wiki_crawl/enrich_schools.py
private:
	$(PY) nces_crawl/download_schools.py --type private
nces:
	$(PY) nces_crawl/build_from_bulk.py --download

# --- Housekeeping -----------------------------------------------------------
test:
	cd common && $(PY) -m pytest -q tests
	cd nces_crawl && $(PY) -m pytest -q tests
	cd wiki_crawl && $(PY) -m pytest -q -m "not integration" tests
	cd data_publish && $(PY) -m pytest -q tests

status:
	@for f in $(PUBLIC) $(PRIVATE) $(MASTER) $(COORDS) $(CRAWL) $(ENRICHED) \
	          $(MATCHES) $(WIKITEXT) $(DIST); do \
	  if [ -e $$f ]; then printf "  %-62s %s\n" $$f "$$(date -r $$f '+%Y-%m-%d %H:%M')"; \
	  else printf "  %-62s MISSING\n" $$f; fi; done
	@echo "stale (would rebuild):"; $(MAKE) -n release 2>/dev/null | grep -E "^$(PY) " | sed 's/^/  /' || true
