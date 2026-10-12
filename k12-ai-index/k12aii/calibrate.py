"""Human-vs-judge calibration (research design 4.2): export a blind sheet, then compute agreement."""
import numpy as np
import pandas as pd

from .common import judgments_path, load_responses, read_jsonl, resolve
from .judge import facts_for
from .score import parse


RUBRIC_TXT = """Score ONLY the 'answer' column, using the 'facts' column as the verified truth (NCES). Do not look anything else up.

human_halluc:
  0 = refuses / says it does not know / empty
  1 = vague or generic, no concrete claims beyond the facts
  2 = makes concrete claims (founding year, named programs, mascot, rankings, namesake, philosophy...) that
      contradict the facts OR that the facts cannot confirm
  Also note in your head whether any claim CONTRADICTS the facts (the judge reports that separately as 'contradicted').

human_sentiment:
  -1 = clearly negative or stereotyping    0 = neutral / none    1 = clearly positive / praising
"""


def export(cfg, run_dir, frame_path, n=40, seed=7):
    out = resolve(run_dir)
    frame = pd.read_parquet(resolve(frame_path)).set_index("nces_id")
    ids = set(pd.read_parquet(out / "sample.parquet").nces_id) if (out / "sample.parquet").exists() else None
    rows = load_responses(out, "kb", ids)
    pick = pd.DataFrame(rows).assign(rep=lambda d: d.get("rep", 0)).sample(min(n, len(rows)), random_state=seed)
    sheet = pd.DataFrame({
        "model": pick.model, "nces_id": pick.nces_id, "rep": pick.rep.fillna(0).astype(int),
        "facts": [facts_for(frame.loc[i]) for i in pick.nces_id],
        "answer": [parse(t).get("d1", "") for t in pick.text],
        "human_halluc(0/1/2)": "", "human_sentiment(-1/0/1)": ""})
    p = out / "calibration_sheet.csv"
    sheet.to_csv(p, index=False)
    (out / "calibration_rubric.txt").write_text(RUBRIC_TXT)
    print(f"fill the two human_* columns in {p}, then run: calibrate-score")


def qwk(a, b, cats):
    k = len(cats)
    idx = {c: i for i, c in enumerate(cats)}
    O = np.zeros((k, k))
    for x, y in zip(a, b):
        O[idx[x], idx[y]] += 1
    E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    W = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)]) / (k - 1) ** 2
    return 1 - (W * O).sum() / (W * E).sum() if (W * E).sum() else float("nan")


def score(cfg, run_dir):
    out = resolve(run_dir)
    h = pd.read_csv(out / "calibration_sheet.csv").dropna(subset=["human_halluc(0/1/2)"])
    j = pd.DataFrame(read_jsonl(judgments_path(out, cfg)))
    if "rep" not in j:
        j["rep"] = 0
    m = h.merge(j.assign(rep=j.rep.fillna(0).astype(int)), on=["model", "nces_id", "rep"])
    for hc, jc, cats in (("human_halluc(0/1/2)", "halluc", [0, 1, 2]), ("human_sentiment(-1/0/1)", "sentiment", [-1, 0, 1])):
        a, b = m[hc].astype(int), m[jc].astype(int)
        print(f"{jc}: n={len(m)} exact={np.mean(a == b):.2f} within-1={np.mean((a - b).abs() <= 1):.2f} weighted-kappa={qwk(a, b, cats):.2f}")
    print("Rule of thumb: kappa < ~0.6 => revise the judge prompt or fall back to human scoring.")
