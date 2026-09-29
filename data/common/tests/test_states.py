# common/tests/test_states.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from common import states as s


def test_all_nces_jurisdictions_present():
    assert len(s.USPS_TO_NAME) == 56                       # 50 + DC + 5 territories
    assert s.USPS_TO_FIPS["PR"] == "72" and s.USPS_TO_FIPS["DC"] == "11"


def test_state_code_accepts_codes_names_and_variants():
    assert s.state_code("ca") == "CA"
    assert s.state_code("California") == "CA"
    assert s.state_code("U.S. Virgin Islands") == "VI"
    assert s.state_code("Narnia") == ""


def test_state_in_text_prefers_longest_name():
    assert s.state_in_text("Schools in Arkansas") == "Arkansas"            # not Kansas
    assert s.state_in_text("Schools in West Virginia") == "West Virginia"  # not Virginia
    assert s.state_in_text("A school in Washington, D.C.") == "District of Columbia"
    assert s.state_in_text("Schools in the U.S. Virgin Islands") == "United States Virgin Islands"
    assert s.state_in_text("nothing here") == ""


def test_prose_names_read_naturally():
    assert s.PROSE_NAME["DC"] == "the District of Columbia"
    assert s.PROSE_NAME["VI"] == "the U.S. Virgin Islands"
    assert s.PROSE_NAME["OH"] == "Ohio"
