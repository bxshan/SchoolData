#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Clean + enrich the raw K-12 school crawl into a usable dataset.

Pipeline (reads schools.csv -> writes schools_enriched.csv):
  1. CLEAN  - drop obvious non-school rows (film/TV/song disambig pages,
              churches/cemeteries without "school"/"academy"); optionally drop
              accreditation-association member categories (--exclude-accreditation).
  2. RESOLVE- batch the MediaWiki API with redirects=1. A redirect whose target is
              itself a crawled school (e.g. a renamed school) collapses onto that
              article; de-duplicate by the resolved pageid. A redirect to any other
              page (usually the school's town or district: the school has no
              article of its own) is kept under its own title, tagged
              validation=redirect with `redirect_to` set, so the town/district
              page never enters the set posing as a school.
  3. ENRICH - for every resolved article add: state, level (high/middle/
              elementary/combined), Wikidata QID, and lat/lon coordinates.

Output columns: title, url, pageid, state, level, description, instance_of,
                founded, website, school_district, nces_id, postal_code,
                wikidata_qid, lat, lon, pageviews_60d, thumbnail,
                source_category, validation, redirect_to

`validation` is carried through from the crawl (school / unverified / defunct /
out_of_scope / non_school; blank if the input has no such column) so the match
step can keep only verified schools. Enrich adds one tag of its own, `redirect`
(see RESOLVE).

Usage:
    python enrich_schools.py                       # schools.csv -> schools_enriched.csv
    python enrich_schools.py --in schools.csv --out schools_enriched.csv
    python enrich_schools.py --exclude-accreditation
    python enrich_schools.py --proxy http://127.0.0.1:7890
