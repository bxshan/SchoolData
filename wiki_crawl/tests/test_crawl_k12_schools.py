# wiki_crawl/tests/test_crawl_k12_schools.py
import re
import csv
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crawl_k12_schools as ck


def test_seed_categories_cover_all_k12_levels():
    joined = " | ".join(ck.SEED_CATEGORIES).lower()
    for needed in [
        "high schools in the united states",
        "middle schools in the united states",
        "elementary schools in the united states",
        "primary schools in the united states",
        "magnet schools in the united states",
        "boarding schools in the united states",
        "private schools in the united states",
    ]:
        assert needed in joined, f"missing seed: {needed}"


def test_school_regex_matches_school_types():
    for label in ["high school", "school", "private school", "academy",
                  "boarding school", "yeshiva", "school building",
                  "university-preparatory school", "montessori school"]:
        assert ck.SCHOOL_RE.search(label), f"should match: {label}"


def test_school_regex_rejects_clear_non_schools():
    assert not ck.SCHOOL_RE.search("human")
    assert not ck.SCHOOL_RE.search("film")


def test_non_school_re_catches_violent_events():
    # These P31 labels contain "school" (so SCHOOL_RE matches) but are events,
    # not schools. NON_SCHOOL_RE must flag them so classify never tags `school`.
    for label in ["school shooting", "school massacre", "school bombing"]:
        assert ck.SCHOOL_RE.search(label), f"SCHOOL_RE should match {label}"
        assert ck.NON_SCHOOL_RE.search(label), f"NON_SCHOOL_RE should catch {label}"
    # real schools must NOT be caught by the disqualifier
    for label in ["high school", "school building", "boarding school"]:
        assert not ck.NON_SCHOOL_RE.search(label)


def test_validation_tags_are_exactly_five():
    assert set(ck.VALIDATION_TAGS) == {
        "school", "unverified", "defunct", "out_of_scope", "non_school"
    }


def test_classify_unverified_when_no_qid_or_no_p31():
    assert ck.classify_validation("", [], False) == "unverified"
    assert ck.classify_validation("Q123", [], False) == "unverified"


def test_classify_out_of_scope_for_district_and_higher_ed():
    assert ck.classify_validation("Q1", ["school district"], False) == "out_of_scope"
    assert ck.classify_validation("Q2", ["law school"], False) == "out_of_scope"
    assert ck.classify_validation("Q3", ["public university"], False) == "out_of_scope"
    assert ck.classify_validation("Q4", ["community college"], False) == "out_of_scope"


def test_classify_keeps_prep_school_despite_university_word():
    # "university-preparatory school" must stay a school, not out_of_scope
    assert ck.classify_validation("Q5", ["university-preparatory school"], False) == "school"


def test_classify_school_and_defunct():
    assert ck.classify_validation("Q6", ["high school"], False) == "school"
    assert ck.classify_validation("Q7", ["school building"], False) == "school"
    assert ck.classify_validation("Q8", ["high school"], True) == "defunct"


def test_classify_non_school_for_positive_non_school_p31():
    assert ck.classify_validation("Q9", ["human"], False) == "non_school"
    assert ck.classify_validation("Q10", ["massacre"], False) == "non_school"
    assert ck.classify_validation("Q11", ["film"], False) == "non_school"


def test_classify_school_shooting_is_non_school():
    # Real Wikidata P31 label for school-shooting events is literally
    # "school shooting" (contains "school"). It must NOT be tagged `school`.
    assert ck.classify_validation("Q473845", ["school shooting"], False) == "non_school"
    # Columbine-style multi-value P31: still non_school (no genuine school type)
    assert ck.classify_validation(
        "Q473845", ["school shooting", "mass shooting", "murder-suicide"], False
    ) == "non_school"


def test_classify_multivalue_prefers_school():
    # a page that is both a school and a tourist attraction is a school
    assert ck.classify_validation("Q12", ["tourist attraction", "high school"], False) == "school"


def test_extract_claims_reads_p31_p576_p571():
    entity = {
        "claims": {
            "P31": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"id": "Q9826"}}}},
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"id": "Q41176"}}}},
            ],
            "P571": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"time": "+1923-00-00T00:00:00Z"}}}}
            ],
            "P576": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"time": "+1995-00-00T00:00:00Z"}}}}
            ],
        }
    }
    out = ck.extract_claims(entity)
    assert out["p31_qids"] == ["Q9826", "Q41176"]
    assert out["dissolved"] is True
    assert out["founded"] == "1923"


