import pytest

from k12aii.frame import _clean_name


@pytest.mark.parametrize("raw,want", [
    ("CLYDE H S", "Clyde High School"),
    ("Moises E Molina H S", "Moises E Molina High School"),
    ("Northeast Elem.", "Northeast Elementary School"),
    ("Clovis High", "Clovis High School"),
    ("Lake Stevens Sr High School", "Lake Stevens Senior High School"),
    ("Edwin M Wells Middle", "Edwin M Wells Middle School"),
    ("Mercersburg Academy", "Mercersburg Academy"),
])
def test_clean_name(raw, want):
    assert _clean_name(raw) == want
