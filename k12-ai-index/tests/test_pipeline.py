"""Integration test: sample -> mock run -> mock judge -> analysis, on the real frame (skipped if not built)."""
import pytest

from k12aii.common import ROOT, load_cfg

FRAME = ROOT / "data" / "frame.parquet"
pytestmark = pytest.mark.skipif(not FRAME.exists(), reason="run `make frame` first")


def test_sample_is_matched_and_eligible(tmp_path):
    import pandas as pd
    from k12aii import sample
    cfg = load_cfg()
    p = sample.draw(cfg, n_per_group=24, seed=1, out=str(tmp_path / "s.parquet"))
    s = pd.read_parquet(p)
    assert s.from_wikipedia.value_counts().nunique() == 1          # equal group sizes
    assert s.eligible.all() and s.nces_id.is_unique
    cell = s.groupby(["sector", "locale3", "level_group", "from_wikipedia"]).size().unstack()
    assert (cell[0] == cell[1]).all()                              # matched inside every cell
    pub = s[s.sector == "public"]
    assert pub.frl_pct.notna().all()


def test_mock_end_to_end(tmp_path):
    from k12aii import analyze, judge, run, sample
    cfg = load_cfg()
    cfg["judge"].update(provider="mock", model="mock")
    s = sample.draw(cfg, n_per_group=24, seed=2, out=str(tmp_path / "s.parquet"))
    run.run(cfg, s, str(tmp_path / "r"), ["mock-old", "mock-new"])
    judge.run_judge(cfg, str(tmp_path / "r"), cfg["paths"]["frame"])
    analyze.analyze(cfg, str(tmp_path / "r"), cfg["paths"]["frame"])
    assert (tmp_path / "r" / "analysis" / "report.md").exists()


def test_repeats_are_resumable(tmp_path):
    from k12aii import run, sample
    from k12aii.common import load_responses
    cfg = load_cfg()
    s = sample.draw(cfg, n_per_group=12, seed=3, out=str(tmp_path / "s.parquet"))
    run.run(cfg, s, str(tmp_path / "r"), ["mock-old"], ["kb"], repeats=1)
    run.run(cfg, s, str(tmp_path / "r"), ["mock-old"], ["kb"], repeats=2)    # only the 2nd repeat is new
    R = load_responses(tmp_path / "r", "kb")
    assert len(R) == 48 and {r["rep"] for r in R} == {0, 1}
    run.run(cfg, s, str(tmp_path / "r"), ["mock-old"], ["kb"], repeats=2)    # nothing left to do
    assert len(load_responses(tmp_path / "r", "kb")) == 48


def test_enrollment_matched_sample_is_balanced(tmp_path):
    import numpy as np
    import pandas as pd
    from k12aii import sample
    cfg = load_cfg()
    s = pd.read_parquet(sample.draw(cfg, n_per_group=30, seed=5, out=str(tmp_path / "m.parquet")))
    w, n = s[s.from_wikipedia == 1], s[s.from_wikipedia == 0]
    smd = (w.log_enroll.mean() - n.log_enroll.mean()) / np.sqrt((w.log_enroll.var() + n.log_enroll.var()) / 2)
    assert abs(smd) < 0.1
    assert s.groupby("pair_id").from_wikipedia.agg(["sum", "size"]).eq([1, 2]).all(axis=None)   # one wiki + one non-wiki per pair
    assert (s.match_gap_log <= cfg["sampling"]["caliper_log"]).all()


def test_multiple_choice_pipeline_with_mock(tmp_path):
    import json
    import pandas as pd
    from k12aii import exposure
    cfg = load_cfg()
    cfg["judge"].update(provider="mock", model="mock")
    out = tmp_path / "e"
    out.mkdir()
    pool = pd.DataFrame({"nces_id": ["a", "b"], "school_name": ["A High School", "B High School"], "city": ["X", "Y"], "state": ["IL", "TX"], "group": ["exposed", "unexposed"],
                         "text": ["A High School was founded in 1952. Its mascot is the Eagles. It has an IB program."] * 2, "prefix": ["p"] * 2, "target": ["t"] * 2,
                         "sector": ["public"] * 2, "log_pageviews": [5.0, 5.2], "log_enroll": [6.0, 6.1], "months_from_cutoff": [-5.0, 5.0]})
    pool.to_parquet(out / "pool.parquet")
    (out / "split.json").write_text(json.dumps({"model": "gpt-4o", "cutoff": "2023-10-01"}))
    with open(out / "qa.jsonl", "w") as f:
        for n in ("a", "b"):
            f.write(json.dumps({"nces_id": n, "qa": [{"q": "Founded?", "a": "1952"}, {"q": "Mascot?", "a": "Eagles"}, {"q": "Program?", "a": "IB"}]}) + "\n")
    exposure.build_mc(cfg, out)
    items = [json.loads(l) for l in open(out / "mc.jsonl")]
    assert all(len(r["items"]) == 3 for r in items)
    for r in items:
        for x in r["items"]:
            assert len(set(x["options"])) == 4 and x["options"]["ABCD".index(x["correct"])] in ("1952", "Eagles", "IB")
    exposure.run_models(cfg, out, ["mock-old"], ("mc", "mc_blind"))
    s = exposure.mc_scores(out, "mc")
    assert len(s) == 2 and s.n_q.eq(3).all() and s.answered.eq(3).all()


def test_direct_pipeline_with_mock(tmp_path):
    import json
    import pandas as pd
    from k12aii import exposure
    cfg = load_cfg()
    cfg["judge"].update(provider="mock", model="mock")
    out = tmp_path / "e"
    out.mkdir()
    rows = []
    for i, g in enumerate(["exposed"] * 6 + ["unexposed"] * 6 + ["famous"] * 4):
        rows.append({"nces_id": f"n{i}", "school_name": f"S{i} High School", "city": "X", "state": "IL", "group": g, "pageid": 1000 + i,
                     "text": "S was founded in 1952. Mascot Eagles.", "prefix": "p", "target": "t", "sector": "public", "log_pageviews": 5.0 + i / 10,
                     "log_enroll": 6.0 + i / 10, "months_from_cutoff": -5.0 if g == "exposed" else 5.0, "enrollment": 500})
    pd.DataFrame(rows).to_parquet(out / "pool.parquet")
    (out / "split.json").write_text(json.dumps({"model": "gpt-4o", "cutoff": "2023-10-01"}))
    with open(out / "truth.jsonl", "w") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps({"nces_id": r["nces_id"], "year": 1940 + 3 * i, "mascot": "Eagles", "colors": None}) + "\n")
    exposure.run_models(cfg, out, ["mock-old"], ("direct",))
    exposure.grade_direct(cfg, out)
    txt = "\n".join(exposure.direct_report(out, pd.read_parquet(out / "pool.parquet"), cfg))
    assert "Founding year" in txt and "Positive-control gate" in txt and "Mascot and school colors" in txt
    assert exposure.parse_direct("Y: 1904 | conf: 85 | basis: A")["year"] == {"ans": 1904, "conf": 85, "basis": "A"}