def test_extract_claims_handles_missing():
    assert ck.extract_claims({"claims": {}}) == {
        "p31_qids": [], "dissolved": False, "dissolved_year": "", "founded": ""
    }


def test_extract_claims_returns_dissolved_year():
    entity = {"claims": {"P576": [
        {"mainsnak": {"snaktype": "value",
                      "datavalue": {"value": {"time": "+1995-00-00T00:00:00Z"}}}}]}}
    out = ck.extract_claims(entity)
    assert out["dissolved"] is True
    assert out["dissolved_year"] == "1995"


def test_tag_writes_dissolved_year(monkeypatch):
    candidates = [{"title": "Old School", "url": "u", "pageid": 1, "source_category": "X"}]
    monkeypatch.setattr(ck, "resolve_qids", lambda s, p, d, t: {1: "Q1"})
    monkeypatch.setattr(ck, "fetch_claims", lambda s, q, d, t: {
        "Q1": {"p31_qids": ["Q9826"], "dissolved": True,
               "dissolved_year": "1980", "founded": "1900"}})
    monkeypatch.setattr(ck, "resolve_labels", lambda s, q, d, t: {"Q9826": "high school"})
    out = ck.tag_candidates(None, candidates, 0, 1)
    assert out[0]["validation"] == "defunct"
    assert out[0]["dissolved"] == "1980"


def test_extract_claims_ignores_novalue_snaks():
    entity = {"claims": {"P576": [{"mainsnak": {"snaktype": "novalue"}}]}}
    assert ck.extract_claims(entity)["dissolved"] is False


def test_resolve_qids_maps_pageid_to_qid(monkeypatch):
    captured = {}
    def fake_api_get(session, params, timeout, max_retries=8, base_url=None):
        captured["base_url"] = base_url
        return {"query": {"pages": [
            {"pageid": 111, "title": "A High School",
             "pageprops": {"wikibase_item": "Q111"}},
            {"pageid": 222, "title": "B School"},  # no wikibase_item
        ]}}
    monkeypatch.setattr(ck, "api_get", fake_api_get)
    out = ck.resolve_qids(session=None, pageids=[111, 222], delay=0, timeout=1)
    assert out == {111: "Q111", 222: ""}
    assert captured["base_url"] in (None, ck.API_URL)


def test_fetch_claims_batches_and_extracts(monkeypatch):
    def fake_api_get(session, params, timeout, max_retries=8, base_url=None):
        assert base_url == ck.WIKIDATA_API
        assert params["action"] == "wbgetentities"
        return {"entities": {
            "Q111": {"claims": {"P31": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"id": "Q9826"}}}}]}},
        }}
    monkeypatch.setattr(ck, "api_get", fake_api_get)
    out = ck.fetch_claims(session=None, qids=["Q111"], delay=0, timeout=1)
    assert out["Q111"]["p31_qids"] == ["Q9826"]


def test_resolve_labels_returns_en_label(monkeypatch):
    def fake_api_get(session, params, timeout, max_retries=8, base_url=None):
        assert params["props"] == "labels"
        return {"entities": {
            "Q9826": {"labels": {"en": {"value": "high school"}}},
            "Q1": {"labels": {}},
        }}
    monkeypatch.setattr(ck, "api_get", fake_api_get)
    out = ck.resolve_labels(session=None, qids=["Q9826", "Q1"], delay=0, timeout=1)
    assert out == {"Q9826": "high school", "Q1": ""}


