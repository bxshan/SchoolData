#!/usr/bin/env python3
"""Crawl Wikipedia for all US K-12 school articles (public + private) and save
their titles and links.

Approach: instead of scraping HTML, we walk Wikipedia's category tree via the
MediaWiki API (https://en.wikipedia.org/w/api.php). Starting from broad
"Schools in the United States by state" plus level-specific and private/Catholic
seed categories, we recursively descend into subcategories and collect all
article pages (namespace 0). Higher-education and clearly off-topic subcategory
branches (universities, alumni, sports, buildings, "established in YEAR", ...)
are pruned so we stay on K-12 schools. Results are de-duplicated by pageid and
streamed to a CSV as they are found.

Usage:
    python crawl_k12_schools.py                       # -> k12_schools.csv
    python crawl_k12_schools.py --max-depth 5 --delay 0.2 --out schools.csv
    python crawl_k12_schools.py --include-defunct
    python crawl_k12_schools.py --proxy http://127.0.0.1:7890   # via local proxy

Only dependency beyond the standard library is `requests`:
    pip install requests
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import deque

import requests

API_URL = "https://en.wikipedia.org/w/api.php"

# Be a polite API citizen: identify the bot per Wikimedia's User-Agent policy.
USER_AGENT = (
    "K12SchoolCrawler/1.0 (https://example.org; contact: boxuan.shan@gmail.com) "
    "python-requests"
)

# Seed categories. The broad "Schools ... by state" root gives the best recall
# (many K-12 schools are filed only under generic "Schools in <place>"). The
# level-specific and private/Catholic roots are kept as a safety net.
SEED_CATEGORIES = [
    "Category:Schools in the United States",                       # master root
    "Category:Schools in the United States by state or territory",  # 69 states/territories
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

# Optional: also include closed/historical schools.
DEFUNCT_SEEDS = [
    "Category:Defunct schools in the United States",
]

# Article-title prefixes that are clearly not individual school articles.
TITLE_PREFIX_BLOCKLIST = (
    "List of ",
    "Lists of ",
    "Index of ",
    "Outline of ",
    "Timeline of ",
)

# Substrings (case-insensitive) marking a SUBCATEGORY branch we should NOT
# descend into: higher education, people, sports, buildings, by-year buckets,
# meta/navigation, etc. Pruning these keeps the crawl on K-12 schools and stops
# it from drifting into unrelated parts of the category graph.
CATEGORY_NAME_BLOCKLIST = (
    "universit",            # universities, university-...
    "community college",
    "junior college",
    "technical college",
    "law school",
    "medical school",
    "nursing school",
    "business school",
    "graduate school",
    "art school",
    "divinity",
    "seminar",              # seminaries
    "alumni",
    "faculty",
    "people educated",
    "people associated",
    "educators",
    "teachers",
    "headmasters",
    "heads of",
    "principals",
    "school shootings",
    "shootings",
    "attacks on",
    "school fires",
    "school board",
    "lists of",
    "national register",
    "historic places",
    "sport",
    "athletic",
    "football",
    "basketball",
    "baseball",
    "mascot",
    "stadium",
    "gymnasium",
    "yearbook",
    "student newspaper",
    "school buildings",
    "buildings and structures",
    "campuses",
    "architecture",
    "establishments in",
    "disestablishments in",
    "introductions",
    "in fiction",
    "fictional",
    "popular culture",
    "film",
    "radio station",
    "television station",
    "novel",
    "song",
    "video game",
    "discograph",
    "template",
    "stubs",
    "wikipedia",
    "wikiproject",
    "tracking categories",
)


# Only descend into branches that look like schools/academies. This keeps the
# place/level groupings ("Schools in X", "High schools in X", "Segregation
# academies in X", "Yeshivas in X", ...) while pruning eponymous institution
# categories (e.g. "Stanford University", "California Institute of Technology")
# whose sub-pages are not K-12 schools.
_PERMIT_RE = re.compile(r"school|academ|yeshiv")

# Blocklist matched at a LEADING word boundary (so "film" still catches "films"
# but "art school" no longer fires on "heart schools"). Trailing is open on
# purpose to catch plurals/inflections.
_BLOCK_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in CATEGORY_NAME_BLOCKLIST) + r")"
)


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
    """Extract {p31_qids, dissolved, dissolved_year, founded} from one wbgetentities entity."""
    claims = entity.get("claims", {})
    year = _first_year(claims, "P576")
    return {
        "p31_qids": _p31_qids(claims),
        "dissolved": bool(year) or _has_value(claims, "P576"),
        "dissolved_year": year,
        "founded": _first_year(claims, "P571"),
    }


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


def should_descend(subcat_title, include_defunct):
    """Decide whether to recurse into a subcategory by its name."""
    name = subcat_title[len("Category:"):].lower()
    if not _PERMIT_RE.search(name):
        return False
    # Higher-ed "college/colleges" — but keep K-12 "college preparatory" cats.
    if "college" in name and "prep" not in name:
        return False
    if not include_defunct and re.search(r"\bdefunct", name):
        return False
    return not _BLOCK_RE.search(name)


def api_get(session, params, timeout=60, max_retries=8, base_url=None):
    """GET the MediaWiki API with retry + backoff.

    Handles rate limiting (429) and server overload (503) specially: respects
    the `Retry-After` header when present, otherwise backs off exponentially.
    `maxlag` lets the server shed load gracefully under replication lag.
    """
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    backoff = 1.0
    for attempt in range(max_retries):
        try:
            resp = session.get(base_url or API_URL, params=params, timeout=timeout)
            if resp.status_code in (429, 503):
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after and retry_after.isdigit()) else backoff
                sys.stderr.write(
                    f"  ! {resp.status_code} rate-limited; waiting {wait:.0f}s\n"
                )
                time.sleep(wait)
                backoff = min(backoff * 2, 60)
                continue
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                # maxlag returns an 'error' with code 'maxlag' — back off and retry.
                if data["error"].get("code") == "maxlag":
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                raise RuntimeError(f"API error: {data['error']}")
            return data
        except (requests.RequestException, ValueError) as exc:
            if attempt == max_retries - 1:
                raise
            sys.stderr.write(f"  ! request failed ({exc}); retry in {backoff:.0f}s\n")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
    raise RuntimeError(f"giving up after {max_retries} attempts")


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
        c["dissolved"] = cl.get("dissolved_year", "")
        c["validation"] = classify_validation(qid, p31_labels, cl["dissolved"])
    return candidates


def iter_category_members(session, category, cmtype, delay, timeout):
    """Yield members of a category, transparently handling continuation.

    cmtype is "page" (articles) or "subcat" (subcategories).
    """
    cont = {}
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": cmtype,
            "cmlimit": "500",
            "cmprop": "ids|title|type",
            **cont,
        }
        # Restrict article collection to the main namespace (drops Template:,
        # Portal:, Wikipedia:, etc. that occasionally get categorized).
        if cmtype == "page":
            params["cmnamespace"] = "0"
        data = api_get(session, params, timeout)
        for member in data.get("query", {}).get("categorymembers", []):
            yield member
        if "continue" in data:
            cont = data["continue"]
            time.sleep(delay)
        else:
            return


def is_real_article(title):
    return not any(title.startswith(p) for p in TITLE_PREFIX_BLOCKLIST)


def title_to_url(title):
    return "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")


def crawl(seeds, max_depth, delay, timeout, include_defunct, writer, flush,
          proxies=None, checkpoint_path=None, resume=False, extra_seen=None):
    """Breadth-first walk of the category tree, streaming rows to `writer`.

    Returns the number of unique articles found. If `checkpoint_path` is set,
    state (queue/visited/seen) is saved periodically and on Ctrl-C so the run
    can be continued later with resume=True.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if proxies:
        session.proxies.update(proxies)

    visited_cats = set()
    seen_pages = set()  # pageids already written
    queue = deque()

    if resume and checkpoint_path and os.path.exists(checkpoint_path):
        with open(checkpoint_path, encoding="utf-8") as fh:
            ck = json.load(fh)
        visited_cats = set(ck["visited"])
        seen_pages = set(ck["seen"])
        queue = deque((c, d) for c, d in ck["queue"])
        sys.stderr.write(
            f"resumed from checkpoint: {len(visited_cats)} cats done, "
            f"{len(seen_pages)} pages, {len(queue)} queued\n"
        )
    else:
        queue = deque((c, 0) for c in seeds)
    if extra_seen:
        seen_pages |= extra_seen

    def save_checkpoint():
        if not checkpoint_path:
            return
        tmp = checkpoint_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {"queue": list(queue), "visited": list(visited_cats),
                 "seen": list(seen_pages)},
                fh,
            )
        os.replace(tmp, checkpoint_path)

    processed = 0
    try:
        while queue:
            category, depth = queue.popleft()
            if category in visited_cats:
                continue
            visited_cats.add(category)

            try:
                # 1) collect article pages in this category
                new_here = 0
                for member in iter_category_members(
                    session, category, "page", delay, timeout
                ):
                    title = member["title"]
                    pageid = member["pageid"]
                    if pageid in seen_pages or not is_real_article(title):
                        continue
                    seen_pages.add(pageid)
                    writer.writerow(
                        {
                            "title": title,
                            "url": title_to_url(title),
                            "pageid": pageid,
                            "source_category": category[len("Category:"):],
                        }
                    )
                    new_here += 1

                # 2) enqueue subcategories (depth-limited + name-pruned)
                n_subcats = 0
                if depth < max_depth:
                    for member in iter_category_members(
                        session, category, "subcat", delay, timeout
                    ):
                        subcat = member["title"]
                        if subcat in visited_cats:
                            continue
                        if not should_descend(subcat, include_defunct):
                            continue
                        queue.append((subcat, depth + 1))
                        n_subcats += 1

                flush()
                tag = category[len("Category:"):]
                warn = "  <-- EMPTY (check name?)" if (new_here == 0 and n_subcats == 0) else ""
                sys.stderr.write(
                    f"[d{depth}] {tag[:60]:<60} +{new_here:>4} pages, "
                    f"{n_subcats:>3} subcats | total={len(seen_pages)} "
                    f"queue={len(queue)}{warn}\n"
                )
            except Exception as exc:  # noqa: BLE001 - keep crawling on per-cat failure
                sys.stderr.write(f"  !! skipping {category}: {exc}\n")

            processed += 1
            if processed % 25 == 0:
                save_checkpoint()
            time.sleep(delay)
    except KeyboardInterrupt:
        save_checkpoint()
        sys.stderr.write(
            "\ninterrupted; checkpoint saved. Re-run with --resume to continue.\n"
        )
        raise

    # completed cleanly — drop the checkpoint so a fresh run starts over
    if checkpoint_path and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    return len(seen_pages)


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


