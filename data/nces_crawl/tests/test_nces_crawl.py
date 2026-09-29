# nces_crawl/tests/test_nces_crawl.py
import os
import sys
from pathlib import Path

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "generate_articles"))
import combine_all_schools as c
import generate_article as ga


def test_chrome_temp_files_are_never_taken_as_downloads():
    # A hidden in-progress file was once renamed as Utah's data, truncating it.
    import download_schools as d
    paths = [Path(".com.google.Chrome.CazZSO"), Path("ncesdata_1.xls.crdownload"),
             Path("ncesdata_2.xls")]
    assert d.finished_downloads(paths) == [Path("ncesdata_2.xls")]


def test_parse_school_file_skips_preamble_and_footer(tmp_path):
    html = ("<table><tr><td>NCES banner</td></tr><tr><td>notes</td></tr>"
            "<tr><th>NCES School ID</th><th>School Name*</th></tr>"
            "<tr><td>010000500870</td><td>Albertville High</td></tr>"
            "<tr><td></td><td>footer</td></tr></table>")
    path = tmp_path / "Alabama_01.xls"
    path.write_text(html)
    header, records = c.parse_school_file(path, "NCES School ID")
    assert header == ["NCES School ID", "School Name"]     # footnote * stripped
    assert records == [{"NCES School ID": "010000500870", "School Name": "Albertville High"}]


def _public(**kw):
    r = {"sector": "public", "school_name": "A C MOORE PRIMARY SCHOOL", "city": "ATMORE",
         "state": "AL", "low_grade": "PK", "high_grade": "KG", "total_students": "216",
         "teachers": "13", "Locale": "Town, Distant", "address": "501 BECK STREET",
         "zip": "36502", "phone": "(251)368-4245"}
    return {**r, **kw}


def test_article_year_follows_sector():
    pub = ga.render_article(_public())
    pri = ga.render_article(_public(sector="private"))
    assert f"As of the {ga.DATA_YEAR['public']} school year" in pub
    assert f"As of the {ga.DATA_YEAR['private']} school year" in pri
    assert "As of the 1999-00 school year" in ga.render_article(_public(), year="1999-00")


def test_article_does_not_repeat_located_phrasing():
    text = ga.render_article(_public())
    assert text.count("located") == 1
    assert "Its street address is 501 Beck Street, Atmore, AL 36502" in text


def test_article_never_invents_missing_fields():
    text = ga.render_article({"sector": "public", "school_name": "X SCHOOL", "state": "AL"})
    assert text == "X School is a public school in Alabama."


def test_only_new_status_becomes_a_sentence():
    assert "It opened in the 2024-25 school year." in ga.render_article(_public(Status="New"), year="2024-25")
    for status in ("Open", "Added", "Changed Boundary/Agency", "Reopened"):
        text = ga.render_article(_public(Status=status))
        assert "status" not in text.lower() and "opened in" not in text
