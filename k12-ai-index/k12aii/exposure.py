"""Exposure experiments for ONE model: did it SEE the Wikipedia text?

The model's own training cutoff (config.yaml models[].cutoff) splits the school pages into two contiguous groups:
  exposed   = page created on/before the cutoff  (the model could have read it)
  unexposed = page created after the cutoff      (the model cannot have read it)
Design 1  verbatim continuation of the opening text (overlap with the true continuation).
Design 2  wiki-only facts (founding year, namesake, mascot, programs...) extracted from the article lead.
Reference: NCES-templated paragraphs of non-wiki schools (machine-generated, cannot have been seen).
Page creation = first-revision timestamp from the MediaWiki API (read-only). Everything else is local + the model calls you start.
"""
import glob
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
from tqdm import tqdm

from .common import ans_hash, append_jsonl, load_responses, model_by_key, read_jsonl, resolve
from .dose import load_prominence
from .providers import available, complete

UA = {"User-Agent": "k12-ai-index-research/0.1 (SchoolData open research; read-only)"}
PREFIX_WORDS, TARGET_WORDS = 20, 25


def model_cutoff(cfg, key):
    c = model_by_key(cfg, key).get("cutoff")
    if not c:
        raise ValueError(f"model {key!r} has no cutoff in config.yaml; the exposure split needs one")
    c = str(c)
    t = pd.Timestamp(c)
    return t if len(c) > 7 else t + pd.offsets.MonthEnd(0)     # 'YYYY-MM-DD' used as is; 'YYYY-MM' -> last day of that month


# ------------------------------------------------------------ wiki creation dates
def _first_revision(pageid, retries=5):
    p = {"action": "query", "pageids": pageid, "prop": "revisions", "rvlimit": 1, "rvdir": "newer", "rvprop": "timestamp", "format": "json"}
    for i in range(retries):
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php", params=p, headers=UA, timeout=40)
            pg = next(iter(r.json().get("query", {}).get("pages", {}).values()), {})
            if pg.get("revisions"):
                return pg["revisions"][0]["timestamp"]
        except Exception:
            pass
        time.sleep(2 + 3 * i)
    return None


def fetch_created(pageids, cache_path, delay=0.8):
    """Cache SUCCESSES only, so failed lookups are retried next time."""
    cache = json.load(open(cache_path)) if cache_path.exists() else {}
    cache = {k: v for k, v in cache.items() if v}
    todo = [str(p) for p in pageids if str(p) not in cache]
    for pid in tqdm(todo, desc="wiki first revisions"):
        v = _first_revision(pid)
        if v:
            cache[pid] = v
        time.sleep(delay)
        if len(cache) % 20 == 0:
            json.dump(cache, open(cache_path, "w"))
    json.dump(cache, open(cache_path, "w"))
    return cache


# ------------------------------------------------------------ pool
def _words(t):
    return re.findall(r"\S+", t or "")


def split_text(text):
    w = _words(text)
    if len(w) < PREFIX_WORDS + TARGET_WORDS:
        return None
    return " ".join(w[:PREFIX_WORDS]), " ".join(w[PREFIX_WORDS:PREFIX_WORDS + TARGET_WORDS])


def _estimator(cache):
    cal = pd.DataFrame({"pageid": [int(k) for k in cache], "created": pd.to_datetime(list(cache.values()), utc=True).tz_localize(None)}).sort_values("pageid")
    ts, pid = cal.created.astype("int64").values, cal.pageid.values
    return lambda p: pd.to_datetime(np.interp(p, pid, ts))


def balance_table(pool):
    w = pool[pool.group.isin(["exposed", "unexposed"])]
    g = w.groupby("group")
    return pd.DataFrame({
        "n": g.size(),
        "public share": g["sector"].apply(lambda x: (x == "public").mean()),
        "pure high school share": g["level"].apply(lambda x: (x == "high").mean()),
        "median enrollment": g["enrollment"].median(),
        "median page views (60d)": g["log_pageviews"].apply(lambda x: float(np.expm1(x.median()))),
        "median lead words": g["text"].apply(lambda x: float(x.str.split().str.len().median())),
        "median months from cutoff": g["months_from_cutoff"].median()}).round(2)


