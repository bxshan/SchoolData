# Wikipedia K-12 School Downloader Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `wiki_crawl/crawl_k12_schools.py` into a two-phase downloader that discovers US K-12 school candidates and tags every one with a `validation` status, so non-school leaks are labeled (not lost) and the clean dataset is produced by a reversible downstream filter.

**Architecture:** Phase 1 (DISCOVER) walks the Wikipedia category tree and streams raw candidates to `<out>.raw.csv`. Phase 2 (TAG) reads that file, resolves each page's Wikidata item, fetches P31/P576/P571, assigns one of five `validation` tags, and writes the final `<out>` CSV. No row is ever dropped at crawl time; cleaning is `validation == "school"` applied later.

**Tech Stack:** Python 3 (stdlib + `requests`), MediaWiki Action API, Wikidata `wbgetentities` API, `pytest` for tests.

## Global Constraints

- **Language/deps:** Python 3, standard library + `requests` only for the script itself. Tests may use `pytest`. No pandas/lxml. (Matches existing `wiki_crawl/` convention.)
- **File author header:** none required in `wiki_crawl/` (unlike `nces_crawl/`, which prefixes `# Author: Boxuan Shan + support from Claude Sonnet 4.5`). Do not add an author header here — match the existing `crawl_k12_schools.py` style (module docstring first).
- **API politeness:** keep the existing `User-Agent` string and the `api_get()` backoff (429/503/`maxlag`, `formatversion=2`, `maxlag=5`). Wikidata calls go to `https://www.wikidata.org/w/api.php`.
- **Batch size:** 50 titles/ids per API call (MediaWiki + Wikidata limit used by `enrich_schools.py`).
- **Non-destructive rule:** Phase 2 must never discard a candidate. Every Phase-1 row appears in the final output with exactly one `validation` tag. On any per-batch API failure, affected rows are tagged `unverified`, not dropped.
- **Backward compatibility:** the final CSV is a *superset* of the current 4 columns; `enrich_schools.py` reads only `title` and `source_category` from its input, so extra columns are safe.
- **Validation tag set (exactly five):** `school`, `unverified`, `defunct`, `out_of_scope`, `non_school`.
- **Output column order:** `title, url, pageid, source_category, instance_of, wikidata_qid, founded, dissolved, validation`.

---

## File Structure

- **Modify:** `wiki_crawl/crawl_k12_schools.py` — expand seeds; add Phase-2 tagging functions; restructure `main()` into Phase 1 (→ `<out>.raw.csv`) then Phase 2 (→ `<out>`); add CLI flags. Keep all pure logic in importable module-level functions.
- **Create:** `wiki_crawl/tests/test_crawl_k12_schools.py` — pytest unit tests for the pure functions and the orchestration (network monkeypatched), plus one opt-in live integration test.
- **Create:** `wiki_crawl/tests/__init__.py` — empty (makes the package importable).
- **Modify:** `wiki_crawl/README.md` *(if present; create a short note if not)* — document the `validation` column and the `validation == "school"` filter step before `enrich_schools.py`.

All Phase-2 network access goes through the existing `api_get(session, params, timeout, max_retries, base_url)` choke point so tests can monkeypatch one function.

---

## Reference signatures (already in the codebase — reuse, do not reinvent)

From `wiki_crawl/crawl_k12_schools.py` (current):
- `api_get(session, params, timeout, max_retries=8)` — **extend** to accept `base_url=None` (Wikidata reuse), mirroring `enrich_schools.py:api_get`.
- `iter_category_members(session, category, cmtype, delay, timeout)` — unchanged.
- `should_descend(subcat_title, include_defunct)` — unchanged (light pruning kept).
- `is_real_article(title)` — unchanged.
- `title_to_url(title)` — unchanged.
- `crawl(...)` — unchanged except it writes to the raw file (same writer interface).

From `wiki_crawl/enrich_schools.py` (pattern to mirror for Wikidata):
- `wbgetentities` with `props=claims` then `props=labels&languages=en`, batched 50.
- `_claim_value(claims, pid)` returns first mainsnak value; we generalize to **all** P31 values.
- Property IDs: **P31** instance-of, **P576** dissolved/abolished date, **P571** inception.

---

### Task 1: Test scaffold + expanded seeds + classifier constants

**Files:**
- Create: `wiki_crawl/tests/__init__.py`
- Create: `wiki_crawl/tests/test_crawl_k12_schools.py`
- Modify: `wiki_crawl/crawl_k12_schools.py` (SEED_CATEGORIES, new regex/constants)

**Interfaces:**
- Produces: module constants `SEED_CATEGORIES: list[str]`, `SCHOOL_RE: re.Pattern`, `HIGHER_ED_RE: re.Pattern`, `SCHOOL_DISTRICT_RE: re.Pattern`, `VALIDATION_TAGS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# wiki_crawl/tests/test_crawl_k12_schools.py
import re
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crawl_k12_schools as ck


def test_seed_categories_cover_all_k12_levels():
    joined = " | ".join(ck.SEED_CATEGORIES).lower()
    for needed in [
        "high schools in the united states",
        "middle schools in the united states",
        "elementary schools in the united states",
        "primary schools in the united states",
        "magnet schools in the united states",
        "boarding schools in the united states",
        "private schools in the united states",
    ]:
        assert needed in joined, f"missing seed: {needed}"


def test_school_regex_matches_school_types():
    for label in ["high school", "school", "private school", "academy",
                  "boarding school", "yeshiva", "school building",
                  "university-preparatory school", "montessori school"]:
        assert ck.SCHOOL_RE.search(label), f"should match: {label}"


def test_school_regex_rejects_clear_non_schools():
    assert not ck.SCHOOL_RE.search("human")
    assert not ck.SCHOOL_RE.search("film")


def test_non_school_re_catches_violent_events():
    # These P31 labels contain "school" (so SCHOOL_RE matches) but are events,
    # not schools. NON_SCHOOL_RE must flag them so classify never tags `school`.
    for label in ["school shooting", "school massacre", "school bombing"]:
        assert ck.SCHOOL_RE.search(label), f"SCHOOL_RE should match {label}"
        assert ck.NON_SCHOOL_RE.search(label), f"NON_SCHOOL_RE should catch {label}"
    # real schools must NOT be caught by the disqualifier
    for label in ["high school", "school building", "boarding school"]:
        assert not ck.NON_SCHOOL_RE.search(label)


def test_validation_tags_are_exactly_five():
    assert set(ck.VALIDATION_TAGS) == {
        "school", "unverified", "defunct", "out_of_scope", "non_school"
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -v`
Expected: FAIL with `AttributeError: module 'crawl_k12_schools' has no attribute 'SCHOOL_RE'` (and seed assertions).

