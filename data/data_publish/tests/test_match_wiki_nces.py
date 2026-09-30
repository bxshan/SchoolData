# Author: Boxuan Shan, with support from Claude (Anthropic)
# data_publish/tests/test_match_wiki_nces.py
# Regression tests for match failures found while auditing the 2026-09 rebuild.
import csv
import os
import sys
from collections import defaultdict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import match_wiki_nces as m

MASTER_COLS = ["sector", "school_id", "school_name", "state", "city",
               "low_grade", "high_grade"] + [c for _, c in m._PSS_ENROLL]


def pub(sid, name, city, lo, hi, state="AL"):
    return {"sector": "public", "school_id": sid, "school_name": name,
            "state": state, "city": city, "low_grade": lo, "high_grade": hi}


def priv(sid, name, city, grades, state="NY"):
    r = {"sector": "private", "school_id": sid, "school_name": name,
         "state": state, "city": city, "low_grade": "", "high_grade": ""}
    for g, col in m._PSS_ENROLL:
        r[col] = "10" if g in grades else "0"
    return r


@pytest.fixture
def nces(tmp_path):
    def build(*rows):
        path = tmp_path / "master.csv"
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=MASTER_COLS, restval="")
            w.writeheader()
            w.writerows(rows)
        by_id, by_state = m.load_nces(str(path))
        idx = {st: m.build_token_index(recs) for st, recs in by_state.items()}
        return by_id, by_state, idx
    return build


def wiki(title, state="Alabama", level="", nces_id=""):
    return {"title": title, "state": state, "level": level, "nces_id": nces_id}


def match(w, db):
    by_id, by_state, idx = db
    return m.match_one(w, by_id, by_state, idx, 88.0, defaultdict(int))


def test_fuzzy_rejects_high_school_vs_elementary(nces):
    db = nces(pub("1", "Troy Elementary School", "troy", "KG", "05"))
    assert match(wiki("Troy High School (Alabama)"), db) is None


def test_fuzzy_prefers_level_compatible_school(nces):
    db = nces(pub("1", "Troy Elementary School", "troy", "KG", "05"),
              pub("2", "Troy High School", "troy", "09", "12"))
    rec, _, _ = match(wiki("Troy High School (Alabama)"), db)
    assert rec["school_id"] == "2"


def test_fuzzy_rejects_title_city_mismatch(nces):
    db = nces(pub("1", "Hope Academy", "la joya", "09", "12", state="TX"))
    assert match(wiki("Hope High School (Port Lavaca, Texas)", state="Texas"), db) is None


def test_name_state_picks_school_in_title_city(nces):
    db = nces(pub("1", "Lincoln High School", "mobile", "09", "12"),
              pub("2", "Lincoln High School", "talladega", "09", "12"))
    rec, method, _ = match(wiki("Lincoln High School (Talladega, Alabama)"), db)
    assert (rec["school_id"], method) == ("2", "name_state")


def test_name_state_rejects_when_every_candidate_is_elsewhere(nces):
    db = nces(priv("1", "Notre Dame School", "new hyde park", range(-1, 9)))
    assert match(wiki("Notre Dame School (Albany, New York)", state="New York"), db) is None


def test_nces_id_tier_matches_without_a_conflicting_level(nces):
    db = nces(pub("010000500870", "Albertville Middle School", "albertville", "07", "08"))
    rec, method, _ = match(wiki("Whatever Title", nces_id="010000500870"), db)
    assert method == "nces_id" and rec["school_id"] == "010000500870"


@pytest.mark.parametrize("a,b,ok", [
    ("st. george", "st george", True),          # punctuation
    ("new york city", "new york", True),
    ("queens", "astoria", True),                # NCES files NYC by neighborhood
    ("bloomfield township", "bloomfield hills", True),
    ("port lavaca", "la joya", False),
    ("encino", "el cajon", False),
    ("north bend", "north hills", False),       # filler words don't count
    ("", "anywhere", True),
])
def test_city_compatible(a, b, ok):
    assert m.city_compatible(a, b) is ok


@pytest.mark.parametrize("title,city", [
    ("Our Lady of Grace (Encino)", "encino"),
    ("Trinity High School (Georgia)", ""),      # a state is not a city
    ("X (San Diego, California)", "san diego"),
    ("Y (1920)", ""),
    ("Z", ""),
])
def test_title_explicit_city(title, city):
    assert m.title_explicit_city(title) == city


def test_grade_levels_public_codes():
    assert m.grade_levels({"sector": "public", "low_grade": "PK", "high_grade": "05"}) == {"elementary"}
    assert m.grade_levels({"sector": "public", "low_grade": "06", "high_grade": "12"}) == {"middle", "high"}
    assert m.grade_levels({"sector": "public", "low_grade": "UG", "high_grade": "UG"}) == set()


