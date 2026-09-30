# Author: Boxuan Shan, with support from Claude (Anthropic)
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


def _rec(**kw):
    base = {"title": "X School", "state": "Ohio", "description": "", "instance_of": "school",
            "validation": "school", "wikidata_qid": "Q1", "country": "United States",
            "dissolved": "", "lat": "", "lon": "", "operating": "", "validation_note": ""}
    return {**base, **kw}


def _reval(**kw):
    recs = {1: _rec(**kw)}
    e.revalidate(recs)
    return recs[1]


def test_revalidate_moves_networks_and_districts_out():
    assert _reval(description="Charter school network in Chicago")["validation"] == "out_of_scope"
    assert _reval(description="School district in Texas")["validation"] == "out_of_scope"


def test_revalidate_keeps_a_school_that_mentions_its_district():
    r = _reval(description="Public high school in the Fairfax County school district")
    assert r["validation"] == "school" and r["validation_note"] == ""


def test_revalidate_higher_ed_but_not_college_prep():
    assert _reval(description="Private university in Alabama")["validation"] == "out_of_scope"
    assert _reval(description="Private college preparatory school")["validation"] == "school"


def test_revalidate_foreign_only_without_a_us_state():
    assert _reval(country="Canada", state="")["validation"] == "out_of_scope"
    # Wikidata country bug: French High School (Beaumont, Texas) tagged France
    assert _reval(country="France", state="Texas")["validation"] == "school"


def test_revalidate_rescues_unverified_described_as_school():
    r = _reval(validation="unverified", description="Private school in Queens, New York")
    assert r["validation"] == "school" and "rescued" in r["validation_note"]


def test_revalidate_operating_flag():
    assert _reval()["operating"] == "yes"
    assert _reval(dissolved="1")["operating"] == "no"
    assert _reval(description="Former school in Ohio")["operating"] == "no"
    assert _reval(instance_of="school building")["operating"] == "no"
    assert _reval(instance_of="school building|United States historic place")["operating"] == "no"
    # an operating school whose building is also listed (Chandler High School)
    assert _reval(instance_of="high school|school building|public school")["operating"] == "yes"
    assert _reval(description="Historic public high school in Boston")["operating"] == "yes"


def test_revalidate_fills_state_from_description():
    r = _reval(state="", description="Public elementary school in Queens, New York")
    assert r["state"] == "New York" and "description" in r["validation_note"]


def test_defunct_category_detection():
    hit = lambda cats: bool(e.DEFUNCT_CATEGORY.search(" | ".join(cats)))   # noqa: E731
    assert hit(["Category:Defunct high schools in Ohio"])
    assert hit(["Category:Educational institutions disestablished in 1971"])
    # "Former ..." categories hold open schools: former girls' schools, etc.
    assert not hit(["Category:Former university-affiliated schools in the United States"])
    assert not hit(["Category:Former girls' schools in California"])
    assert not hit(["Category:High schools in Ohio", "Category:Schools in Ohio"])
    # words from two different categories must not combine
    assert not hit(["Category:Former municipalities in Ohio", "Category:High schools in Ohio"])


def test_school_in_defunct_category_becomes_defunct():
    r = _reval(defunct_category="Category:Defunct high schools in Ohio")
    assert r["validation"] == "defunct" and r["operating"] == "no"


def test_defunct_category_returns_the_category_for_auditing():
    assert e.defunct_category(["Category:Schools in Ohio",
                               "Category:Educational institutions disestablished in 1999"]) \
        == "Category:Educational institutions disestablished in 1999"
    assert e.defunct_category(["Category:Schools in Ohio"]) == ""


def test_lead_tense():
    assert e.lead_tense("Troy High School is a public high school in Troy, Ohio.") == "present"
    assert e.lead_tense("Blue School was a progressive school in New York City.") == "past"
    assert e.lead_tense("Evergreen School is a historic school building in Alabama.") == "past"
    assert e.lead_tense("") == ""


def test_present_tense_lead_overrides_a_predecessor_defunct_category():
    # Manhattan Center for Science and Mathematics sits in "Defunct high schools
    # in Manhattan" (its predecessor's category) but is open.
    r = _reval(defunct_category="Category:Defunct high schools in Manhattan",
               lead="Manhattan Center for Science and Mathematics is a public high school in East Harlem.")
    assert r["validation"] == "school" and r["operating"] == "yes"
    r = _reval(defunct_category="Category:Defunct high schools in Manhattan",
               lead="Benjamin Franklin High School was a public high school in East Harlem.")
    assert r["validation"] == "defunct" and r["operating"] == "no"


def test_single_school_district_stays_a_school():
    r = _reval(title="Lenape Valley Regional High School", instance_of="high school",
               description="School district in Sussex County, New Jersey, US")
    assert r["validation"] == "school"
    assert _reval(title="Atlas Schools", instance_of="school",
                  description="Charter school network in Colorado Springs")["validation"] == "out_of_scope"


def test_network_school_is_not_a_network():
    assert _reval(title="Detroit Cristo Rey High School", instance_of="high school",
                  description="Private, cristo rey network school in Wayne County")["validation"] == "school"


def test_middle_college_high_school_is_not_higher_ed():
    assert _reval(title="Grossmont Middle College High School", instance_of="high school|public school",
                  description="Middle college in El Cajon, California")["validation"] == "school"


def test_rescue_crawl_misfiled_school_with_present_lead():
    r = _reval(title="Gilroy Early College Academy", crawl_validation="out_of_scope",
               validation="out_of_scope", instance_of="early college high school",
               lead="Gilroy Early College Academy is a public high school in Gilroy, California.")
    assert r["validation"] == "school" and "rescued" in r["validation_note"]


def test_revalidate_is_idempotent_from_crawl_tag():
    rec = _rec(crawl_validation="school", description="Private university in Alabama")
    recs = {1: rec}
    e.revalidate(recs); first = dict(recs[1])
    e.revalidate(recs)
    assert recs[1]["validation"] == first["validation"] == "out_of_scope"