def test_tag_candidates_is_non_destructive_and_tags(monkeypatch):
    candidates = [
        {"title": "Real High School", "url": "u1", "pageid": 1, "source_category": "Schools in X"},
        {"title": "Some Shooting",    "url": "u2", "pageid": 2, "source_category": "Copycat crimes"},
        {"title": "No Wikidata",      "url": "u3", "pageid": 3, "source_category": "Schools in X"},
    ]
    monkeypatch.setattr(ck, "resolve_qids",
        lambda s, pids, delay, timeout: {1: "Q1", 2: "Q2", 3: ""})
    monkeypatch.setattr(ck, "fetch_claims",
        lambda s, qids, delay, timeout: {
            "Q1": {"p31_qids": ["Q9826"], "dissolved": False, "founded": "1950"},
            "Q2": {"p31_qids": ["Qmass"], "dissolved": False, "founded": ""},
        })
    monkeypatch.setattr(ck, "resolve_labels",
        lambda s, qids, delay, timeout: {"Q9826": "high school", "Qmass": "massacre"})

    out = ck.tag_candidates(session=None, candidates=candidates, delay=0, timeout=1)
    assert len(out) == 3  # nothing dropped
    by_id = {r["pageid"]: r for r in out}
    assert by_id[1]["validation"] == "school"
    assert by_id[1]["instance_of"] == "high school"
    assert by_id[1]["wikidata_qid"] == "Q1"
    assert by_id[1]["founded"] == "1950"
    assert by_id[2]["validation"] == "non_school"
    assert by_id[3]["validation"] == "unverified"
    assert by_id[3]["wikidata_qid"] == ""


def test_tag_candidates_survives_api_failure(monkeypatch):
    # If the underlying api_get raises (exhausted retries / hard error), the
    # batch functions must catch it and every row is kept as `unverified`.
    candidates = [
        {"title": "X", "url": "u", "pageid": 1, "source_category": "S"},
        {"title": "Y", "url": "u", "pageid": 2, "source_category": "S"},
    ]
    def boom(*a, **k):
        raise RuntimeError("API error: simulated")
    monkeypatch.setattr(ck, "api_get", boom)  # real batch fns must swallow it
    out = ck.tag_candidates(session=None, candidates=candidates, delay=0, timeout=1)
    assert len(out) == 2  # nothing lost
    assert all(r["validation"] == "unverified" for r in out)
    assert all(r["wikidata_qid"] == "" for r in out)


@pytest.mark.integration
def test_live_small_seed_tags_known_school(monkeypatch):
    """Hits the live API on a tiny seed. Run with: pytest -m integration"""
    import requests
    session = requests.Session()
    session.headers.update({"User-Agent": ck.USER_AGENT})
    # One small, stable category with a known school page.
    members = list(ck.iter_category_members(
        session, "Category:High schools in Vermont", "page", 0.2, 30))
    assert members, "expected some pages in the seed category"
    cands = [{"title": m["title"], "url": ck.title_to_url(m["title"]),
              "pageid": m["pageid"], "source_category": "High schools in Vermont"}
             for m in members[:15]]
    tagged = ck.tag_candidates(session, cands, 0.2, 30)
    assert len(tagged) == len(cands)                 # non-destructive
    assert all(r["validation"] in ck.VALIDATION_TAGS for r in tagged)
    assert any(r["validation"] == "school" for r in tagged)


def test_read_candidates_roundtrip(tmp_path):
    p = tmp_path / "raw.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["title", "url", "pageid", "source_category"])
        w.writeheader()
        w.writerow({"title": "A", "url": "ua", "pageid": "5", "source_category": "X"})
    rows = ck.read_candidates(str(p))
    assert rows == [{"title": "A", "url": "ua", "pageid": 5, "source_category": "X"}]


def test_parse_write_status():
    assert ck.parse_write_status("") is None
    assert ck.parse_write_status("school,unverified") == {"school", "unverified"}


def test_write_tagged_csv_all_and_filtered(tmp_path):
    rows = [
        {"title": "A", "url": "ua", "pageid": 1, "source_category": "X",
         "instance_of": "high school", "wikidata_qid": "Q1", "founded": "",
         "dissolved": "", "validation": "school"},
        {"title": "B", "url": "ub", "pageid": 2, "source_category": "X",
         "instance_of": "human", "wikidata_qid": "Q2", "founded": "",
         "dissolved": "", "validation": "non_school"},
    ]
    p_all = tmp_path / "all.csv"
    n_all = ck.write_tagged_csv(str(p_all), rows, None)
    assert n_all == 2
    header = next(csv.reader(open(p_all)))
    assert header == ["title", "url", "pageid", "source_category", "instance_of",
                      "wikidata_qid", "founded", "dissolved", "validation"]

    p_sch = tmp_path / "schools.csv"
    n_sch = ck.write_tagged_csv(str(p_sch), rows, {"school"})
    assert n_sch == 1
    data = list(csv.DictReader(open(p_sch)))
    assert [r["validation"] for r in data] == ["school"]