"""

import argparse
import csv
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common.states import USPS_TO_NAME, state_in_text  # noqa: E402
from common.wiki_api import USER_AGENT, WIKIDATA_API, api_get  # noqa: E402



# Title patterns that are never a school (disambig/media pages).
TITLE_DROP = re.compile(
    r"\((?:\d{4} )?film\)|\(TV series\)|\(song\)|\(album\)|\(band\)|"
    r"\(novel\)|\(disambiguation\)",
    re.I,
)
CHURCH_CEM = re.compile(r"\b(church|cemetery|chapel|congregation)\b", re.I)
SCHOOLISH = re.compile(r"school|academ|yeshiv|institute|seminary|montessori", re.I)
ENRICHED_FIELDS = ["title", "url", "pageid", "state", "level", "description",
                   "instance_of", "founded", "website", "school_district",
                   "nces_id", "postal_code", "wikidata_qid", "lat", "lon",
                   "pageviews_60d", "thumbnail", "source_category", "lead",
                   "crawl_validation", "validation", "redirect_to", "defunct_category",
                   "country", "dissolved", "operating", "validation_note"]
ACCREDITATION = re.compile(r"accredit|commission on|association of", re.I)


def state_of(text):
    """Full state name mentioned in `text` (longest match wins), or ''."""
    return state_in_text(text)


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
    src, val, orig_pid = {}, {}, {}
    for r in rows:
        src.setdefault(r["title"], r["source_category"])
        val.setdefault(r["title"], r.get("validation", ""))
        orig_pid.setdefault(r["title"], r.get("pageid", ""))
    crawled = set(src)

    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        base = {
            "action": "query",
            "titles": "|".join(batch),
            "redirects": "1",
            "prop": "info|coordinates|pageprops|categories|description|pageviews|pageimages|extracts",
            # exchars, not exsentences: the sentence splitter stops at "St." / "Dr."
            "exintro": "1", "explaintext": "1", "exchars": "300", "exlimit": "max",
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
                    if p.get("extract") and not acc.get("extract"):
                        acc["extract"] = p["extract"]
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
            target = resolved_title(orig)
            if norm.get(orig, orig) in redir and target not in crawled:
                # The school has no article of its own: its title redirects to
                # a page outside the crawl (usually its town or district, e.g.
                # "Joliet Montessori School" -> "Crest Hill, Illinois"). Keep it,
                # labeled, instead of letting the town/district page pose as a
                # school or silently dropping the row.
                key = ("redirect", orig)
                if key not in out:
                    out[key] = _redirect_record(orig, orig_pid.get(orig, ""),
                                                target, src.get(orig, ""))
                continue
            page = bytitle.get(target)
            if not page or page.get("missing") or "pageid" not in page:
                continue
            pid = page["pageid"]
            if pid in out:
                # A redirect title has no QID of its own, so the crawl tags it
                # `unverified`; let a real tag from the target article win.
                if out[pid]["validation"] in ("", "unverified"):
                    out[pid]["validation"] = val.get(orig, "") or out[pid]["validation"]
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
                "validation": val.get(orig, ""),
                "crawl_validation": val.get(orig, ""),
                "lead": re.sub(r"\s+", " ", page.get("extract") or "").strip()[:400],
                "redirect_to": "",
                "defunct_category": defunct_category(
                    [sc] + [c["title"] for c in page.get("categories", [])]),
                "country": "", "dissolved": "", "operating": "",
                "validation_note": "",
            }
        sys.stderr.write(f"  resolved {min(i + 50, len(titles))}/{len(titles)} "
                         f"-> {len(out)} unique\n")
        time.sleep(delay)
    return out




def _redirect_record(title, pageid, target, source_category):
    """Row for a crawled title that is only a redirect to a non-school page."""
    rec = {k: "" for k in ENRICHED_FIELDS}
    rec.update({
        "title": title,
        "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
        "pageid": pageid,
        "state": state_of(source_category) or state_of(title),
        "level": level_of(title + " | " + source_category),
        "source_category": source_category,
        "validation": "redirect",
        "crawl_validation": "redirect",
        "redirect_to": target,
    })
    return rec


def _claim_ids(claims, pid):
    """Every entity id asserted for property `pid` (value snaks only)."""
    out = []
    for c in claims.get(pid, []):
        snak = c.get("mainsnak", {})
        v = snak.get("datavalue", {}).get("value") if snak.get("snaktype") == "value" else None
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


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
            inst_qs = _claim_ids(cl, "P31")
            country_qs = _claim_ids(cl, "P17")
            dist = _claim_value(cl, "P5353")
            founded = _claim_value(cl, "P571")
            year = ""
            if isinstance(founded, dict) and founded.get("time"):
                m = re.search(r"([+-]\d{4})", founded["time"])
                year = m.group(1).lstrip("+") if m else ""
            dist_q = dist.get("id") if isinstance(dist, dict) else None
            label_needed.update(inst_qs + country_qs[:1])
            if dist_q:
                label_needed.add(dist_q)
            raw[qid] = {
                "instance_qs": inst_qs,
                "country_q": country_qs[0] if country_qs else None,
                "dissolved": any(c.get("mainsnak", {}).get("snaktype") == "value"
                                 for c in cl.get("P576", [])),
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
            rec["instance_of"] = "|".join(l for l in (labels.get(q, "") for q in ex["instance_qs"]) if l)
            rec["country"] = labels.get(ex["country_q"], "") if ex["country_q"] else ""
            rec["dissolved"] = "1" if ex["dissolved"] else ""
            rec["school_district"] = labels.get(ex["district_q"], "") if ex["district_q"] else ""
            rec["founded"] = ex["founded"]
            rec["website"] = ex["website"] if isinstance(ex["website"], str) else ""
            rec["nces_id"] = ex["nces_id"] if isinstance(ex["nces_id"], str) else ""
            rec["postal_code"] = ex["postal_code"] if isinstance(ex["postal_code"], str) else ""


from revalidate_rules import (  # noqa: E402  (the offline-rerunnable rules)
    DEFUNCT_CATEGORY, NcesLocator, defunct_category, revalidate)


# Intermediates live in output/ (a sibling of the scripts). Bare --in/--out names
# resolve here; pass a path with a separator to read/write elsewhere.
OUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def _out(name):
    return name if os.path.dirname(name) else os.path.join(OUT_DIR, name)


def fetch_leads(session, pageids, delay):
    """pageid -> first 300 characters of the article (plain text), 20 per request."""
    out = {}
    for i in range(0, len(pageids), 20):
        chunk = pageids[i:i + 20]
        data = api_get(session, {"action": "query", "pageids": "|".join(chunk),
                                 "prop": "extracts", "exintro": "1", "explaintext": "1",
                                 "exchars": "300", "exlimit": "max"})
        for p in data.get("query", {}).get("pages", []):
            out[str(p.get("pageid"))] = re.sub(r"\s+", " ", p.get("extract") or "").strip()[:400]
        if (i // 20) % 50 == 0:
            sys.stderr.write(f"  leads {min(i + 20, len(pageids))}/{len(pageids)}\n")
        time.sleep(delay)
    return out


def write_enriched(path, records):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ENRICHED_FIELDS, extrasaction="ignore")
        w.writeheader()
        for rec in sorted(records.values(), key=lambda r: (r["state"], r["title"])):
            w.writerow(rec)


def main():
    ap = argparse.ArgumentParser(description="Clean + enrich K-12 school crawl.")
    ap.add_argument("--in", dest="inp", default="schools.csv")
    ap.add_argument("--out", default="schools_enriched.csv")
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--exclude-accreditation", action="store_true",
                    help="drop rows whose source category is an accreditor/association")
    nces_out = os.path.join(os.path.dirname(__file__), "..", "nces_crawl", "output_all_schools")
    ap.add_argument("--nces-coords", default=os.path.join(nces_out, "school_coordinates.csv"),
                    help="NCES school coordinates used to infer a missing state; '' disables")
    ap.add_argument("--nces-master", default=os.path.join(nces_out, "all_schools_master.csv"))
    ap.add_argument("--refresh-leads", action="store_true",
                    help="re-fetch every article's first 300 characters into the "
                         "existing --out file, then revalidate (~15 min)")
    ap.add_argument("--revalidate-only", action="store_true",
                    help="re-run revalidate() on the existing --out file (after a "
                         "rule change) without any network access, then exit")
    ap.add_argument("--no-wikidata", action="store_true",
                    help="skip the Wikidata pass (type/founded/website/district/NCES/postal)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    args.inp = _out(args.inp)
    args.out = _out(args.out)
    locator = (NcesLocator(args.nces_coords, args.nces_master)
               if args.nces_coords and os.path.exists(args.nces_coords) else None)

    if args.revalidate_only or args.refresh_leads:
        with open(args.out, newline="", encoding="utf-8") as fh:
            records = {i: r for i, r in enumerate(csv.DictReader(fh))}
        if args.refresh_leads:
            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
            if args.proxy:
                session.proxies.update({"http": args.proxy, "https": args.proxy})
            leads = fetch_leads(session, [r["pageid"] for r in records.values()
                                          if r["validation"] != "redirect"], args.delay)
            for r in records.values():
                if r["pageid"] in leads:
                    r["lead"] = leads[r["pageid"]]
        changes = revalidate(records, locator)
        sys.stderr.write(f"revalidated {len(records):,} rows offline: {dict(changes)}\n")
        write_enriched(args.out, records)
        return

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
    changes = revalidate(records, locator)
    sys.stderr.write(f"revalidated: {dict(changes)}\n")
    write_enriched(args.out, records)

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