- [ ] **Step 3: Write minimal implementation**

In `wiki_crawl/crawl_k12_schools.py`, replace the `SEED_CATEGORIES` list with the expanded set and add the classifier constants near the other module constants:

```python
SEED_CATEGORIES = [
    "Category:Schools in the United States",
    "Category:Schools in the United States by state or territory",
    "Category:High schools in the United States",
    "Category:Secondary schools in the United States",
    "Category:Middle schools in the United States",
    "Category:Junior high schools in the United States",
    "Category:Elementary schools in the United States",
    "Category:Primary schools in the United States",
    "Category:Private schools in the United States",
    "Category:Public schools in the United States",
    "Category:Charter schools in the United States",
    "Category:Magnet schools in the United States",
    "Category:Catholic schools in the United States",
    "Category:Boarding schools in the United States",
    "Category:Preparatory schools in the United States",
]

VALIDATION_TAGS = ("school", "unverified", "defunct", "out_of_scope", "non_school")

# A Wikidata P31 label is "school-ish" if it matches this and is not caught by
# the higher-ed / district guards below.
SCHOOL_RE = re.compile(
    r"school|academ|gymnasium|yeshiv|lyceum|montessori|seminar|"
    r"kindergarten|preparat|educational institution",
    re.I,
)

# Higher-ed / professional school labels to push to out_of_scope — but NEVER a
# K-12 "... preparatory school" (guarded by the negative lookahead on 'preparat').
HIGHER_ED_RE = re.compile(
    r"(?!.*preparat)("
    r"\bcollege\b|\buniversity\b|law school|medical school|graduate school|"
    r"business school|nursing school|art school|dental school|"
    r"veterinary school|divinity school|community college|junior college"
    r")",
    re.I,
)

SCHOOL_DISTRICT_RE = re.compile(r"school district", re.I)

# Disqualifier: a P31 label that contains "school" but is really a violent
# event/crime (real Wikidata P31 for school shootings is literally the label
# "school shooting", which would otherwise match SCHOOL_RE). Checked BEFORE the
# school branch so these never get tagged `school`.
NON_SCHOOL_RE = re.compile(
    r"shooting|massacre|bombing|attack|murder|killing|stabbing|"
    r"disaster|riot|hostage|kidnap|hoax",
    re.I,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/tests/__init__.py wiki_crawl/tests/test_crawl_k12_schools.py wiki_crawl/crawl_k12_schools.py
git commit -m "feat(wiki): expand K-12 seeds and add validation classifier constants"
```

---

### Task 2: `classify_validation()` — the core tagging logic (pure)

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py` (add function)
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py`

**Interfaces:**
- Produces: `classify_validation(qid: str, p31_labels: list[str], dissolved: bool) -> str`
  - `qid`: Wikidata QID string (`""` if none).
  - `p31_labels`: resolved English labels of all P31 values (may be empty).
  - `dissolved`: True if the item has a P576 date.
  - Returns one of `VALIDATION_TAGS`.

- [ ] **Step 1: Write the failing test**

```python
def test_classify_unverified_when_no_qid_or_no_p31():
    assert ck.classify_validation("", [], False) == "unverified"
    assert ck.classify_validation("Q123", [], False) == "unverified"


def test_classify_out_of_scope_for_district_and_higher_ed():
    assert ck.classify_validation("Q1", ["school district"], False) == "out_of_scope"
    assert ck.classify_validation("Q2", ["law school"], False) == "out_of_scope"
    assert ck.classify_validation("Q3", ["public university"], False) == "out_of_scope"
    assert ck.classify_validation("Q4", ["community college"], False) == "out_of_scope"


def test_classify_keeps_prep_school_despite_university_word():
    # "university-preparatory school" must stay a school, not out_of_scope
    assert ck.classify_validation("Q5", ["university-preparatory school"], False) == "school"


def test_classify_school_and_defunct():
    assert ck.classify_validation("Q6", ["high school"], False) == "school"
    assert ck.classify_validation("Q7", ["school building"], False) == "school"
    assert ck.classify_validation("Q8", ["high school"], True) == "defunct"


def test_classify_non_school_for_positive_non_school_p31():
    assert ck.classify_validation("Q9", ["human"], False) == "non_school"
    assert ck.classify_validation("Q10", ["massacre"], False) == "non_school"
    assert ck.classify_validation("Q11", ["film"], False) == "non_school"


def test_classify_school_shooting_is_non_school():
    # Real Wikidata P31 label for school-shooting events is literally
    # "school shooting" (contains "school"). It must NOT be tagged `school`.
    assert ck.classify_validation("Q473845", ["school shooting"], False) == "non_school"
    # Columbine-style multi-value P31: still non_school (no genuine school type)
    assert ck.classify_validation(
        "Q473845", ["school shooting", "mass shooting", "murder-suicide"], False
    ) == "non_school"


def test_classify_multivalue_prefers_school():
    # a page that is both a school and a tourist attraction is a school
    assert ck.classify_validation("Q12", ["tourist attraction", "high school"], False) == "school"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k classify -v`
