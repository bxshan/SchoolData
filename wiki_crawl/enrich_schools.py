#!/usr/bin/env python3
"""Clean + enrich the raw K-12 school crawl into a usable dataset.

Pipeline (reads schools.csv -> writes schools_enriched.csv):
  1. CLEAN  - drop obvious non-school rows (film/TV/song disambig pages,
              churches/cemeteries without "school"/"academy"); optionally drop
              accreditation-association member categories (--exclude-accreditation).
  2. RESOLVE- batch the MediaWiki API with redirects=1 so redirect pages collapse
              onto their real target article; de-duplicate by the resolved pageid.
  3. ENRICH - for every resolved article add: state, level (high/middle/
              elementary/combined), Wikidata QID, and lat/lon coordinates.

Output columns: title, url, pageid, state, level, wikidata_qid, lat, lon,
                source_category

Usage:
    python enrich_schools.py                       # schools.csv -> schools_enriched.csv
    python enrich_schools.py --in schools.csv --out schools_enriched.csv
    python enrich_schools.py --exclude-accreditation
    python enrich_schools.py --proxy http://127.0.0.1:7890
"""

import argparse
import csv
import re
import sys
import time

import requests

API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "K12SchoolEnricher/1.0 (contact: boxuan.shan@gmail.com) python-requests"

STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
    "Puerto Rico", "Guam",
]
_STATES_BY_LEN = sorted(STATES, key=len, reverse=True)

# Title patterns that are never a school (disambig/media pages).
TITLE_DROP = re.compile(
    r"\((?:\d{4} )?film\)|\(TV series\)|\(song\)|\(album\)|\(band\)|"
    r"\(novel\)|\(disambiguation\)",
    re.I,
)
CHURCH_CEM = re.compile(r"\b(church|cemetery|chapel|congregation)\b", re.I)
SCHOOLISH = re.compile(r"school|academ|yeshiv|institute|seminary|montessori", re.I)
ACCREDITATION = re.compile(r"accredit|commission on|association of", re.I)


def api_get(session, params, timeout=60, max_retries=8, base_url=None):
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    url = base_url or API_URL
    backoff = 1.0
    for attempt in range(max_retries):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code in (429, 503):
                ra = resp.headers.get("Retry-After")
                wait = float(ra) if (ra and ra.isdigit()) else backoff
                sys.stderr.write(f"  ! {resp.status_code}; waiting {wait:.0f}s\n")
                time.sleep(wait)
                backoff = min(backoff * 2, 60)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("error", {}).get("code") == "maxlag":
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            return data
        except (requests.RequestException, ValueError) as exc:
            if attempt == max_retries - 1:
                raise
            sys.stderr.write(f"  ! request failed ({exc}); retry in {backoff:.0f}s\n")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
    raise RuntimeError("giving up")


def state_of(text):
    for s in _STATES_BY_LEN:
        if s in text:
            return s
    return ""


def level_of(text):
    t = text.lower()
    if "high school" in t or "secondary" in t or "senior high" in t:
        return "high"
    if "middle school" in t or "junior high" in t or "intermediate school" in t:
        return "middle"
    if any(k in t for k in ("elementary", "primary school", "grade school", "grammar school")):
        return "elementary"
    if any(k in t for k in ("k–12", "k-12", "k–8", "k-8")):
        return "combined"
    return ""