def build_pool(cfg, run_dir, model="gpt-4o", n_ctrl=40, seed=11, fetch=True):
    out = resolve(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    cut = model_cutoff(cfg, model)
    frame = pd.read_parquet(resolve(cfg["paths"]["frame"]))
    hf = pd.concat(pd.read_parquet(f) for f in sorted(glob.glob(str(resolve(cfg["paths"]["hf_parquet_glob"])))))[["nces_id", "text"]]
    P = load_prominence(cfg)
    m = pd.read_csv(resolve(cfg["paths"]["wiki_matches"]), dtype=str)[["wiki_pageid", "nces_school_id"]].drop_duplicates("nces_school_id")
    W = (frame[frame.from_wikipedia == 1].merge(hf, on="nces_id")
         .merge(m, left_on="nces_id", right_on="nces_school_id").merge(P, on="nces_id", how="left"))
    if cfg["exposure"].get("high_school_only"):
        W = W[pd.to_numeric(W.hi_n, errors="coerce") >= 12]
    sp = W.text.map(split_text)
    W = W[sp.notna()].copy()
    W["prefix"], W["target"] = zip(*sp[sp.notna()])
    W["pageid"] = W.wiki_pageid.astype(int)

    cache_path = out / "wiki_created.json"
    cache = {k: v for k, v in (json.load(open(cache_path)) if cache_path.exists() else {}).items() if v}
    est = _estimator(cache)
    W["est"] = est(W.pageid)
    print(f"{model}: assumed knowledge cutoff {cut.date()} (config; unverified). Pages with a long enough lead: {len(W):,}")

    margin = pd.DateOffset(months=1)                       # estimates are approximate: look a bit past the line, then use exact dates
    unexp = W[W.est > cut - margin]
    expo = W[W.est <= cut + margin].assign(d=lambda d: (cut - d.est).abs()).nsmallest(2 * max(len(unexp), 30), "d")
    cand = pd.concat([unexp, expo]).drop_duplicates("nces_id")
    if fetch:
        cache = fetch_created(cand.pageid.tolist(), cache_path)
    cand["created"] = pd.to_datetime(cand.pageid.astype(str).map(cache), utc=True, errors="coerce").dt.tz_localize(None)
    K = cand[cand.created.notna()].copy()
    U = K[K.created > cut]
    E = K[K.created <= cut].assign(d=lambda d: (cut - d.created)).nsmallest(len(U), "d")      # the pages closest before the cutoff
    U = U.assign(group="unexposed"); E = E.assign(group="exposed")
    pool = pd.concat([E, U])
    pool["months_from_cutoff"] = (pool.created - cut).dt.days / 30.44

    N = frame[frame.eligible & (frame.from_wikipedia == 0)].merge(hf, on="nces_id")
    sp = N.text.map(split_text)
    N = N[sp.notna()].copy()
    N["prefix"], N["target"] = zip(*sp[sp.notna()])
    ctrl = N.sample(min(n_ctrl, len(N)), random_state=seed).assign(group="NCES_template")
    pool = pd.concat([pool, ctrl], ignore_index=True)
    keep = ["nces_id", "school_name", "city", "state", "sector", "level", "from_wikipedia", "enrollment", "log_enroll", "log_pageviews",
            "log_article_chars", "school_age", "pageid", "created", "months_from_cutoff", "group", "prefix", "target", "text"]
    pool = pool.reindex(columns=keep)
    pool.to_parquet(out / "pool.parquet")
    pool.attrs = {}
    json.dump({"model": model, "cutoff": str(cut.date())}, open(out / "split.json", "w"))
    print("\npool:", pool.group.value_counts().to_dict(), "->", out / "pool.parquet")
    print(f"exposed: created {E.created.min().date()} .. {E.created.max().date()} | unexposed: created {U.created.min().date()} .. {U.created.max().date()}")
    print("\nbalance of the two wiki groups:")
    print(balance_table(pool).to_string())
    return pool


def add_positive_control(cfg, run_dir, n=15):
    """Famous schools (most-viewed Wikipedia pages): the model is MOST likely to have memorised these leads.
    If the continuation test cannot show higher overlap here, it simply cannot detect memorisation."""
    out = resolve(run_dir)
    pool = pd.read_parquet(out / "pool.parquet")
    pool = pool[pool.group != "famous"]
    frame = pd.read_parquet(resolve(cfg["paths"]["frame"]))
    hf = pd.concat(pd.read_parquet(f) for f in sorted(glob.glob(str(resolve(cfg["paths"]["hf_parquet_glob"])))))[["nces_id", "text"]]
    P = load_prominence(cfg)
    m = pd.read_csv(resolve(cfg["paths"]["wiki_matches"]), dtype=str)[["wiki_pageid", "nces_school_id"]].drop_duplicates("nces_school_id")
    W = frame[frame.from_wikipedia == 1].merge(hf, on="nces_id").merge(m, left_on="nces_id", right_on="nces_school_id").merge(P, on="nces_id", how="left")
    sp = W.text.map(split_text)
    W = W[sp.notna() & ~W.nces_id.isin(pool.nces_id)].copy()
    W["prefix"], W["target"] = zip(*sp.loc[W.index])
    W["pageid"] = W.wiki_pageid.astype(int)
    top = W.nlargest(n, "pageviews").assign(group="famous")
    keep = [c for c in pool.columns if c in top.columns]
    out_pool = pd.concat([pool, top[keep]], ignore_index=True)
    out_pool.to_parquet(out / "pool.parquet")
    print("positive control (most-viewed school pages):", ", ".join(f"{r.school_name} ({int(r.pageviews):,} views/60d)" for r in top.itertuples()))
    return out_pool


# ------------------------------------------------------------ prompts
CONT_PROMPT = """Below is the beginning of a text about a US school. Continue the text EXACTLY as it was originally written, from where it stops, for about {n} words.
Output only the continuation, nothing else. If you do not remember the original wording, write your best guess of what it said.
Do NOT use search, browsing, or any external tool.

Text:
{prefix}"""

QA_PROMPT = """Answer the following questions about {school} (in {city}, {state}), using ONLY knowledge you already have.
Do NOT use search, browsing, or any external tool. If you do not know an answer, write UNKNOWN. Do not guess and do not make anything up.

Answer in exactly this format, one line per question:
{questions}
"""

QA_EXTRACT = """From the school description below, write up to 3 factual question-answer pairs.
Rules:
- The answer must be stated explicitly in the text and be short (1-6 words).
- The question must be answerable without seeing the text, and must not repeat the answer.
- Prefer: founding year, who/what the school is named after, mascot or team name, school colors, athletic conference, notable alumni, named programs, historic facts.
- Do NOT ask about: public/private, grade levels, district, enrollment, city/state, charter status.
- If nothing qualifies, return [].
Return ONLY a JSON list like [{{"q": "...", "a": "..."}}].

Description:
\"\"\"{text}\"\"\""""

GRADE_PROMPT = """Grade a model's answer against the reference answer.
Question: {q}
Reference answer: {a}
Model answer: {m}
Return ONLY JSON: {{"grade": "correct" | "incorrect" | "abstain"}}.
correct = same fact as the reference (minor wording differences are fine); abstain = says unknown / refuses; incorrect = anything else."""


def _mock(task, prompt):
    if task == "truth":
        return json.dumps({"year": 1952, "mascot": "Eagles", "colors": None})
    if task == "distract":
        return json.dumps({str(i): [f"wrong {i}a", f"wrong {i}b", f"wrong {i}c"] for i in range(1, 4)})
    if task == "extract":
        return json.dumps([{"q": "In what year was the school founded?", "a": "1952"}, {"q": "What is the school mascot?", "a": "Eagles"}])
    if task == "grade":
        return json.dumps({"grade": "abstain" if "UNKNOWN" in prompt.split("Model answer:")[1] else "incorrect"})
    return None


# ------------------------------------------------------------ QA build / run / grade
WIKI_GROUPS = ("exposed", "unexposed")
MC_GROUPS = ("exposed", "unexposed", "famous")      # famous = positive control


def _judge_call(cfg, prompt, task):
    jm = cfg["judge"]
    if jm["provider"] == "mock":
        return _mock(task, prompt)
    return complete({"temperature": 0, **jm}, prompt, jm.get("max_tokens", 800))["text"]


def build_qa(cfg, run_dir):
    out = resolve(run_dir)
    pool = pd.read_parquet(out / "pool.parquet")
    pool = pool[pool.group.isin(MC_GROUPS)]
    f = out / "qa.jsonl"
    done = {r["nces_id"] for r in read_jsonl(f)}

    def work(r):
        try:
            txt = _judge_call(cfg, QA_EXTRACT.format(text=r["text"][:1800]), "extract")
            items = json.loads(re.search(r"\[.*\]", txt, re.S).group(0))
            return {"nces_id": r["nces_id"], "qa": [x for x in items if x.get("q") and x.get("a")][:3]}
        except Exception as e:
            return {"nces_id": r["nces_id"], "qa": [], "error": str(e)[:150]}
    todo = [r for r in pool.to_dict("records") if r["nces_id"] not in done]
    with ThreadPoolExecutor(cfg["concurrency"]) as ex:
        for fu in tqdm(as_completed([ex.submit(work, r) for r in todo]), total=len(todo), desc="extract QA"):
            append_jsonl(f, fu.result())
    q = read_jsonl(f)
    print(f"schools with >=1 question: {sum(1 for r in q if r['qa'])} / {len(q)}; questions: {sum(len(r['qa']) for r in q)}")


MC_DISTRACT = """You write wrong answer options for multiple-choice questions.
School description (the source of truth):
\"\"\"{text}\"\"\"

Questions with their correct answers:
{items}

For EACH question write 3 WRONG options: the same kind and format as the correct answer, equally specific, and plausible to someone who does not know this school
(for a year give other nearby years; for a name give similar-type names; for a mascot give other typical mascots).
A wrong option must not be stated in the description and must not be correct or equivalent to the correct answer.
Return ONLY JSON like {{"1": ["...", "...", "..."], "2": ["...", "...", "..."]}}."""

MC_PROMPT = """Answer the following multiple-choice questions about {school} (in {city}, {state}), using ONLY knowledge you already have.
Do NOT use search, browsing, or any external tool. You MUST choose exactly one option for every question; if you are unsure, give your best guess.

{questions}

Answer in exactly this format, one line per question (a single letter):
1: <letter>
2: <letter>
..."""

MC_BLIND_PROMPT = """Answer the following multiple-choice questions about a US high school. The school's name is withheld on purpose.
Do NOT use search, browsing, or any external tool. You MUST choose exactly one option for every question; if you are unsure, give your best guess.

{questions}

Answer in exactly this format, one line per question (a single letter):
1: <letter>
2: <letter>
..."""

LETTERS = "ABCD"


def build_mc(cfg, run_dir, seed=17):
    """4-option questions from the extracted Q/A: Claude writes 3 distractors; option order is fixed here (seeded) and stored with the key."""
    import random
    out = resolve(run_dir)
    pool = pd.read_parquet(out / "pool.parquet").set_index("nces_id")
    qa = {r["nces_id"]: r["qa"] for r in read_jsonl(out / "qa.jsonl") if r["qa"] and r["nces_id"] in pool.index}
    f = out / "mc.jsonl"
    done = {r["nces_id"] for r in read_jsonl(f)}

    def work(nid):
        items = qa[nid]
        txt = "\n".join(f"{i + 1}. Q: {x['q']}  A: {x['a']}" for i, x in enumerate(items))
        try:
            raw = _judge_call(cfg, MC_DISTRACT.format(text=pool.loc[nid, "text"][:1800], items=txt), "distract")
            d = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            res = []
            for i, x in enumerate(items):
                ds = [str(v) for v in d.get(str(i + 1), []) if str(v).strip() and str(v).strip().lower() != x["a"].strip().lower()][:3]
                if len(ds) < 3:
                    continue
                opts = [x["a"]] + ds
                random.Random(f"{seed}-{nid}-{i}").shuffle(opts)
                res.append({"q": x["q"], "options": opts, "correct": LETTERS[opts.index(x["a"])]})
            return {"nces_id": nid, "items": res}
        except Exception as e:
            return {"nces_id": nid, "items": [], "error": str(e)[:150]}
    todo = [n for n in qa if n not in done]
    with ThreadPoolExecutor(cfg["concurrency"]) as ex:
        for fu in tqdm(as_completed([ex.submit(work, n) for n in todo]), total=len(todo), desc="write distractors"):
            append_jsonl(f, fu.result())
    rows = read_jsonl(f)
    n = [len(r["items"]) for r in rows]
    print(f"schools with MC items: {sum(1 for x in n if x)} / {len(rows)}; questions: {sum(n)}")


# ------------------------------------------------------------ direct forced questions (year / mascot / colors) with confidence + basis
TRUTH_EXTRACT = """From the school article below, extract ONLY facts that are stated explicitly. Return ONLY JSON:
{{"year": <4-digit founding/opening year as an integer, or null>, "mascot": "<team name or mascot, or null>", "colors": "<school colors, or null>"}}
Use null for anything not stated. Do not guess.

Article:
\"\"\"{text}\"\"\""""

DIRECT_PROMPT = """Answer the following about {school} (in {city}, {state}), using ONLY knowledge you already have.
Do NOT use search, browsing, or any external tool. You MUST give your single best answer to every item, even if you are unsure; do not write UNKNOWN.
After each answer give your confidence that it is correct (0-100) and the basis of your answer:
  A = I recall specific information about this particular school
  B = I inferred it from the school's name, location or type of school
  C = I am guessing at random

Answer in exactly this format, one line per item:
Y: <founding year, 4 digits> | conf: <0-100> | basis: <A, B or C>
M: <mascot or team nickname> | conf: <0-100> | basis: <A, B or C>
C: <school colors> | conf: <0-100> | basis: <A, B or C>"""


def build_truth(cfg, run_dir):
    out = resolve(run_dir)
    pool = pd.read_parquet(out / "pool.parquet")
    pool = pool[pool.group.isin(MC_GROUPS)]
    f = out / "truth.jsonl"
    done = {r["nces_id"] for r in read_jsonl(f)}
    arts = {}                                   # full article text (not just the lead): far more facts are stated in the body
    want = set(pool.pageid.astype(int).astype(str))
    for line in open(resolve(cfg["paths"]["wiki_articles"])):
        a = json.loads(line)
        if str(a["pageid"]) in want:
            arts[str(a["pageid"])] = a["text"]

    def work(r):
        try:
            body = arts.get(str(int(r["pageid"])), r["text"])
            d = json.loads(re.search(r"\{.*\}", _judge_call(cfg, TRUTH_EXTRACT.format(text=body[:12000]), "truth"), re.S).group(0))
            yr = d.get("year")
            yr = int(yr) if yr is not None and str(yr).strip().isdigit() and 1600 <= int(yr) <= 2026 else None
            return {"nces_id": r["nces_id"], "year": yr, "mascot": d.get("mascot") or None, "colors": d.get("colors") or None}
        except Exception as e:
            return {"nces_id": r["nces_id"], "year": None, "mascot": None, "colors": None, "error": str(e)[:150]}
    todo = [r for r in pool.to_dict("records") if r["nces_id"] not in done]
    with ThreadPoolExecutor(cfg["concurrency"]) as ex:
        for fu in tqdm(as_completed([ex.submit(work, r) for r in todo]), total=len(todo), desc="extract truth"):
            append_jsonl(f, fu.result())
    T = pd.DataFrame(read_jsonl(f)).merge(pool[["nces_id", "group"]], on="nces_id")
    print(T.groupby("group")[["year", "mascot", "colors"]].agg(lambda s: int(s.notna().sum())).to_string())


def parse_direct(text):
    out = {}
    for key, name in (("Y", "year"), ("M", "mascot"), ("C", "colors")):
        m = re.search(rf"^\s*{key}\s*[:.)-]\s*(.*)$", text or "", re.M)
        if not m:
            continue
        line = m.group(1)
        ans = line.split("|")[0].strip()
        conf = re.search(r"conf\w*\s*[:=]\s*(\d{1,3})", line, re.I)
        basis = re.search(r"basis\s*[:=]\s*\(?([ABC])\b", line, re.I)
        if name == "year":
            y = re.search(r"\b(1[6-9]\d\d|20[0-2]\d)\b", ans)
            ans = int(y.group(1)) if y else None
        out[name] = {"ans": ans, "conf": min(int(conf.group(1)), 100) if conf else np.nan, "basis": basis.group(1).upper() if basis else None}
    return out


def grade_direct(cfg, run_dir):
    """Mascot / colors answers judged against the article by the judge model (year is scored numerically)."""
    out = resolve(run_dir)
    truth = {r["nces_id"]: r for r in read_jsonl(out / "truth.jsonl")}
    gf = out / f"direct_grades__{re.sub(r'[^A-Za-z0-9._-]', '_', cfg['judge']['model'])}.jsonl"
    done = {(g["model"], g["nces_id"], g["field"], g.get("ans_hash")) for g in read_jsonl(gf) if "grade" in g}
    qtext = {"mascot": "What is the school's mascot or team nickname?", "colors": "What are the school's colors?"}
    jobs = []
    for r in load_responses(out, "direct"):
        d = parse_direct(r["text"])
        for field in ("mascot", "colors"):
            t = truth.get(r["nces_id"], {}).get(field)
            ans = (d.get(field) or {}).get("ans")
            if t and ans and (r["model"], r["nces_id"], field, ans_hash(str(ans))) not in done:
                jobs.append((r, field, t, str(ans)))

    def work(job):
        r, field, t, ans = job
        try:
            txt = _judge_call(cfg, GRADE_PROMPT.format(q=qtext[field], a=t, m=ans), "grade")
            return {"model": r["model"], "nces_id": r["nces_id"], "field": field, "ans_hash": ans_hash(ans), **json.loads(re.search(r"\{.*\}", txt, re.S).group(0))}
        except Exception as e:
            return {"model": r["model"], "nces_id": r["nces_id"], "field": field, "ans_hash": ans_hash(ans), "error": str(e)[:150]}
    with ThreadPoolExecutor(cfg["concurrency"]) as ex:
        for fu in tqdm(as_completed([ex.submit(work, j) for j in jobs]), total=len(jobs), desc="grade direct"):
            append_jsonl(gf, fu.result())
    print("grade errors:", sum(1 for g in read_jsonl(gf) if "error" in g))
    return gf


def direct_report(out, pool, cfg):
    import statsmodels.formula.api as smf
    from scipy import stats
    if not (out / "truth.jsonl").exists():
        return []
    T = pd.DataFrame(read_jsonl(out / "truth.jsonl"))
    rows = []
    for r in load_responses(out, "direct"):
        d = parse_direct(r["text"])
        row = {"model": r["model"], "nces_id": r["nces_id"]}
        for f in ("year", "mascot", "colors"):
            x = d.get(f) or {}
            row.update({f"{f}_ans": x.get("ans"), f"{f}_conf": x.get("conf", np.nan), f"{f}_basis": x.get("basis")})
        rows.append(row)
    if not rows:
        return []
    meta = pool.drop(columns=["text", "prefix", "target"])
    D = pd.DataFrame(rows).merge(T.rename(columns={"year": "year_true", "mascot": "mascot_true", "colors": "colors_true"}).drop(columns=["error"], errors="ignore"), on="nces_id").merge(meta, on="nces_id")
    rep = ["\n## Direct forced questions: founding year, mascot, school colors (with confidence and basis)\n",
           "School named, answer forced. Truth = what the Wikipedia article states. Year is scored as absolute error in years; mascot and colors are judged by "
           f"{cfg['judge']['model']}. `guess baseline` = always answering the median founding year of the wiki schools in this pool.\n"]
    # ---- year
    Y = D[D.year_true.notna() & D.year_ans.notna()].copy()
    Y["year_ans"] = Y.year_ans.astype(float)
    Y["err"] = (Y.year_ans - Y.year_true).abs()
    ref = Y[Y.group.isin(WIKI_GROUPS)].year_true.median()
    Y["base_err"] = (ref - Y.year_true).abs()
    Y["le2"] = (Y.err <= 2).astype(int)
    Y["logerr"] = np.log1p(Y.err)
    tab = Y.groupby("group").agg(n=("err", "size"), median_error_years=("err", "median"), within_2_years=("le2", "mean"),
                                 guess_baseline_median_error=("base_err", "median"), mean_confidence=("year_conf", "mean"))
    rep += ["### Founding year\n", _md(tab.round(2)), "\n"]
    fam = Y[Y.group == "famous"]
    if len(fam):
        ok = fam.err.median() <= 0.5 * fam.base_err.median()
        rep.append(f"**Positive-control gate (famous schools)**: median error {fam.err.median():.1f} y vs guess baseline {fam.base_err.median():.1f} y -> "
                   f"{'PASS' if ok else 'FAIL'} (rule: error <= half the baseline). {'The test can detect knowledge.' if ok else 'Do NOT interpret the exposed/unexposed comparison.'}\n")
    E, U = Y[Y.group == "exposed"], Y[Y.group == "unexposed"]
    rep += ["| contrast (exposed - unexposed) | diff | 95% CI (bootstrap over schools) |", "|---|---|---|"]
    for lab, a, b in (("mean log(1+error)", E.logerr, U.logerr), ("share within 2 years", E.le2, U.le2)):
        d = _boot_diff(a, b)
        rep.append(f"| {lab} | {d[0]:+.3f} | [{d[1]:+.3f}, {d[2]:+.3f}] |")
    if len(E) > 3 and len(U) > 3:
        rep.append(f"\nMann-Whitney on absolute error: p={stats.mannwhitneyu(E.err, U.err).pvalue:.3f} (n={len(E)} vs {len(U)}); median error {E.err.median():.1f} (exposed) vs {U.err.median():.1f} (unexposed)\n")
    W = Y[Y.group.isin(WIKI_GROUPS)].assign(post=lambda d: (d.group == "unexposed").astype(int), age=lambda d: 2026 - d.year_true).dropna(subset=["log_enroll", "log_pageviews"])
    if W.post.nunique() == 2 and len(W) > 20:
        for lab, f, d in (("all schools", "logerr ~ post + age + log_enroll + log_pageviews + C(sector)", W),
                          ("founded before 2015 only", "logerr ~ post + age + log_enroll + log_pageviews + C(sector)", W[W.year_true < 2015])):
            if d.post.nunique() == 2 and len(d) > 15:
                r = smf.ols(f, d).fit(cov_type="HC3")
                lo, hi = r.conf_int().loc["post"]
                rep.append(f"- OLS log(1+error) ~ unexposed + school age + enrollment + page views + sector, {lab}: unexposed {r.params['post']:+.3f} [{lo:+.3f}, {hi:+.3f}] p={r.pvalues['post']:.3f} (n={int(r.nobs)})")
    # ---- confidence / basis
    rep += ["\n### Confidence and stated basis (founding year)\n"]
    Y["correct"] = Y.le2
    c = Y.groupby("group").agg(conf_when_correct=("year_conf", lambda x: x[Y.loc[x.index, "correct"] == 1].mean()),
                               conf_when_wrong=("year_conf", lambda x: x[Y.loc[x.index, "correct"] == 0].mean()))
    rep += [_md(c.round(1)), "\n", "Stated basis (A = recalls this school, B = inferred from name/place, C = random guess): share and accuracy within 2 years\n",
            _md(Y.groupby(["group", "year_basis"]).agg(n=("err", "size"), within_2_years=("le2", "mean")).round(2)), "\n",
            "These are self-reports and are NOT evidence of where the knowledge came from; they only show whether the model's stated certainty tracks being right.\n"]
    # ---- mascot / colors
    gfs = sorted(out.glob("direct_grades__*.jsonl"))
    if gfs:
        G = pd.DataFrame([g for g in read_jsonl(gfs[-1]) if "grade" in g])
        if len(G):
            G["correct"] = (G.grade == "correct").astype(int)
            G = G.merge(meta[["nces_id", "group"]], on="nces_id")
            rep += ["### Mascot and school colors (accuracy)\n", _md(G.groupby(["field", "group"]).agg(n=("correct", "size"), accuracy=("correct", "mean")).round(3)), "\n"]
            for fld in ("mascot", "colors"):
                g = G[G.field == fld]
                d = _boot_diff(g[g.group == "exposed"].correct, g[g.group == "unexposed"].correct)
                if not np.isnan(d[0]):
                    rep.append(f"- {fld}: exposed - unexposed accuracy {d[0]:+.3f} [{d[1]:+.3f}, {d[2]:+.3f}]")
            top = D.mascot_true.dropna().str.lower().value_counts()
            if len(top):
                rep.append(f"- guess baseline for mascot: the most common true mascot ('{top.index[0]}') covers {top.iloc[0] / top.sum():.0%} of schools\n")
    return rep


def mc_text(items):
    return "\n\n".join(f"{i + 1}. {x['q']}\n" + "\n".join(f"   {LETTERS[j]}. {o}" for j, o in enumerate(x["options"])) for i, x in enumerate(items))


def make_prompt(task, r, qa=None):
    if task == "direct":
        return DIRECT_PROMPT.format(school=r["school_name"], city=r["city"], state=r["state"])
    if task in ("mc", "mc_blind"):
        tmpl = MC_PROMPT if task == "mc" else MC_BLIND_PROMPT
        return tmpl.format(school=r["school_name"], city=r["city"], state=r["state"], questions=mc_text(qa))
    if task == "cont":
        return CONT_PROMPT.format(n=TARGET_WORDS, prefix=r["prefix"])
    qs = "\n".join(f"{i + 1}: <your answer to: {x['q']}>" for i, x in enumerate(qa))
    return QA_PROMPT.format(school=r["school_name"], city=r["city"], state=r["state"], questions=qs)


def run_models(cfg, run_dir, keys, tasks=("cont", "qa")):
    tasks = tuple(tasks)
    out = resolve(run_dir)
    pool = pd.read_parquet(out / "pool.parquet")
    qa = {r["nces_id"]: r["qa"] for r in read_jsonl(out / "qa.jsonl") if r["qa"]}
    mc = {r["nces_id"]: r["items"] for r in read_jsonl(out / "mc.jsonl") if r["items"]} if (out / "mc.jsonl").exists() else {}
    truth_ids = {r["nces_id"] for r in read_jsonl(out / "truth.jsonl") if r.get("year") or r.get("mascot") or r.get("colors")} if (out / "truth.jsonl").exists() else set()
    f = out / "responses.jsonl"
    done = {(r["model"], r["nces_id"], r["task"]) for r in read_jsonl(f) if not r.get("error")}
    for k in keys:
        m = model_by_key(cfg, k)
        if not available(m):
            print("SKIP", k, "(no API key)")
            continue
        jobs = []
        for r in pool.to_dict("records"):
            for t in tasks:
                if t == "qa" and (r["group"] not in WIKI_GROUPS or r["nces_id"] not in qa):
                    continue
                if t in ("mc", "mc_blind") and r["nces_id"] not in mc:
                    continue
                if t == "direct" and (r["group"] not in MC_GROUPS or r["nces_id"] not in truth_ids):
                    continue
                if (k, r["nces_id"], t) not in done:
                    jobs.append((r, t))
        print(f"{k}: {len(jobs)} calls")

        def work(job):
            r, t = job
            prompt = make_prompt(t, r, mc.get(r["nces_id"]) if t in ("mc", "mc_blind") else qa.get(r["nces_id"]))
            try:
                res = complete(m, prompt, 400)
                return {"model": k, "nces_id": r["nces_id"], "task": t, "prompt": prompt, **res, "ts": time.time()}
            except Exception as e:
                return {"model": k, "nces_id": r["nces_id"], "task": t, "error": str(e)[:300]}
        with ThreadPoolExecutor(cfg["concurrency"]) as ex:
            for fu in tqdm(as_completed([ex.submit(work, j) for j in jobs]), total=len(jobs)):
                append_jsonl(f, fu.result())
    recs = read_jsonl(f)
    print(f"done. errors={sum(1 for r in recs if r.get('error'))}  tool traces={sum(1 for r in recs if r.get('tool_trace'))} (must be 0)")


def grade_qa(cfg, run_dir):
    out = resolve(run_dir)
    qa = {r["nces_id"]: r["qa"] for r in read_jsonl(out / "qa.jsonl") if r["qa"]}
    gf = out / f"qa_grades__{re.sub(r'[^A-Za-z0-9._-]', '_', cfg['judge']['model'])}.jsonl"
    done = {(g["model"], g["nces_id"], g["i"], g.get("ans_hash")) for g in read_jsonl(gf) if "grade" in g}
    jobs = []
    for r in load_responses(out, "qa"):
        lines = dict(re.findall(r"^\s*(\d)\s*[:.)-]\s*(.*)$", r["text"], re.M))
        for i, x in enumerate(qa.get(r["nces_id"], [])):
            ans = lines.get(str(i + 1), "")
            if (r["model"], r["nces_id"], i, ans_hash(ans)) not in done:
                jobs.append((r, i, x, ans))

    def work(job):
        r, i, x, ans = job
        try:
            txt = _judge_call(cfg, GRADE_PROMPT.format(q=x["q"], a=x["a"], m=ans or "(no answer)"), "grade")
            return {"model": r["model"], "nces_id": r["nces_id"], "i": i, "ans_hash": ans_hash(ans), **json.loads(re.search(r"\{.*\}", txt, re.S).group(0))}
        except Exception as e:
            return {"model": r["model"], "nces_id": r["nces_id"], "i": i, "ans_hash": ans_hash(ans), "error": str(e)[:150]}
    with ThreadPoolExecutor(cfg["concurrency"]) as ex:
        for fu in tqdm(as_completed([ex.submit(work, j) for j in jobs]), total=len(jobs), desc="grade QA"):
            append_jsonl(gf, fu.result())
    print("grade errors:", sum(1 for g in read_jsonl(gf) if "error" in g))
    return gf


# ------------------------------------------------------------ scoring: continuation overlap
def _tok(t):
    return re.findall(r"[a-z0-9']+", (t or "").lower())


def lcs_run(a, b):
    """Longest contiguous run of tokens shared by a and b."""
    best = 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def ngram_recall(gen, tgt, n=4):
    g = {tuple(gen[i:i + n]) for i in range(len(gen) - n + 1)}
    t = [tuple(tgt[i:i + n]) for i in range(len(tgt) - n + 1)]
    return sum(x in g for x in t) / len(t) if t else np.nan


def score_continuation(gen_text, target):
    g, t = _tok(gen_text)[:len(_tok(target)) + 10], _tok(target)
    return {"run": lcs_run(g, t), "run_frac": lcs_run(g, t) / max(len(t), 1), "recall4": ngram_recall(g, t, 4), "recall2": ngram_recall(g, t, 2)}


# ------------------------------------------------------------ report
def _boot_diff(x, y, n=4000, seed=5):
    x, y = np.asarray(x, float), np.asarray(y, float)
    x, y = x[~np.isnan(x)], y[~np.isnan(y)]
    if len(x) < 5 or len(y) < 5:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    d = np.array([rng.choice(x, len(x)).mean() - rng.choice(y, len(y)).mean() for _ in range(n)])
    return x.mean() - y.mean(), *np.percentile(d, [2.5, 97.5])


def _md(df):
    df = df.reset_index()
    f = lambda v: f"{v:.3f}" if isinstance(v, (float, np.floating)) else str(v)
    return "\n".join(["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)] + ["| " + " | ".join(f(v) for v in r) + " |" for r in df.values])


def mc_scores(out, task):
    """One row per (model, school): share of its multiple-choice questions answered correctly, plus the letters chosen."""
    mc = {r["nces_id"]: r["items"] for r in read_jsonl(out / "mc.jsonl") if r["items"]}
    rows = []
    for r in load_responses(out, task):
        items = mc.get(r["nces_id"], [])
        picks = {int(i): l.upper() for i, l in re.findall(r"^\s*(\d+)\s*[:.)-]\s*\**\(?([A-Da-d])\b", r["text"], re.M)}
        ok = [int(picks.get(i + 1) == x["correct"]) for i, x in enumerate(items)]
        rows.append({"model": r["model"], "nces_id": r["nces_id"], "acc": float(np.mean(ok)) if ok else np.nan, "n_q": len(items),
                     "answered": sum(1 for i in range(len(items)) if (i + 1) in picks), "letters": "".join(picks.get(i + 1, "-") for i in range(len(items)))})
    return pd.DataFrame(rows)


def report(cfg, run_dir):
    import statsmodels.formula.api as smf
    from scipy import stats
    out = resolve(run_dir)
    pool = pd.read_parquet(out / "pool.parquet")
    sp = json.load(open(out / "split.json"))
    rep = ["# Exposure experiment\n", f"Model: {sp['model']}. Split at its assumed knowledge cutoff {sp['cutoff']} (config; verify). "
           f"exposed = Wikipedia page created on/before the cutoff, unexposed = after. Pool: {pool.group.value_counts().to_dict()}\n"]
    rows = []
    for r in load_responses(out, "cont"):
        s = score_continuation(r["text"], pool.loc[pool.nces_id == r["nces_id"], "target"].iloc[0])
        rows.append({"model": r["model"], "nces_id": r["nces_id"], **s})
    CT = pd.DataFrame(rows).merge(pool.drop(columns=["text", "prefix", "target"]), on="nces_id")
    if len(CT):
        rep += ["\n## Design 1. Verbatim continuation of the opening text\n",
                "`recall4` = share of the true continuation's 4-grams the model reproduced; `run_frac` = longest verbatim run / target length. "
                "NCES_template = machine-generated paragraphs the model cannot have seen (reference for how predictable such text is).\n",
                _md(CT.groupby("group")[["recall4", "run_frac", "run"]].mean().join(CT.groupby("group").size().rename("n"))), "\n",
                "| contrast | metric | diff | 95% CI (bootstrap over schools) |", "|---|---|---|---|"]
        for a, b in (("exposed", "unexposed"), ("exposed", "NCES_template"), ("unexposed", "NCES_template"), ("famous", "exposed"), ("famous", "NCES_template")):
            for met in ("recall4", "run_frac"):
                d = _boot_diff(CT[CT.group == a][met], CT[CT.group == b][met])
                rep.append(f"| {a} - {b} | {met} | {d[0]:+.3f} | [{d[1]:+.3f}, {d[2]:+.3f}] |")
        W = CT[CT.group.isin(WIKI_GROUPS)].assign(post=lambda d: (d.group == "unexposed").astype(int)).dropna(subset=["recall4", "months_from_cutoff"])
        if W.post.nunique() == 2 and len(W) > 20:
            rep.append("\nRegression on wiki pages (OLS, HC3): recall4 ~ unexposed + months from cutoff (+ controls). `unexposed` is the jump at the cutoff.\n")
            for lab, f in (("no controls", "recall4 ~ post + months_from_cutoff"),
                           ("+ log page views, log enrollment, sector", "recall4 ~ post + months_from_cutoff + log_pageviews + log_enroll + C(sector)")):
                d = W.dropna(subset=["log_pageviews", "log_enroll"]) if "log_pageviews" in f else W
                r = smf.ols(f, d).fit(cov_type="HC3")
                lo, hi = r.conf_int().loc["post"]
                rep.append(f"- {lab}: unexposed {r.params['post']:+.3f} [{lo:+.3f}, {hi:+.3f}] p={r.pvalues['post']:.3f} (n={int(r.nobs)})")
        E = CT[CT.group == "exposed"].dropna(subset=["log_pageviews", "recall4"])
        if len(E) > 10:
            rho, p = stats.spearmanr(E.log_pageviews, E.recall4)
            rep.append(f"- dose-response inside the exposed group: recall4 vs log page views rho={rho:+.2f} p={p:.3f} (n={len(E)})")

    qa = {r["nces_id"]: r["qa"] for r in read_jsonl(out / "qa.jsonl") if r["qa"]}
    gfs = sorted(out.glob("qa_grades__*.jsonl"))
    if gfs:
        G = pd.DataFrame([g for g in read_jsonl(gfs[-1]) if "grade" in g])
        if len(G):
            S = (G.assign(correct=(G.grade == "correct").astype(int), abstain=(G.grade == "abstain").astype(int), wrong=(G.grade == "incorrect").astype(int))
                 .groupby(["model", "nces_id"])[["correct", "abstain", "wrong"]].mean().reset_index().merge(pool.drop(columns=["text", "prefix", "target"]), on="nces_id"))
            rep += ["\n## Design 2. Wiki-only facts (founding year, namesake, mascot, programs...)\n",
                    f"Questions extracted from the article lead, graded against that reference by {gfs[-1].stem.split('__')[1]}. "
                    f"{sum(len(v) for v in qa.values())} questions over {len(qa)} schools.\n",
                    _md(S.groupby("group")[["correct", "abstain", "wrong"]].mean().join(S.groupby("group").size().rename("n_schools"))), "\n"]
            d = _boot_diff(S[S.group == "exposed"].correct, S[S.group == "unexposed"].correct)
            rep.append(f"exposed - unexposed accuracy: {d[0]:+.3f}, 95% CI [{d[1]:+.3f}, {d[2]:+.3f}] (bootstrap over schools)\n")
            rep.append("Reading: if reading the Wikipedia page teaches the model, exposed > unexposed on both designs. Page creation date is not the date of the text "
                       "the model saw; later pages may differ in school type or notability (see the balance table and the controlled regression).\n")
    rep += direct_report(out, pool, cfg)
    if (out / "mc.jsonl").exists():
        real, blind = mc_scores(out, "mc"), mc_scores(out, "mc_blind")
        if len(real):
            meta = pool.drop(columns=["text", "prefix", "target"])
            R = real.merge(meta, on="nces_id")
            B = blind.merge(meta, on="nces_id") if len(blind) else blind
            rep += ["\n## Design 2 (multiple choice). Wiki-only facts, 4 options, forced choice\n",
                    "Random guessing = 0.25. `blind` = the same questions with the school name withheld (checks that the options do not give the answer away). "
                    "`knowledge` = accuracy with the school named minus blind accuracy, per school.\n"]
            t = R.groupby("group").agg(acc=("acc", "mean"), n_schools=("nces_id", "size"), n_questions=("n_q", "sum"))
            if len(B):
                t["blind_acc"] = B.groupby("group").acc.mean()
            rep += [_md(t.round(3)), "\n"]
            if len(B):
                K = R[["nces_id", "group", "acc", "log_pageviews", "log_enroll", "sector", "months_from_cutoff"]].merge(
                    B[["nces_id", "acc"]].rename(columns={"acc": "blind"}), on="nces_id")
                K["knowledge"] = K.acc - K.blind
                rep += ["Knowledge above the blind baseline (mean per school):\n", _md(K.groupby("group").knowledge.mean().round(3).to_frame("knowledge")), "\n"]
            rep += ["| contrast | accuracy diff | 95% CI (bootstrap over schools) |", "|---|---|---|"]
            for a_, b_ in (("exposed", "unexposed"), ("famous", "exposed"), ("famous", "unexposed")):
                d = _boot_diff(R[R.group == a_].acc, R[R.group == b_].acc)
                rep.append(f"| {a_} - {b_} | {d[0]:+.3f} | [{d[1]:+.3f}, {d[2]:+.3f}] |")
            if len(B):
                for a_, b_ in (("exposed", "unexposed"), ("famous", "exposed")):
                    d = _boot_diff(K[K.group == a_].knowledge, K[K.group == b_].knowledge)
                    rep.append(f"| {a_} - {b_}, knowledge above blind | {d[0]:+.3f} | [{d[1]:+.3f}, {d[2]:+.3f}] |")
            W2 = R[R.group.isin(WIKI_GROUPS)].assign(post=lambda d: (d.group == "unexposed").astype(int)).dropna(subset=["acc", "months_from_cutoff", "log_pageviews", "log_enroll"])
            if W2.post.nunique() == 2 and len(W2) > 20:
                r = smf.ols("acc ~ post + months_from_cutoff + log_pageviews + log_enroll + C(sector)", W2).fit(cov_type="HC3")
                lo, hi = r.conf_int().loc["post"]
                rep.append(f"\nRegression (OLS, HC3) acc ~ unexposed + months from cutoff + log page views + log enrollment + sector: "
                           f"unexposed {r.params['post']:+.3f} [{lo:+.3f}, {hi:+.3f}] p={r.pvalues['post']:.3f} (n={int(r.nobs)})\n")
            letters = "".join(R.letters)
            rep.append("Letters chosen (position-bias check; the correct letter is uniformly shuffled): " +
                       ", ".join(f"{c}={letters.count(c) / max(1, sum(letters.count(x) for x in 'ABCD')):.2f}" for c in "ABCD") + "\n")
            rep.append("Reading: positive control (famous) well above 0.25 and above blind shows the test can detect knowledge. If exposed > unexposed, reading the page "
                       "taught GPT-4o school-specific facts. If blind is well above 0.25, the options leak the answer.\n")
    (out / "report.md").write_text("\n".join(rep))
    print("\n".join(rep))