Expected: FAIL with `AttributeError: ... has no attribute 'classify_validation'`.

- [ ] **Step 3: Write minimal implementation**

Add to `wiki_crawl/crawl_k12_schools.py`:

```python
def classify_validation(qid, p31_labels, dissolved):
    """Assign exactly one validation tag from P31 labels + dissolution flag.

    A label is a *genuine school type* if it matches SCHOOL_RE and is NOT a
    school district, a higher-ed institution, or a violent event/crime.

    Order:
      1. no QID or no resolvable P31 label          -> "unverified"
      2. any genuine school type:
           with a P576 dissolution date             -> "defunct"
           otherwise                                -> "school"
      3. any label is a school district / higher-ed -> "out_of_scope"
      4. otherwise (event / person / film / ...)    -> "non_school"

    A genuine school type wins over a co-asserted higher-ed label on mixed P31,
    favoring recall — consistent with the non-destructive design.
    """
    labels = [l.strip() for l in p31_labels if l and l.strip()]
    if not qid or not labels:
        return "unverified"

    school_labels = [
        l for l in labels
        if SCHOOL_RE.search(l)
        and not SCHOOL_DISTRICT_RE.search(l)
        and not HIGHER_ED_RE.search(l)
        and not NON_SCHOOL_RE.search(l)
    ]
    if school_labels:
        return "defunct" if dissolved else "school"

    if any(SCHOOL_DISTRICT_RE.search(l) or HIGHER_ED_RE.search(l) for l in labels):
        return "out_of_scope"

    return "non_school"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k classify -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): add classify_validation tagging logic"
```

---

### Task 3: `extract_claims()` — parse a Wikidata entity (pure)

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py`
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py`

**Interfaces:**
- Produces: `extract_claims(entity: dict) -> dict` returning
  `{"p31_qids": list[str], "dissolved": bool, "founded": str}` from one
  `wbgetentities` entity object (the value under `entities[qid]`).

- [ ] **Step 1: Write the failing test**

```python
def test_extract_claims_reads_p31_p576_p571():
    entity = {
        "claims": {
            "P31": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"id": "Q9826"}}}},
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"id": "Q41176"}}}},
            ],
            "P571": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"time": "+1923-00-00T00:00:00Z"}}}}
            ],
            "P576": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"time": "+1995-00-00T00:00:00Z"}}}}
            ],
        }
    }
    out = ck.extract_claims(entity)
    assert out["p31_qids"] == ["Q9826", "Q41176"]
    assert out["dissolved"] is True
    assert out["founded"] == "1923"


def test_extract_claims_handles_missing():
    assert ck.extract_claims({"claims": {}}) == {
        "p31_qids": [], "dissolved": False, "founded": ""
    }


def test_extract_claims_ignores_novalue_snaks():
    entity = {"claims": {"P576": [{"mainsnak": {"snaktype": "novalue"}}]}}
    assert ck.extract_claims(entity)["dissolved"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k extract_claims -v`
Expected: FAIL — `extract_claims` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
def _p31_qids(claims):
    out = []
    for c in claims.get("P31", []):
        snak = c.get("mainsnak", {})
        if snak.get("snaktype") != "value":
            continue
        qid = snak.get("datavalue", {}).get("value", {}).get("id")
        if qid:
            out.append(qid)
    return out


def _has_value(claims, pid):
    for c in claims.get(pid, []):
        if c.get("mainsnak", {}).get("snaktype") == "value":
            return True
    return False


def _first_year(claims, pid):
    for c in claims.get(pid, []):
        snak = c.get("mainsnak", {})
        if snak.get("snaktype") != "value":
            continue
        t = snak.get("datavalue", {}).get("value", {}).get("time", "")
        m = re.search(r"([+-]\d{4})", t)
        if m:
            return m.group(1).lstrip("+")
    return ""


