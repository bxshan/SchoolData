# wiki_crawl/tests/test_enrich_and_fetch.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import enrich_schools as e
import fetch_article_text as f


def _fake_api(redirects, pages):
    def api_get(session, params, **kw):
        return {"query": {"redirects": [{"from": a, "to": b} for a, b in redirects],
                          "pages": pages}}
    return api_get


def test_redirect_to_town_is_labeled_not_merged(monkeypatch):
    monkeypatch.setattr(e, "api_get", _fake_api(
        [("Joliet Montessori School", "Crest Hill, Illinois")],
        [{"pageid": 9, "title": "Crest Hill, Illinois", "pageprops": {"wikibase_item": "Q2"}}]))
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    out = e.resolve_and_enrich(None, [{"title": "Joliet Montessori School", "pageid": "5",
                                       "source_category": "Schools in Illinois",
                                       "validation": "school"}], 0)
    (rec,) = out.values()
    assert rec["title"] == "Joliet Montessori School"      # the town never enters
    assert rec["validation"] == "redirect"
    assert rec["redirect_to"] == "Crest Hill, Illinois"
    assert rec["state"] == "Illinois"


def test_redirect_to_crawled_school_collapses_and_keeps_real_tag(monkeypatch):
    monkeypatch.setattr(e, "api_get", _fake_api(
        [("Old HS", "Real HS")],
        [{"pageid": 7, "title": "Real HS", "pageprops": {"wikibase_item": "Q1"}}]))
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    rows = [{"title": "Old HS", "pageid": "1", "source_category": "Schools in Ohio",
             "validation": "unverified"},
            {"title": "Real HS", "pageid": "7", "source_category": "Schools in Ohio",
             "validation": "school"}]
    out = e.resolve_and_enrich(None, rows, 0)
    assert list(out) == [7]
    assert out[7]["validation"] == "school" and out[7]["redirect_to"] == ""


def test_state_of_handles_territories_and_overlaps():
    assert e.state_of("Schools in the United States Virgin Islands") == "United States Virgin Islands"
    assert e.state_of("Schools in Arkansas") == "Arkansas"            # not Kansas
    assert e.state_of("Schools in West Virginia") == "West Virginia"  # not Virginia


def test_clean_text_strips_leftover_markup_and_boilerplate():
    raw = ("Troy High School is a {{convert|5|mi}} school in [[Troy, Alabama|Troy]].[3] "
           "It opened[citation needed] in 1920 .\n== History ==\nFounded early."
           "\n== References ==\n1. Some ref\n=== Sub ===\nmore ref")
    assert f.clean_text(raw) == ("Troy High School is a school in Troy. "
                                 "It opened in 1920. Founded early.")


def test_clean_text_drops_unbalanced_brackets_from_broken_articles():
    # Saddleback High School's article carries a stray "]]" from a bad edit.
    assert f.clean_text("Alumni: Daniel Arreolaiola]] - Sport caster") == \
        "Alumni: Daniel Arreolaiola - Sport caster"


def test_clean_text_is_idempotent():
    once = f.clean_text("A [[b|c]] school {{x}}.[1] It is.")
    assert f.clean_text(once) == once