def clean(rows, exclude_accreditation):
    kept, dropped = [], 0
    for r in rows:
        title, sc = r["title"], r["source_category"]
        if ":" in title and title.split(":")[0] in (
            "Template", "Portal", "Wikipedia", "Draft", "Module", "Help",
            "Category", "File", "User", "MediaWiki", "Talk",
        ):
            dropped += 1
            continue
        if TITLE_DROP.search(title):
            dropped += 1
            continue
        # churches/cemeteries that are not also a school/academy
        if CHURCH_CEM.search(title) and not SCHOOLISH.search(title):
            dropped += 1
            continue
        if exclude_accreditation and ACCREDITATION.search(sc):
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def resolve_and_enrich(session, rows, delay):
    """Resolve redirects and attach wikidata/coords; de-dupe by resolved pageid."""
    out = {}  # resolved pageid -> record
    titles = [r["title"] for r in rows]
    # keep a map from input title -> original source_category (first wins)
    src = {}
    for r in rows:
        src.setdefault(r["title"], r["source_category"])

    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        base = {
            "action": "query",
            "titles": "|".join(batch),
            "redirects": "1",
            "prop": "info|coordinates|pageprops|categories|description|pageviews|pageimages",
            "ppprop": "wikibase_item",
            "coprop": "lat|lon",
            "colimit": "max",
            "cllimit": "max",
            "pvipdays": "60",          # 60 days of daily pageviews
            "piprop": "thumbnail",
            "pithumbsize": "320",
        }
        # The categories list can paginate; follow continue and merge cats.
        pages = {}
        redir, norm = {}, {}
        cont = {}
        while True:
            data = api_get(session, {**base, **cont})
            q = data.get("query", {})
            redir.update({x["from"]: x["to"] for x in q.get("redirects", [])})
            norm.update({x["from"]: x["to"] for x in q.get("normalized", [])})
            for p in q.get("pages", []):
                acc = pages.setdefault(p["title"], p)
                if acc is not p:
                    acc.setdefault("categories", []).extend(p.get("categories", []))
            if "continue" in data:
                cont = data["continue"]
            else:
                break

        def resolved_title(t):
            t = norm.get(t, t)
            seen = 0
            while t in redir and seen < 5:
                t = redir[t]
                seen += 1
            return t

        bytitle = pages
        for orig in batch:
            page = bytitle.get(resolved_title(orig))
            if not page or page.get("missing") or "pageid" not in page:
                continue
            pid = page["pageid"]
            if pid in out:
                continue
            coords = page.get("coordinates")
            lat = coords[0]["lat"] if coords else ""
            lon = coords[0]["lon"] if coords else ""
            qid = page.get("pageprops", {}).get("wikibase_item", "")
            title = page["title"]
            sc = src.get(orig, "")
            cats_text = " ".join(c["title"] for c in page.get("categories", []))
            ctx = title + " | " + sc + " | " + cats_text
            pv = page.get("pageviews") or {}
            views = sum(v for v in pv.values() if v)
            thumb = page.get("thumbnail", {}).get("source", "")
            out[pid] = {
                "title": title,
                "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                "pageid": pid,
                "state": state_of(sc) or state_of(cats_text) or state_of(title),
                "level": level_of(ctx),
                "description": page.get("description", ""),
                "instance_of": "",
                "founded": "",
                "website": "",
                "school_district": "",
                "nces_id": "",
                "postal_code": "",
                "wikidata_qid": qid,
                "lat": lat,
                "lon": lon,
                "pageviews_60d": views,
                "thumbnail": thumb,
                "source_category": sc,
            }
        sys.stderr.write(f"  resolved {min(i + 50, len(titles))}/{len(titles)} "
                         f"-> {len(out)} unique\n")
        time.sleep(delay)
    return out


WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def _claim_value(claims, pid):
    """Return the first mainsnak value for property `pid`, or None."""
    for c in claims.get(pid, []):
        snak = c.get("mainsnak", {})
        if snak.get("snaktype") != "value":
            continue
        return snak.get("datavalue", {}).get("value")
    return None