def extract_claims(entity):
    """Extract {p31_qids, dissolved, founded} from one wbgetentities entity."""
    claims = entity.get("claims", {})
    return {
        "p31_qids": _p31_qids(claims),
        "dissolved": _has_value(claims, "P576"),
        "founded": _first_year(claims, "P571"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k extract_claims -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): add Wikidata claim extraction (P31/P576/P571)"
```

---

### Task 4: Extend `api_get` for Wikidata + `resolve_qids()` (pageid → QID)

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py`
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py`

**Interfaces:**
- Modifies: `api_get(session, params, timeout=60, max_retries=8, base_url=None)` — add `base_url` param (defaults to `API_URL`).
- Produces: `resolve_qids(session, pageids: list[int], delay: float, timeout: float) -> dict[int, str]` — maps pageid → Wikidata QID (`""` when none), via `prop=pageprops&ppprop=wikibase_item`, batched 50.

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_qids_maps_pageid_to_qid(monkeypatch):
    captured = {}
    def fake_api_get(session, params, timeout, max_retries=8, base_url=None):
        captured["base_url"] = base_url
        return {"query": {"pages": [
            {"pageid": 111, "title": "A High School",
             "pageprops": {"wikibase_item": "Q111"}},
            {"pageid": 222, "title": "B School"},  # no wikibase_item
        ]}}
    monkeypatch.setattr(ck, "api_get", fake_api_get)
    out = ck.resolve_qids(session=None, pageids=[111, 222], delay=0, timeout=1)
    assert out == {111: "Q111", 222: ""}
    assert captured["base_url"] in (None, ck.API_URL)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k resolve_qids -v`
Expected: FAIL — `resolve_qids` not defined.

- [ ] **Step 3: Write minimal implementation**

First change the `api_get` signature line in `crawl_k12_schools.py` from:

```python
def api_get(session, params, timeout, max_retries=8):
```

to:

```python
def api_get(session, params, timeout=60, max_retries=8, base_url=None):
```

and inside it change the request line from `session.get(API_URL, ...)` to:

```python
            resp = session.get(base_url or API_URL, params=params, timeout=timeout)
```

Then add:

```python
WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def resolve_qids(session, pageids, delay, timeout):
    """Map pageid -> Wikidata QID ('' if none) via pageprops, batched 50.

    Non-destructive: if a batch errors (after api_get's retries), it is skipped
    and those pageids stay unresolved, so tag_candidates tags them `unverified`
    rather than aborting the run.

    Note: lookups are by pageid (no redirects=1). In the rare case a category
    member is itself a redirect page, it usually has no wikibase_item and lands
    in `unverified` (kept, not lost). enrich_schools.py resolves redirects
    downstream, so this is an accepted, non-destructive recall trade-off.
    """
    out = {}
    for i in range(0, len(pageids), 50):
        chunk = pageids[i:i + 50]
        try:
            data = api_get(session, {
                "action": "query",
                "pageids": "|".join(str(p) for p in chunk),
                "prop": "pageprops",
                "ppprop": "wikibase_item",
            }, timeout)
        except (RuntimeError, requests.RequestException) as exc:
            sys.stderr.write(f"  ! resolve_qids batch failed ({exc}); "
                             f"{len(chunk)} pages -> unverified\n")
            continue
        for page in data.get("query", {}).get("pages", []):
            pid = page.get("pageid")
            if pid is None:
                continue
            out[pid] = page.get("pageprops", {}).get("wikibase_item", "")
        if delay:
            time.sleep(delay)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k resolve_qids -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite to confirm the `api_get` signature change broke nothing**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -v`
Expected: PASS (all prior tests still green).

- [ ] **Step 6: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): add Wikidata base_url support and resolve_qids"
```

---

### Task 5: `fetch_claims()` + `resolve_labels()` (Wikidata batch fetch)

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py`
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py`

**Interfaces:**
- Produces: `fetch_claims(session, qids: list[str], delay, timeout) -> dict[str, dict]` — qid → `extract_claims` result, via `wbgetentities props=claims`, batched 50, `base_url=WIKIDATA_API`.
- Produces: `resolve_labels(session, qids: list[str], delay, timeout) -> dict[str, str]` — qid → English label, via `wbgetentities props=labels languages=en`, batched 50.

- [ ] **Step 1: Write the failing test**

```python
def test_fetch_claims_batches_and_extracts(monkeypatch):
    def fake_api_get(session, params, timeout, max_retries=8, base_url=None):
        assert base_url == ck.WIKIDATA_API
        assert params["action"] == "wbgetentities"
        return {"entities": {
            "Q111": {"claims": {"P31": [
                {"mainsnak": {"snaktype": "value",
                              "datavalue": {"value": {"id": "Q9826"}}}}]}},
        }}
    monkeypatch.setattr(ck, "api_get", fake_api_get)
    out = ck.fetch_claims(session=None, qids=["Q111"], delay=0, timeout=1)
    assert out["Q111"]["p31_qids"] == ["Q9826"]


def test_resolve_labels_returns_en_label(monkeypatch):
    def fake_api_get(session, params, timeout, max_retries=8, base_url=None):
        assert params["props"] == "labels"
        return {"entities": {
            "Q9826": {"labels": {"en": {"value": "high school"}}},
            "Q1": {"labels": {}},
        }}
    monkeypatch.setattr(ck, "api_get", fake_api_get)
    out = ck.resolve_labels(session=None, qids=["Q9826", "Q1"], delay=0, timeout=1)
    assert out == {"Q9826": "high school", "Q1": ""}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k "fetch_claims or resolve_labels" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Write minimal implementation**

```python
def fetch_claims(session, qids, delay, timeout):
    """qid -> {p31_qids, dissolved, founded} via wbgetentities (claims).

    Non-destructive: a failed batch is skipped; those qids get no claims, so
    tag_candidates tags the affected rows `unverified`.
    """
    out = {}
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        try:
            data = api_get(session, {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "claims",
            }, timeout, base_url=WIKIDATA_API)
        except (RuntimeError, requests.RequestException) as exc:
            sys.stderr.write(f"  ! fetch_claims batch failed ({exc}); "
                             f"{len(chunk)} qids -> unverified\n")
            continue
        for qid, ent in data.get("entities", {}).items():
            out[qid] = extract_claims(ent)
        if delay:
            time.sleep(delay)
    return out


def resolve_labels(session, qids, delay, timeout):
    """qid -> English label ('' if none) via wbgetentities (labels).

    Non-destructive: a failed batch is skipped; unresolved labels become '',
    which classify_validation treats as no usable P31 (-> `unverified`).
    """
    out = {}
    uniq = list(dict.fromkeys(qids))
    for i in range(0, len(uniq), 50):
        chunk = uniq[i:i + 50]
        try:
            data = api_get(session, {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "labels",
                "languages": "en",
            }, timeout, base_url=WIKIDATA_API)
        except (RuntimeError, requests.RequestException) as exc:
            sys.stderr.write(f"  ! resolve_labels batch failed ({exc}); "
                             f"{len(chunk)} qids unlabeled\n")
            continue
        for qid, ent in data.get("entities", {}).items():
            out[qid] = ent.get("labels", {}).get("en", {}).get("value", "")
        if delay:
            time.sleep(delay)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k "fetch_claims or resolve_labels" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): add Wikidata fetch_claims and resolve_labels"
```