def test_grade_levels_private_uses_enrollment_not_codes():
    r = priv("1", "St X", "x", range(9, 13))
    r.update(low_grade="14", high_grade="17")   # opaque PSS codes are ignored
    assert m.grade_levels(r) == {"high"}


def test_category_level_only_vetoes_fuzzy_matches(nces):
    # Exact name + state: a category-inferred level must not veto it...
    db = nces(pub("1", "Oak Hill Academy", "lincroft", "PK", "08"))
    assert match(wiki("Oak Hill Academy", level="high"), db) is not None


def test_difflib_fallback_has_the_method_the_matcher_calls():
    assert hasattr(m.fuzz, "token_sort_ratio")


def test_parse_statuses():
    assert m.parse_statuses("school") == {"school"}
    assert m.parse_statuses("school, unverified") == {"school", "unverified"}
    assert m.parse_statuses("all") is None


def test_one_article_per_nces_school(tmp_path, monkeypatch, capsys):
    master = tmp_path / "master.csv"
    with open(master, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MASTER_COLS, restval="")
        w.writeheader()
        w.writerow(pub("010000500870", "Albertville High School", "albertville", "09", "12"))
    wiki_csv = tmp_path / "wiki.csv"
    with open(wiki_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["title", "url", "pageid", "state", "level",
                                           "wikidata_qid", "nces_id", "validation",
                                           "pageviews_60d"])
        w.writeheader()
        w.writerow({"title": "Albertville High School", "url": "u1", "pageid": "1",
                    "state": "Alabama", "nces_id": "", "validation": "school"})
        w.writerow({"title": "Albertville HS (old)", "url": "u2", "pageid": "2",
                    "state": "Alabama", "nces_id": "010000500870", "validation": "school"})
        w.writerow({"title": "Albertville High School shooting", "url": "u3", "pageid": "3",
                    "state": "Alabama", "nces_id": "", "validation": "non_school"})
    out = tmp_path / "out.csv"
    monkeypatch.setattr(sys, "argv", ["m", "--wiki", str(wiki_csv), "--nces", str(master),
                                      "--out", str(out), "--nces-coords", "",
                                      "--unmatched", str(tmp_path / "unmatched.csv")])
    m.main()
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 1                               # one article per school
    assert rows[0]["match_method"] == "nces_id"         # the strongest tier wins


def _with_coords(rec, lat, lon):
    rec["lat"], rec["lon"] = lat, lon
    return rec


def test_same_named_schools_without_city_are_not_guessed(nces):
    db = nces(pub("1", "Bridges Academy", "san jose", "09", "12", state="CA"),
              pub("2", "Bridges Academy", "studio city", "09", "12", state="CA"))
    assert match(wiki("Bridges Academy", state="California"), db) is None


def test_same_named_schools_resolved_by_article_coordinates(nces):
    by_id, by_state, idx = nces(pub("1", "Bridges Academy", "san jose", "09", "12", state="CA"),
                                pub("2", "Bridges Academy", "studio city", "09", "12", state="CA"))
    _with_coords(by_id["1"], 37.33, -121.89)
    _with_coords(by_id["2"], 34.14, -118.39)
    w = {**wiki("Bridges Academy", state="California"), "lat": "34.15", "lon": "-118.40"}
    rec, method, _ = m.match_one(w, by_id, by_state, idx, 88.0, defaultdict(int))
    assert (rec["school_id"], method) == ("2", "name_state")


def test_coordinates_too_far_away_do_not_decide(nces):
    by_id, by_state, idx = nces(pub("1", "Bridges Academy", "san jose", "09", "12", state="CA"),
                                pub("2", "Bridges Academy", "studio city", "09", "12", state="CA"))
    _with_coords(by_id["1"], 37.33, -121.89)
    _with_coords(by_id["2"], 34.14, -118.39)
    w = {**wiki("Bridges Academy", state="California"), "lat": "40.0", "lon": "-100.0"}
    assert m.match_one(w, by_id, by_state, idx, 88.0, defaultdict(int)) is None


def test_middle_college_and_intermediate_are_not_level_words():
    assert m.school_levels(m.norm_name("Gary Middle College")) == set()
    assert m.school_levels(m.norm_name("Goshen Intermediate School")) == set()
    assert m.school_levels(m.norm_name("Lincoln Middle School")) == {"middle"}


def test_nces_id_pointing_at_a_different_level_is_rejected(nces):
    # Wikidata's id now belongs to a 6-8 school; the high school is found by name.
    db = nces(pub("010000000001", "Bailey APAC Middle School", "jackson", "06", "08"),
              pub("010000000002", "Bailey Magnet High School", "jackson", "09", "12"))
    rec, method, _ = match(wiki("Bailey Magnet High School", nces_id="010000000001"), db)
    assert (rec["school_id"], method) == ("010000000002", "name_state")
