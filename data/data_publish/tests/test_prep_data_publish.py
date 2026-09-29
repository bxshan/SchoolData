# data_publish/tests/test_prep_data_publish.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prep_data_publish as p

LONG = "Lincoln High School is a public high school in Talladega, Alabama. " * 5


def gen(**kw):
    base = {"name": "LINCOLN HIGH", "state": "AL", "sector": "public", "text": "NCES text."}
    return {**base, **kw}


def test_wikipedia_row_gets_full_text_and_attribution():
    rows, _ = p.build_rows(
        {"1": gen()},
        {"1": {"pageid": "7", "title": "Lincoln High School", "qid": "Q1", "url": "u"}},
        {"7": {"title": "Lincoln High School (Talladega)", "revid": 123, "text": LONG}},
        min_chars=200, state=None)
    r = rows[0]
    assert r["from_wikipedia"] == 1 and r["text"] == LONG
    assert r["wikipedia_revid"] == "123" and r["license"] == "CC-BY-SA-4.0"
    # the current (post-rename) title is the attribution target
    assert r["source"] == "https://en.wikipedia.org/wiki/Lincoln_High_School_(Talladega)"


def test_missing_or_short_wikipedia_text_falls_back_to_nces():
    rows, stats = p.build_rows(
        {"1": gen(), "2": gen()},
        {"1": {"pageid": "7", "title": "A", "qid": "Q1", "url": ""},
         "2": {"pageid": "8", "title": "B", "qid": "Q2", "url": ""}},
        {"8": {"title": "B", "revid": 1, "text": "Too short."}},
        min_chars=200, state=None)
    assert [r["from_wikipedia"] for r in rows] == [0, 0]
    assert all(r["license"] == "CC0-1.0" and not r["wikipedia_title"] for r in rows)
    assert stats == {"no_text": 1, "short_text": 1}


def test_nces_source_names_sector_and_year():
    rows, _ = p.build_rows({"1": gen(), "2": gen(sector="private")}, {}, {}, 200, None)
    assert rows[0]["source"] == f"NCES CCD {p.DATA_YEAR['public']}"
    assert rows[1]["source"] == f"NCES PSS {p.DATA_YEAR['private']}"


def test_state_slice_and_sorted_ids():
    rows, _ = p.build_rows({"3": gen(), "1": gen(state="CA"), "2": gen()}, {}, {}, 200, "AL")
    assert [r["nces_id"] for r in rows] == ["2", "3"]