---

### Task 6: `tag_candidates()` — orchestrate Phase 2 (drop nothing)

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py`
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py`

**Interfaces:**
- Produces: `tag_candidates(session, candidates: list[dict], delay, timeout) -> list[dict]`
  - Input rows have at least `title, url, pageid, source_category`.
  - Returns the **same rows**, each augmented with `instance_of, wikidata_qid, founded, dissolved, validation`. Length is unchanged (non-destructive). `instance_of` is the `|`-joined school/first P31 label(s) for transparency; `dissolved` is the year string (`""` if none).

- [ ] **Step 1: Write the failing test**

```python
def test_tag_candidates_is_non_destructive_and_tags(monkeypatch):
    candidates = [
        {"title": "Real High School", "url": "u1", "pageid": 1, "source_category": "Schools in X"},
        {"title": "Some Shooting",    "url": "u2", "pageid": 2, "source_category": "Copycat crimes"},
        {"title": "No Wikidata",      "url": "u3", "pageid": 3, "source_category": "Schools in X"},
    ]
    monkeypatch.setattr(ck, "resolve_qids",
        lambda s, pids, delay, timeout: {1: "Q1", 2: "Q2", 3: ""})
    monkeypatch.setattr(ck, "fetch_claims",
        lambda s, qids, delay, timeout: {
            "Q1": {"p31_qids": ["Q9826"], "dissolved": False, "founded": "1950"},
            "Q2": {"p31_qids": ["Qmass"], "dissolved": False, "founded": ""},
        })
    monkeypatch.setattr(ck, "resolve_labels",
        lambda s, qids, delay, timeout: {"Q9826": "high school", "Qmass": "massacre"})

    out = ck.tag_candidates(session=None, candidates=candidates, delay=0, timeout=1)
    assert len(out) == 3  # nothing dropped
    by_id = {r["pageid"]: r for r in out}
    assert by_id[1]["validation"] == "school"
    assert by_id[1]["instance_of"] == "high school"
    assert by_id[1]["wikidata_qid"] == "Q1"
    assert by_id[1]["founded"] == "1950"
    assert by_id[2]["validation"] == "non_school"
    assert by_id[3]["validation"] == "unverified"
    assert by_id[3]["wikidata_qid"] == ""


def test_tag_candidates_survives_api_failure(monkeypatch):
    # If the underlying api_get raises (exhausted retries / hard error), the
    # batch functions must catch it and every row is kept as `unverified`.
    candidates = [
        {"title": "X", "url": "u", "pageid": 1, "source_category": "S"},
        {"title": "Y", "url": "u", "pageid": 2, "source_category": "S"},
    ]
    def boom(*a, **k):
        raise RuntimeError("API error: simulated")
    monkeypatch.setattr(ck, "api_get", boom)  # real batch fns must swallow it
    out = ck.tag_candidates(session=None, candidates=candidates, delay=0, timeout=1)
    assert len(out) == 2  # nothing lost
    assert all(r["validation"] == "unverified" for r in out)
    assert all(r["wikidata_qid"] == "" for r in out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k tag_candidates -v`
Expected: FAIL — `tag_candidates` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
def tag_candidates(session, candidates, delay, timeout):
    """Augment every candidate with Wikidata-derived tags. Never drops a row."""
    pageids = [int(c["pageid"]) for c in candidates]
    pid_to_qid = resolve_qids(session, pageids, delay, timeout)

    qids = [q for q in pid_to_qid.values() if q]
    claims = fetch_claims(session, qids, delay, timeout)

    need_labels = []
    for cl in claims.values():
        need_labels.extend(cl["p31_qids"])
    labels = resolve_labels(session, need_labels, delay, timeout)

    for c in candidates:
        qid = pid_to_qid.get(int(c["pageid"]), "")
        cl = claims.get(qid, {"p31_qids": [], "dissolved": False, "founded": ""})
        p31_labels = [labels.get(q, "") for q in cl["p31_qids"]]
        c["wikidata_qid"] = qid
        c["instance_of"] = "|".join(l for l in p31_labels if l)
        c["founded"] = cl["founded"]
        c["dissolved"] = _first_year_from_flag(cl)
        c["validation"] = classify_validation(qid, p31_labels, cl["dissolved"])
    return candidates


def _first_year_from_flag(cl):
    # 'dissolved' in claims is a bool; we only persist a year when known.
    # extract_claims tracks presence, not the year, so keep '' unless a future
    # change captures it. Persist 'dissolved'/'' marker as empty string for now.
    return ""
```

> Note: `extract_claims` currently records P576 *presence* as a bool, which is all
> `classify_validation` needs. The `dissolved` output column is therefore `""`
> unless Task 7's optional enhancement captures the year. Keeping the column makes
> the schema stable; the boolean drives the tag.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k tag_candidates -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): add non-destructive tag_candidates orchestration"
```

---

### Task 7: Capture the P576 year so `dissolved` column is real

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py`
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py`

**Interfaces:**
- Modifies: `extract_claims` to also return `"dissolved_year": str` (year from P576, `""` if none). `tag_candidates` writes that into the `dissolved` column. `classify_validation` still keys off truthiness of the year/flag.

- [ ] **Step 1: Write the failing test**

