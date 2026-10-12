import math

from k12aii.prompts import build_bias_prompt
from k12aii.score import parse_bias

ROW = {"school_name": "Test High School", "city": "Ames", "state": "IA"}


def test_parse_bias():
    p = parse_bias("B0: 2\nB1: 7\nB2: 11\nB3: 5/10\nB4: 6\nB5: 8\nB6: Good school.\nMore text.")
    assert p["familiarity"] == 2 and p["academic"] == 7 and p["resources"] == 5
    assert math.isnan(p["safety"])           # 11 is out of range
    assert p["b6_text"].endswith("More text.")


def test_arms_differ_only_in_poverty_sentence():
    a, b, c = (build_bias_prompt(ROW, arm) for arm in ("none", "frl15", "frl85"))
    assert "15%" in b and "85%" in c and "free or reduced" not in a
    assert b.replace("15%", "85%") == c      # nothing else differs
