from k12aii.score import district_match, parse, score_item

PUB = {"sector": "public", "level": "high", "district": "Boulder Valley School District", "religion": None}
PRIV = {"sector": "private", "level": "elementary", "district": None, "religion": "catholic"}


def test_parse_and_q5_multiline():
    p = parse("Q1: PUBLIC\nQ2: Boulder Valley\nQ3: HIGH\nQ4: NONE\nQ5: A school.\nSecond line.")
    assert p["q1"] == "PUBLIC" and p["q5"].endswith("Second line.")


def test_district_variants():
    assert district_match("Boulder Valley School District RE-2", "Boulder Valley School District")
    assert district_match("Boulder Valley", "Boulder Valley School District")
    assert not district_match("Denver Public Schools", "Boulder Valley School District")


def test_outcomes():
    assert score_item("sector", "PUBLIC", PUB) == "correct"
    assert score_item("sector", "PRIVATE", PUB) == "wrong"
    assert score_item("sector", "UNKNOWN", PUB) == "abstain"
    assert score_item("district", "NONE", PRIV) == "NA"
    assert score_item("religion", "NONE", PUB) == "NA"
    assert score_item("religion", "CATHOLIC", PRIV) == "correct"
    assert score_item("religion", "OTHER_RELIGIOUS", PRIV) == "wrong"
    assert score_item("level", "HIGH", PUB) == "correct"


def test_nces_abbreviations_and_nyc():
    assert district_match("Brownstown Central Community School Corporation", "Brownstown Cnt Com Sch Corp")
    assert district_match("South Sioux City Community Schools", "SO SIOUX CITY COMMUNITY SCHS")
    assert district_match("Des Moines Public Schools", "Des Moines Independent Comm School District")
    assert district_match("New York City Department of Education", "NEW YORK CITY GEOGRAPHIC DISTRICT #28")
    assert not district_match("Clark County School District", "Washoe County")


def test_charter_district_not_scored():
    assert score_item("district", "Vallejo City Unified", {**PUB, "charter": True}) == "NA"


def test_level_alt_accepted():
    from k12aii.score import score_item as si
    t = {"sector": "public", "level": "combined", "level_alt": "high"}
    assert si("level", "HIGH", t) == "correct" and si("level", "COMBINED", t) == "correct"
    assert si("level", "ELEMENTARY", t) == "wrong"


def test_hard_scoring():
    from k12aii.score import band, enroll_ok, grades_ok, parse_grades, score_hard_item
    assert parse_grades("9-12") == (9, 12) and parse_grades("PK–8") == (-1, 8) and parse_grades("K-5") == (0, 5)
    assert parse_grades("UNKNOWN") is None
    t = {"lo_n": -1, "hi_n": 5, "enrollment": 400, "sector": "public", "charter": False}
    assert grades_ok(0, 5, t)                       # K-5 accepted for a PK-5 school
    assert not grades_ok(0, 6, t)
    assert [band(n) for n in (199, 200, 499, 500, 999, 1000)] == ["A", "B", "B", "C", "C", "D"]
    assert enroll_ok(450, t) and not enroll_ok(600, t)
    assert score_hard_item("enroll", "B (200-499)", t) == "correct" and score_hard_item("enroll", "C", t) == "wrong"
    assert score_hard_item("charter", "NO", t) == "correct" and score_hard_item("charter", "YES", t) == "wrong"
    assert score_hard_item("charter", "NO", {**t, "sector": "private"}) == "NA"
    assert score_hard_item("enroll", "UNKNOWN", t) == "abstain"


def test_parse_kb_format():
    from k12aii.score import parse
    p = parse("A1: PUBLIC\nA2: Boulder Valley\nA3: HIGH\nA4: NONE\nA5: 9-12\nA6: C\nA7: NO\nD1: A school.\nSecond line.")
    assert p["a1"] == "PUBLIC" and p["a5"] == "9-12" and p["a6"] == "C" and p["d1"].endswith("Second line.")