```python
def test_extract_claims_returns_dissolved_year():
    entity = {"claims": {"P576": [
        {"mainsnak": {"snaktype": "value",
                      "datavalue": {"value": {"time": "+1995-00-00T00:00:00Z"}}}}]}}
    out = ck.extract_claims(entity)
    assert out["dissolved"] is True
    assert out["dissolved_year"] == "1995"


def test_tag_writes_dissolved_year(monkeypatch):
    candidates = [{"title": "Old School", "url": "u", "pageid": 1, "source_category": "X"}]
    monkeypatch.setattr(ck, "resolve_qids", lambda s, p, d, t: {1: "Q1"})
    monkeypatch.setattr(ck, "fetch_claims", lambda s, q, d, t: {
        "Q1": {"p31_qids": ["Q9826"], "dissolved": True,
               "dissolved_year": "1980", "founded": "1900"}})
    monkeypatch.setattr(ck, "resolve_labels", lambda s, q, d, t: {"Q9826": "high school"})
    out = ck.tag_candidates(None, candidates, 0, 1)
    assert out[0]["validation"] == "defunct"
    assert out[0]["dissolved"] == "1980"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k "dissolved" -v`
Expected: FAIL — `dissolved_year` missing.

- [ ] **Step 3: Write minimal implementation**

In `extract_claims`, add the year:

```python
def extract_claims(entity):
    claims = entity.get("claims", {})
    year = _first_year(claims, "P576")
    return {
        "p31_qids": _p31_qids(claims),
        "dissolved": bool(year) or _has_value(claims, "P576"),
        "dissolved_year": year,
        "founded": _first_year(claims, "P571"),
    }
```

Replace the `tag_candidates` `dissolved` line and delete `_first_year_from_flag`:

```python
        c["dissolved"] = cl.get("dissolved_year", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -v`
Expected: PASS (full suite, including the updated `extract_claims` tests — update the Task 3 `test_extract_claims_handles_missing` expectation to include `"dissolved_year": ""`).

> When this step changes `extract_claims`'s return dict, update the earlier
> `test_extract_claims_handles_missing` assertion to:
> `{"p31_qids": [], "dissolved": False, "dissolved_year": "", "founded": ""}`.

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): capture P576 dissolution year for the dissolved column"
```

---

### Task 8: Output writer with `--write-status` filter (default writes all)

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py`
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py`

**Interfaces:**
- Produces: `write_tagged_csv(path: str, rows: list[dict], statuses: set[str] | None) -> int`
  - Writes the 9-column schema header + rows whose `validation` is in `statuses`
    (or all rows when `statuses is None`). Returns the number of rows written.

- [ ] **Step 1: Write the failing test**

```python
import csv

def test_write_tagged_csv_all_and_filtered(tmp_path):
    rows = [
        {"title": "A", "url": "ua", "pageid": 1, "source_category": "X",
         "instance_of": "high school", "wikidata_qid": "Q1", "founded": "",
         "dissolved": "", "validation": "school"},
        {"title": "B", "url": "ub", "pageid": 2, "source_category": "X",
         "instance_of": "human", "wikidata_qid": "Q2", "founded": "",
         "dissolved": "", "validation": "non_school"},
    ]
    p_all = tmp_path / "all.csv"
    n_all = ck.write_tagged_csv(str(p_all), rows, None)
    assert n_all == 2
    header = next(csv.reader(open(p_all)))
    assert header == ["title", "url", "pageid", "source_category", "instance_of",
                      "wikidata_qid", "founded", "dissolved", "validation"]

    p_sch = tmp_path / "schools.csv"
    n_sch = ck.write_tagged_csv(str(p_sch), rows, {"school"})
    assert n_sch == 1
    data = list(csv.DictReader(open(p_sch)))
    assert [r["validation"] for r in data] == ["school"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k write_tagged_csv -v`
Expected: FAIL — `write_tagged_csv` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
TAGGED_FIELDS = ["title", "url", "pageid", "source_category", "instance_of",
                 "wikidata_qid", "founded", "dissolved", "validation"]


def write_tagged_csv(path, rows, statuses):
    """Write rows (optionally filtered to `statuses`) in the 9-column schema."""
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TAGGED_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            if statuses is not None and r.get("validation") not in statuses:
                continue
            w.writerow(r)
            n += 1
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k write_tagged_csv -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): add tagged CSV writer with optional status filter"
```

---

### Task 9: Wire `main()` — Phase 1 → raw file → Phase 2 → final CSV + CLI flags

**Files:**
- Modify: `wiki_crawl/crawl_k12_schools.py` (`crawl` raw output, `main`, argparse)
- Test: `wiki_crawl/tests/test_crawl_k12_schools.py` (CLI arg parsing + raw-read path)

**Interfaces:**
- Produces: `read_candidates(path: str) -> list[dict]` — read a raw CSV (`title,url,pageid,source_category`) back into candidate dicts (pageid as int).
- Modifies: `main()` to: run Phase 1 to `<out>.raw.csv` (unless the raw file exists and `--resume`), then unless `--no-validate`, read it, `tag_candidates`, and `write_tagged_csv(<out>, rows, statuses)` where `statuses` comes from `--write-status` (default `None` = all). With `--no-validate`, copy raw → `<out>` unchanged.
- Adds CLI: `--no-validate` (store_true), `--write-status` (comma list, default `""` → None).

- [ ] **Step 1: Write the failing test**

```python
def test_read_candidates_roundtrip(tmp_path):
    p = tmp_path / "raw.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["title", "url", "pageid", "source_category"])
        w.writeheader()
        w.writerow({"title": "A", "url": "ua", "pageid": "5", "source_category": "X"})
    rows = ck.read_candidates(str(p))
    assert rows == [{"title": "A", "url": "ua", "pageid": 5, "source_category": "X"}]


def test_parse_write_status():
    assert ck.parse_write_status("") is None
    assert ck.parse_write_status("school,unverified") == {"school", "unverified"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -k "read_candidates or parse_write_status" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Write minimal implementation**

Add helpers:

```python
def read_candidates(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "title": r["title"],
                "url": r["url"],
                "pageid": int(r["pageid"]),
                "source_category": r["source_category"],
            })
    return rows


