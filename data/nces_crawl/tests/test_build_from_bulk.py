# Author: Boxuan Shan, with support from Claude (Anthropic)
# nces_crawl/tests/test_build_from_bulk.py
# Each case here is a bug found while cross-checking the bulk build against the
# CCD search-tool export (2026-09).
import csv
import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_from_bulk as b

DIR_COLS = ["NCESSCH", "ST_SCHID", "LEAID", "ST_LEAID", "GSLO", "GSHI", "SCH_NAME",
            "LEA_NAME", "LSTREET1", "LCITY", "ST", "LSTATE", "LZIP", "LZIP4", "PHONE",
            "CHARTER_TEXT", "SCH_TYPE_TEXT", "SY_STATUS_TEXT", "MSTREET1"]


def _school(sid, **kw):
    base = {"NCESSCH": sid, "ST_SCHID": "X", "LEAID": sid[:7], "ST_LEAID": "X",
            "GSLO": "09", "GSHI": "12", "SCH_NAME": f"School {sid}", "LEA_NAME": "D",
            "LSTREET1": "1 Main St", "LCITY": "Town", "ST": "AL", "LSTATE": "AL",
            "LZIP": "35000", "LZIP4": "", "PHONE": "(205)555-0100",
            "CHARTER_TEXT": "No", "SCH_TYPE_TEXT": "Regular School",
            "SY_STATUS_TEXT": "Open", "MSTREET1": "PO Box 1"}
    return {**base, **kw}


def _write(zip_path, name, header, rows, delimiter=","):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter)
    if header:
        w.writerow(header)
    w.writerows(rows)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readme.sas7bdat", "")          # NCES zips carry other members too
        zf.writestr(name, buf.getvalue().encode("utf-8"))


@pytest.fixture
def bulk(tmp_path, monkeypatch):
    """Write small zips named like the real NCES files into a temp BULK dir."""
    monkeypatch.setattr(b, "BULK", str(tmp_path))
    monkeypatch.setattr(b, "PUBLIC_OUT", str(tmp_path / "public.csv"))

    def build(schools, membership, staff, edge):
        d = lambda key: str(tmp_path / os.path.basename(b.FILES[key]))  # noqa: E731
        _write(d("directory"), "dir.csv", DIR_COLS, [[s[c] for c in DIR_COLS] for s in schools])
        _write(d("membership"), "m.csv", ["NCESSCH", "GRADE", "STUDENT_COUNT", "TOTAL_INDICATOR"],
               membership)
        _write(d("staff"), "s.csv", ["NCESSCH", "TEACHERS", "TOTAL_INDICATOR"], staff)
        _write(d("lunch"), "l.csv", ["NCESSCH", "DATA_GROUP", "LUNCH_PROGRAM",
                                     "STUDENT_COUNT", "TOTAL_INDICATOR"], [])
        _write(d("edge_public"), "E.TXT", None,
               [[sid, "", "", "", "", "", "", "", "", cnty, county, "21", "34.1", "-86.2"]
                + [""] * 9 for sid, cnty, county in edge], delimiter="|")
        b.build_public()
        return {r["NCES School ID"]: r for r in csv.DictReader(open(b.PUBLIC_OUT))}
    return build


TOTAL = "Education Unit Total"
ADULT = "Subtotal 4 - By Grade"


def test_enrollment_excludes_adult_education(bulk):
    out = bulk([_school("010000000001")],
               [["010000000001", "No Category Codes", "348", TOTAL],
                ["010000000001", "Adult Education", "347", ADULT],
                ["010000000001", "Grade 12", "1", ADULT]],
               [["010000000001", "2.00", TOTAL]], [("010000000001", "01001", "Autauga County")])
    assert out["010000000001"]["Students"] == "1"


def test_no_ratio_for_zero_enrollment(bulk):
    out = bulk([_school("010000000001")],
               [["010000000001", "No Category Codes", "0", TOTAL]],
               [["010000000001", "4.00", TOTAL]], [])
    assert out["010000000001"]["Student Teacher Ratio"] == ""


def test_ratio_and_plain_numbers(bulk):
    out = bulk([_school("010000000001")],
               [["010000000001", "No Category Codes", "216", TOTAL]],
               [["010000000001", "13.00", TOTAL]], [])
    r = out["010000000001"]
    assert (r["Students"], r["Teachers"], r["Student Teacher Ratio"]) == ("216", "13", "16.62")


def test_type_labels_match_the_search_export(bulk):
    out = bulk([_school("010000000001", SCH_TYPE_TEXT="Alternative School"),
                _school("010000000002", SCH_TYPE_TEXT="Career and Technical School")], [], [], [])
    assert out["010000000001"]["Type"] == "Other/Alternative"
    assert out["010000000002"]["Type"] == "Vocational"


def test_bie_school_is_placed_in_its_physical_state(bulk):
    out = bulk([_school("590000000001", ST="BI", LSTATE="SD")], [], [], [])
    assert out["590000000001"]["State"] == "SD"


def test_only_operating_schools_and_location_address(bulk):
    out = bulk([_school("010000000001"), _school("010000000002", SY_STATUS_TEXT="Closed"),
                _school("010000000003", SY_STATUS_TEXT="Future"),
                _school("010000000004", SY_STATUS_TEXT="New")], [], [], [])
    assert set(out) == {"010000000001", "010000000004"}
    assert out["010000000001"]["Street Address"] == "1 Main St"      # not the PO box


def test_utf8_county_names(bulk):
    out = bulk([_school("720003000970", ST="PR", LSTATE="PR")], [], [],
               [("720003000970", "72075", "Juana Díaz Municipio")])
    assert out["720003000970"]["County Name"] == "Juana Díaz Municipio"