def main():
    parser = argparse.ArgumentParser(
        description="Crawl Wikipedia for US K-12 school articles."
    )
    parser.add_argument("--out", default="k12_schools.csv", help="output CSV path")
    parser.add_argument(
        "--max-depth", type=int, default=6,
        help="max category recursion depth (default 6)",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="seconds to sleep between API requests (default 0.5)",
    )
    parser.add_argument(
        "--timeout", type=float, default=60,
        help="per-request timeout in seconds (default 60)",
    )
    parser.add_argument(
        "--proxy", default=None,
        help="HTTP/HTTPS proxy URL, e.g. http://127.0.0.1:7890",
    )
    parser.add_argument(
        "--include-defunct", action="store_true",
        help="also include closed/historical schools",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="continue from the checkpoint of an interrupted run (appends to --out)",
    )
    parser.add_argument(
        "--checkpoint", default=None,
        help="checkpoint file path (default: <out>.ckpt.json)",
    )
    parser.add_argument("--no-validate", action="store_true",
                        help="skip Wikidata tagging; emit raw candidates as --out")
    parser.add_argument("--write-status", default="",
                        help="comma list of validation tags to write "
                             "(default: all). e.g. school,unverified")
    args = parser.parse_args()

    seeds = list(SEED_CATEGORIES)
    if args.include_defunct:
        seeds += DEFUNCT_SEEDS

    checkpoint_path = args.checkpoint or (args.out + ".ckpt.json")
    resuming = args.resume and os.path.exists(checkpoint_path)

    sys.stderr.write(
        f"Seeds: {len(seeds)} categories, max_depth={args.max_depth}, "
        f"delay={args.delay}s, timeout={args.timeout}s"
        f"{' | RESUMING' if resuming else ''}\n"
    )

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


if __name__ == "__main__":
    main()