def parse_write_status(s):
    s = (s or "").strip()
    if not s:
        return None
    return {tok.strip() for tok in s.split(",") if tok.strip()}
```

Then update `main()`. Change the raw output path and add the Phase-2 stage. The
Phase-1 `crawl(...)` call stays the same but writes to `raw_path = args.out +
".raw.csv"`. After it returns, run Phase 2:

```python
    # --- new CLI flags (add to argparse) ---
    parser.add_argument("--no-validate", action="store_true",
                        help="skip Wikidata tagging; emit raw candidates as --out")
    parser.add_argument("--write-status", default="",
                        help="comma list of validation tags to write "
                             "(default: all). e.g. school,unverified")
```

Replace the body that opens `args.out` for the crawl with a version that writes the
raw file, then tags:

```python
    raw_path = args.out + ".raw.csv"
    fields = ["title", "url", "pageid", "source_category"]
    extra_seen = set()
    append = resuming and os.path.exists(raw_path)
    if append:
        with open(raw_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    extra_seen.add(int(row["pageid"]))
                except (ValueError, KeyError):
                    pass

    with open(raw_path, "a" if append else "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if not append:
            writer.writeheader()
        proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
        total = crawl(
            seeds, args.max_depth, args.delay, args.timeout,
            args.include_defunct, writer, fh.flush, proxies,
            checkpoint_path=checkpoint_path, resume=args.resume,
            extra_seen=extra_seen,
        )
    sys.stderr.write(f"\nPhase 1 done. {total} raw candidates -> {raw_path}\n")

    if args.no_validate:
        os.replace(raw_path, args.out)
        sys.stderr.write(f"--no-validate: raw candidates -> {args.out}\n")
        return

    # --- Phase 2: tag every candidate via Wikidata ---
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})
    candidates = read_candidates(raw_path)
    sys.stderr.write(f"Phase 2: tagging {len(candidates)} candidates via Wikidata...\n")
    tagged = tag_candidates(session, candidates, args.delay, args.timeout)
    statuses = parse_write_status(args.write_status)
    n = write_tagged_csv(args.out, tagged, statuses)

    from collections import Counter
    dist = Counter(r["validation"] for r in tagged)
    sys.stderr.write(
        f"\nPhase 2 done. wrote {n}/{len(tagged)} rows -> {args.out}\n"
        f"  validation distribution: {dict(dist)}\n"
    )
```

(Remove the old single-stage `with open(args.out, ...)` crawl block this replaces.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd wiki_crawl && python -m pytest tests/test_crawl_k12_schools.py -v`
Expected: PASS (full unit suite).

- [ ] **Step 5: Smoke-check the CLI wiring compiles and `--help` lists new flags**

Run: `cd wiki_crawl && python crawl_k12_schools.py --help`
Expected: usage text includes `--no-validate` and `--write-status`.

- [ ] **Step 6: Commit**

```bash
git add wiki_crawl/crawl_k12_schools.py wiki_crawl/tests/test_crawl_k12_schools.py
git commit -m "feat(wiki): two-phase main (crawl -> raw -> Wikidata tag -> CSV)"
```

---

### Task 10: Opt-in live integration test + README note + real run

**Files:**
- Modify: `wiki_crawl/tests/test_crawl_k12_schools.py` (one marked live test)
- Modify/Create: `wiki_crawl/README.md` (document `validation` + filter step)

**Interfaces:**
- Consumes: the full pipeline end-to-end against the live API on a tiny seed.

- [ ] **Step 1: Add an opt-in live test (skipped by default)**

```python
import pytest

@pytest.mark.integration
def test_live_small_seed_tags_known_school(monkeypatch):
    """Hits the live API on a tiny seed. Run with: pytest -m integration"""
    import requests
    session = requests.Session()
    session.headers.update({"User-Agent": ck.USER_AGENT})
    # One small, stable category with a known school page.
    members = list(ck.iter_category_members(
        session, "Category:High schools in Vermont", "page", 0.2, 30))
    assert members, "expected some pages in the seed category"
    cands = [{"title": m["title"], "url": ck.title_to_url(m["title"]),
              "pageid": m["pageid"], "source_category": "High schools in Vermont"}
             for m in members[:15]]
    tagged = ck.tag_candidates(session, cands, 0.2, 30)
    assert len(tagged) == len(cands)                 # non-destructive
    assert all(r["validation"] in ck.VALIDATION_TAGS for r in tagged)
    assert any(r["validation"] == "school" for r in tagged)
```

Add a `pytest.ini` (or `pyproject` marker) note so `-m integration` is recognized:

```ini
# wiki_crawl/pytest.ini
[pytest]
markers =
    integration: live-network tests (run explicitly with -m integration)
```

- [ ] **Step 2: Run the default suite (integration skipped) then the live test**

Run: `cd wiki_crawl && python -m pytest tests/ -v -m "not integration"`
Expected: PASS, integration test deselected.

Run: `cd wiki_crawl && python -m pytest tests/ -v -m integration`
Expected: PASS (requires network; tags a Vermont high school as `school`).

- [ ] **Step 3: Document the `validation` column + filter in README**

Add to `wiki_crawl/README.md` (create if missing):