def enrich_wikidata(session, records, delay):
    """Add type/founded/website/district/NCES/postal columns from Wikidata.

    Uses the QIDs already on each record. Two passes: fetch claims, then resolve
    the labels of referenced entities (instance-of, school-district).
    """
    by_qid = {}
    for rec in records.values():
        if rec["wikidata_qid"]:
            by_qid.setdefault(rec["wikidata_qid"], []).append(rec)
    qids = list(by_qid)
    sys.stderr.write(f"fetching Wikidata claims for {len(qids)} entities...\n")

    label_needed = set()
    raw = {}  # qid -> dict of extracted (some values are QIDs to resolve)
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        data = api_get(session, {
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "claims",
        }, base_url=WIKIDATA_API)
        for qid, ent in data.get("entities", {}).items():
            cl = ent.get("claims", {})
            inst = _claim_value(cl, "P31")
            dist = _claim_value(cl, "P5353")
            founded = _claim_value(cl, "P571")
            year = ""
            if isinstance(founded, dict) and founded.get("time"):
                m = re.search(r"([+-]\d{4})", founded["time"])
                year = m.group(1).lstrip("+") if m else ""
            inst_q = inst.get("id") if isinstance(inst, dict) else None
            dist_q = dist.get("id") if isinstance(dist, dict) else None
            if inst_q:
                label_needed.add(inst_q)
            if dist_q:
                label_needed.add(dist_q)
            raw[qid] = {
                "instance_q": inst_q,
                "district_q": dist_q,
                "founded": year,
                "website": _claim_value(cl, "P856") or "",
                "nces_id": _claim_value(cl, "P2484") or "",
                "postal_code": _claim_value(cl, "P281") or "",
            }
        sys.stderr.write(f"  claims {min(i + 50, len(qids))}/{len(qids)}\n")
        time.sleep(delay)

    # resolve labels for instance-of / district entity QIDs
    labels = {}
    need = list(label_needed)
    sys.stderr.write(f"resolving {len(need)} entity labels...\n")
    for i in range(0, len(need), 50):
        chunk = need[i:i + 50]
        data = api_get(session, {
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "labels", "languages": "en",
        }, base_url=WIKIDATA_API)
        for qid, ent in data.get("entities", {}).items():
            labels[qid] = ent.get("labels", {}).get("en", {}).get("value", "")
        time.sleep(delay)

    for qid, ex in raw.items():
        for rec in by_qid[qid]:
            rec["instance_of"] = labels.get(ex["instance_q"], "") if ex["instance_q"] else ""
            rec["school_district"] = labels.get(ex["district_q"], "") if ex["district_q"] else ""
            rec["founded"] = ex["founded"]
            rec["website"] = ex["website"] if isinstance(ex["website"], str) else ""
            rec["nces_id"] = ex["nces_id"] if isinstance(ex["nces_id"], str) else ""
            rec["postal_code"] = ex["postal_code"] if isinstance(ex["postal_code"], str) else ""


def main():
    ap = argparse.ArgumentParser(description="Clean + enrich K-12 school crawl.")
    ap.add_argument("--in", dest="inp", default="schools.csv")
    ap.add_argument("--out", default="schools_enriched.csv")
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--exclude-accreditation", action="store_true",
                    help="drop rows whose source category is an accreditor/association")
    ap.add_argument("--no-wikidata", action="store_true",
                    help="skip the Wikidata pass (type/founded/website/district/NCES/postal)")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.inp, encoding="utf-8")))
    sys.stderr.write(f"loaded {len(rows)} rows from {args.inp}\n")

    rows, dropped = clean(rows, args.exclude_accreditation)
    sys.stderr.write(f"cleaned: dropped {dropped}, {len(rows)} remain\n")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})

    records = resolve_and_enrich(session, rows, args.delay)
    if not args.no_wikidata:
        enrich_wikidata(session, records, args.delay)

    fields = ["title", "url", "pageid", "state", "level", "description",
              "instance_of", "founded", "website", "school_district",
              "nces_id", "postal_code", "wikidata_qid", "lat", "lon",
              "pageviews_60d", "thumbnail", "source_category"]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for rec in sorted(records.values(), key=lambda r: (r["state"], r["title"])):
            w.writerow(rec)

    # quick stats
    n = len(records)
    def pct(key, test=lambda v: v not in ("", None)):
        c = sum(1 for r in records.values() if test(r.get(key)))
        return f"{c} ({100*c//max(n,1)}%)"
    sys.stderr.write(
        f"\nDone. {n} unique articles -> {args.out}\n"
        f"  Wikidata QID : {pct('wikidata_qid')}\n"
        f"  coordinates  : {pct('lat')}\n"
        f"  founded      : {pct('founded')}\n"
        f"  website      : {pct('website')}\n"
        f"  NCES id      : {pct('nces_id')}\n"
        f"  district     : {pct('school_district')}\n"
    )


if __name__ == "__main__":
    main()