```markdown
## Wikipedia crawler output

`crawl_k12_schools.py` writes `schools.csv` with a `validation` column tagging every
row: `school`, `unverified`, `defunct`, `out_of_scope`, or `non_school`. Nothing is
dropped at crawl time — leaks are labeled, not removed.

Produce the clean dataset, then enrich. Filter on the `validation` column with a
**CSV-aware** tool — never `awk -F,`, because school titles/categories contain
commas (e.g. `"... High School (Cedar Rapids, Iowa)"`) and a naive comma split
would mis-read the column and silently drop real schools.

Easiest (let the crawler emit the clean file directly — CSV-safe):

    python crawl_k12_schools.py --out schools.csv                       # all rows, tagged
    python crawl_k12_schools.py --out schools_clean.csv --write-status school
    python enrich_schools.py --in schools_clean.csv --out schools_enriched.csv

Or filter an existing `schools.csv` with a CSV-aware one-liner:

    python -c "import csv,sys; r=csv.DictReader(open('schools.csv')); \
    w=csv.DictWriter(sys.stdout,fieldnames=r.fieldnames); w.writeheader(); \
    [w.writerow(x) for x in r if x['validation']=='school']" > schools_clean.csv

Keep `unverified` rows too while reviewing: `--write-status school,unverified`.
```

- [ ] **Step 4: Real run + audit (verification)**

Run a real crawl (small depth first to sanity check, then full):

```bash
cd wiki_crawl
python crawl_k12_schools.py --out schools.csv --max-depth 2 --delay 0.3 2>&1 | tail -20
```

Then audit the result — confirm `school`-tagged rows are clean and known leaks are
present-but-tagged:

```bash
python - <<'PY'
import csv, collections, re
rows = list(csv.DictReader(open("schools.csv")))
dist = collections.Counter(r["validation"] for r in rows)
print("validation distribution:", dict(dist))

sch = [r for r in rows if r["validation"] == "school"]
bad = [r for r in sch if r["instance_of"] and not any(
    k in r["instance_of"].lower() for k in
    ("school","academ","gymnasium","yeshiv","montessori","prep","institution"))]
print(f"school-tagged with suspicious instance_of: {len(bad)} (expect ~0)")
for r in bad[:10]:
    print("  ", r["title"], "|", r["instance_of"])

# HARD CHECK: no violent-event instance_of may carry the `school` tag (the
# core leak this rewrite exists to prevent).
EVENT = re.compile(r"shooting|massacre|bombing|attack|murder|killing", re.I)
leaked = [r for r in sch if EVENT.search(r["instance_of"])]
assert not leaked, f"LEAK: events tagged school: {[r['title'] for r in leaked]}"

# Leaks must be present-but-labeled, not lost: if any event pages were crawled,
# they should appear tagged non_school.
events = [r for r in rows if EVENT.search(r["instance_of"])]
print(f"event-type pages: {len(events)} (all tagged "
      f"{set(r['validation'] for r in events) or 'n/a'})")

# Level coverage sanity (non-high levels present among school-tagged rows).
levels = collections.Counter()
for r in sch:
    t = (r["title"] + " " + r["instance_of"]).lower()
    if "elementary" in t or "primary school" in t: levels["elementary"] += 1
    elif "middle school" in t or "junior high" in t: levels["middle"] += 1
    elif "high school" in t or "secondary" in t:     levels["high"] += 1
print("school-tagged level mix:", dict(levels))
PY
```

Expected: distribution prints all five tags; `school`-tagged suspicious count ≈ 0;
the event-leak assertion passes (no events tagged `school`); event pages, if any,
are tagged `non_school`.

- [ ] **Step 5: Commit**

```bash
git add wiki_crawl/tests/test_crawl_k12_schools.py wiki_crawl/pytest.ini wiki_crawl/README.md
git commit -m "test(wiki): add opt-in live integration test; document validation column"
```

---

## Self-Review

**Spec coverage:**
- Two-phase architecture → Tasks 7/9 (Phase 1 raw) + Tasks 4–6, 9 (Phase 2). ✓
- Expanded K-12 seeds → Task 1. ✓
- Light, recall-safe Phase-1 pruning (no aggressive new blocks) → `should_descend`/`is_real_article` left unchanged (stated in File Structure + Reference signatures). ✓
- Wikidata P31/P576/P571 fetch → Tasks 3, 5, 7. ✓
- Five-tag classifier, priority order, prep-school guard, school-building kept, **violent-event guard (`NON_SCHOOL_RE`) so `"school shooting"` P31 → `non_school`** → Tasks 1, 2. ✓
- Non-destructive (never drop) → Tasks 6, 8 + Global Constraints + integration test + `test_tag_candidates_survives_api_failure`. ✓
- Output schema (9 cols) → Tasks 8/9. ✓
- CLI `--no-validate`, `--write-status`, existing flags kept → Task 9. ✓
- Reversible downstream filter to clean set → Task 10 README + audit. ✓
- Error handling tags failures `unverified` (per-batch try/except in `resolve_qids`/`fetch_claims`/`resolve_labels`, verified by `test_tag_candidates_survives_api_failure`), reuse backoff/checkpoint → Tasks 4, 5, 6, 9. ✓
- Verification plan → Task 10 audit. ✓
- `enrich_schools.py` unchanged / backward compatible → File Structure + Global Constraints. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The
`_first_year_from_flag` stub introduced in Task 6 is explicitly removed in Task 7
(noted in both tasks).

**Type consistency:** `classify_validation(qid, p31_labels, dissolved)`,
`extract_claims(entity)->{p31_qids,dissolved,dissolved_year,founded}`,
`resolve_qids(...)->{pageid:qid}`, `fetch_claims(...)->{qid:claims}`,
`resolve_labels(...)->{qid:label}`, `tag_candidates(...)->list[dict]`,
`write_tagged_csv(path,rows,statuses)->int`, `read_candidates(path)->list[dict]`,
`parse_write_status(s)->set|None` — names/types consistent across tasks. `api_get`
gains `base_url` in Task 4 before any Wikidata caller (Task 5) uses it. ✓
