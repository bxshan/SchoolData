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


# ---------------------------------------------------------------- revalidation
# Post-enrichment checks on signals the crawl didn't have (Wikidata description,
# all P31 types, country, dissolution, coordinates). Each change is recorded in
# `validation_note`; nothing is dropped.

US_COUNTRIES = {"united states", "united states of america", "puerto rico", "guam",
                "american samoa", "northern mariana islands",
                "united states virgin islands"}

SCHOOLISH_DESC = re.compile(
    r"\b(school|academy|yeshiva|montessori|lyceum|gymnasium)\b", re.I)
HIGHER_ED = re.compile(
    r"(?!.*(prep|k-12|k–12|high school))\b(university|college|seminary|"
    r"theological|institute of technology)\b", re.I)
# The description's head noun (within its first few words) is a network or
# district — "Charter school network in Chicago" — as opposed to a school that
# merely mentions its district ("Public high school in the X school district").
NETWORK = re.compile(
    r"^(?:\S+\s+){0,3}?(network|district|school system|organization|"
    r"organisation|board of education|group of schools)\b(?!\s+(?:school|high|academy))",
    re.I)
# Wikidata types that make an item a K-12 school, whatever else it is typed as.
K12_TYPE = re.compile(
    r"\b(high|middle|elementary|primary|secondary|junior high|senior high|charter|"
    r"public|private|boarding|magnet|preparatory|parochial|catholic|montessori|"
    r"k-12|early college high|comprehensive)\s+school\b", re.I)
# A title naming one school ("... High School", "... Academy"), not a system ("... Schools").
SINGLE_SCHOOL_TITLE = re.compile(r"\b(school|academy|institute)\b(?!s)", re.I)
# First sentence tense: "X is a public high school" vs "X was a public high school".
_LEAD_IS = re.compile(r"^[^.]{0,200}?\b(is|are)\s+(an?|the)\b", re.I)
_LEAD_WAS = re.compile(r"^[^.]{0,200}?\b(was|were)\s+(an?|the)\b", re.I)
# Past without "was": "is a former/defunct/closed ...", or "is a historic
# ... building/schoolhouse/site" (a listed building, not a running school).
# A bare "is a historic elementary school" is left undecided: many open
# schools are listed buildings too (Olney Elementary School, Philadelphia).
_LEAD_FORMER = re.compile(
    r"\b(is|are)\s+(an?|the)\s+(former|defunct|closed|"
    r"historic\b[^.]{0,60}?\b(building|schoolhouse|site|structure|district))\b", re.I)
_LEAD_BUILT = re.compile(r"\b(was|were)\s+(built|constructed|erected|designed)\b", re.I)
_LEAD_LISTED = re.compile(r"National Register|historic", re.I)
_LEAD_HISTORIC_SCHOOL = re.compile(r"\b(is|are)\s+(an?|the)\s+historic\b", re.I)
# Concept articles: "A ranch school is a type of school used in ..."
_LEAD_CONCEPT = re.compile(r"\b(is|are)\s+(an?|the)\s+(type|kind|form|style|model)\s+of\b", re.I)
_ABBREV_DOT = re.compile(r"\b(St|Sts|Ste|Mt|Dr|Jr|Sr|No|Ft|Rev|Msgr|Sen|Gen|Pres|Ave|Blvd|Rd|Hwy|Co|Inc|Corp|Bros)\.", re.I)
# What the first sentence says the subject *is*: the head (last) noun of the
# noun phrase after "is a", cut where a preposition or verb starts.
#   "a public charter school network in ..."         -> network  (network)
#   "a public high school in the ... school district" -> school   (school)
#   "a Dallas ISD magnet high school located in ..."  -> school   (school)
#   "a network of charter schools"                    -> network  (network)
_LEAD_SUBJECT = re.compile(r"\b(?:is|are)\s+(?:an?|the)\s+([^.]{0,200})", re.I)
_NP_END = re.compile(
    r"\s(?:in|of|on|at|for|from|to|by|with|within|under|near|located|based|"
    r"headquartered|serving|that|which|who|where|founded|established|operated|"
    r"run|owned|and\s+(?:is|was))\b", re.I)
_HEAD_NOUN = re.compile(
    r"\b(schools?\s+(?:network|district|system|corporation)|charter\s+(?:network|management)|"
    r"network|system|district|organization|organisation|group|"
    r"schools?|academy|institute|institution|college|university|seminary|yeshiva|"
    r"conservatory|center|centre|complex|campus|program|programme)\b(?!-)", re.I)
_NETWORK_HEADS = re.compile(
    r"^(schools?\s+(network|district|system|corporation)|charter\s+(network|management)|"
    r"network|system|district|organi[sz]ation|group)$", re.I)
# "is a part of the X School District" says where it belongs, not what it is.
_BELONGS = re.compile(r"^(?:\S+\s+){0,2}?(part|member|campus|division|unit|branch|work|ministry)\s+of\b", re.I)


def _lead_clean(lead):
    lead = _ABBREV_DOT.sub(r"\1", lead or "")
    lead = re.sub(r"\b([A-Z])\.", r"\1", lead)            # initials: "R. J. Neutra"
    return re.sub(r"\s*\([^)]*\)", "", lead)               # "(DISD)", "(formerly ...)"


def lead_head_noun(lead):
    """Head noun of what the first sentence says the subject is, or ''."""
    first = re.split(r"(?<=[.!?])\s", _lead_clean(lead), maxsplit=1)[0]
    m = _LEAD_SUBJECT.search(first)
    if not m or _BELONGS.search(m.group(1)):
        return ""
    np_ = _NP_END.split(" " + m.group(1), maxsplit=1)[0]
    heads = _HEAD_NOUN.findall(np_)
    return heads[-1].lower() if heads else ""


def lead_names_network(lead):
    """True when the first sentence's subject is a network/district/system."""
    head = lead_head_noun(lead)
    return bool(head and _NETWORK_HEADS.match(head))


def lead_tense(lead):
    """'present' for "X is a ... school", 'past' for "X was a ...", else ''."""
    lead = _lead_clean(lead)
    first = re.split(r"(?<=[.!?])\s", lead, maxsplit=1)[0]
    if _LEAD_FORMER.search(first):
        return "past"
    # A listed building: "The Pine Bluffs High School, at 7th and Elm, was built
    # in 1929. It was listed on the National Register of Historic Places ..."
    if _LEAD_BUILT.search(first) and _LEAD_LISTED.search(lead):
        return "past"
    is_, was = _LEAD_IS.search(first), _LEAD_WAS.search(first)
    if was and (not is_ or was.start(1) < is_.start(1)):   # the earlier verb decides
        return "past"
    if _LEAD_HISTORIC_SCHOOL.search(first):
        return ""
    return "present" if is_ else ""
# Building-only Wikidata types. A school also typed "high school", "public
# school", ... is an operating school whose building happens to be listed.
BUILDING_P31 = re.compile(
    r"school building|one-room school|rosenwald school|schoolhouse|former school|"
    r"building|historic|national register|place", re.I)


def building_only(instance_of):
    labels = [l for l in (instance_of or "").split("|") if l.strip()]
    return bool(labels) and all(BUILDING_P31.search(l) for l in labels)
FORMER_DESC = re.compile(r"\b(former|defunct|closed)\b", re.I)
# A page in any closed-school category ("Defunct high schools in Ohio",
# "Educational institutions disestablished in 1971", ...). Wikidata often lacks
# a dissolution date for these, so the crawl tags many of them `school`.
# "Former" is deliberately absent: "Former girls' schools" and "Former
# university-affiliated schools" hold schools that are still open.
DEFUNCT_CATEGORY = re.compile(
    r"\b(defunct|closed|demolished)\b[^|]*\b(schools?|academ|institutions?)|"
    r"disestablished in \d{4}|disestablishments in", re.I)


def defunct_category(categories):
    """First closed-school category among `categories` (kept for auditing), or ''."""
    return next((c for c in categories if DEFUNCT_CATEGORY.search(c)), "")


class NcesLocator:
    """Nearest NCES school -> state, for articles whose text names no state.

    Joins nces_crawl's school_coordinates.csv (NCES EDGE / PSS coordinates) to
    the all-schools master for each school's state; an article within `max_km`
    of an NCES school is taken to be in that school's state."""

    def __init__(self, coords_path, master_path, max_km=25.0):
        self.max_km, self.grid = max_km, {}
        with open(master_path, newline="", encoding="utf-8") as fh:
            state = {r["school_id"]: r["state"] for r in csv.DictReader(fh)}
        with open(coords_path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not (r["lat"] and r["lon"] and r["school_id"] in state):
                    continue
                y, x = float(r["lat"]), float(r["lon"])
                key = (int(y * 4), int(x * 4))                 # 0.25-degree cells
                self.grid.setdefault(key, []).append((y, x, state[r["school_id"]]))

    def state(self, lat, lon):
        import math
        cy, cx = int(lat * 4), int(lon * 4)
        best, best_km = None, self.max_km
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for y, x, st in self.grid.get((cy + dy, cx + dx), ()):
                    km = 111.0 * math.hypot(y - lat, (x - lon) * math.cos(math.radians(lat)))
                    if km < best_km:
                        best, best_km = st, km
        return USPS_TO_NAME.get(best, "")


def revalidate(records, locator=None):
    """Fill missing states and re-examine tags; returns a Counter of changes."""
    from collections import Counter
    changes = Counter()
    for rec in records.values():
        desc, inst = rec.get("description", ""), rec.get("instance_of", "")
        notes = []
        if rec.get("crawl_validation"):
            rec["validation"] = rec["crawl_validation"]      # idempotent re-runs
        tense = lead_tense(rec.get("lead"))
        k12 = bool(K12_TYPE.search(inst))

        # 1. state: Wikidata description ("school in Talladega, Alabama"), then coords
        if not rec["state"]:
            st = state_of(desc)
            if not st and locator and rec.get("lat") not in ("", None):
                st = locator.state(float(rec["lat"]), float(rec["lon"]))
            if st:
                rec["state"] = st
                notes.append("state from " + ("description" if state_of(desc) else "coordinates"))
                changes["state_filled"] += 1

        # 2. operating. The article's own first sentence decides when it can:
        #    "X is a ... school" is open whatever its categories say (articles on
        #    a current school often also carry a closed predecessor's category),
        #    "X was a ..." is closed. Otherwise fall back to Wikidata/categories.
        if rec["validation"] not in ("redirect",):
            if tense:
                closed = tense == "past"
            else:
                closed = (rec.get("dissolved") or building_only(inst)
                          or FORMER_DESC.search(desc) or rec.get("defunct_category")
                          or rec["validation"] == "defunct")
            rec["operating"] = "no" if closed else "yes"

        # 3. validation fixes
        v = rec["validation"]
        country = (rec.get("country") or "").lower()
        if v in ("school", "unverified") and _LEAD_CONCEPT.search(_lead_clean(rec.get("lead"))):
            rec["validation"] = "non_school"
            notes.append("concept article: the first sentence describes a type of school")
        elif v in ("school", "unverified") and country and country not in US_COUNTRIES \
                and not rec["state"]:
            rec["validation"] = "out_of_scope"
            notes.append(f"foreign ({rec['country']})")
        elif v == "school" and not k12 and (HIGHER_ED.search(desc) or HIGHER_ED.search(inst)) \
                and not SCHOOLISH_DESC.search(desc.replace("college prep", "")):
            rec["validation"] = "out_of_scope"
            notes.append("higher education")
        elif v == "school" and lead_names_network(rec.get("lead")) \
                and not (k12 and SINGLE_SCHOOL_TITLE.search(rec["title"])):
            # (single-school districts — "Wallkill Valley Regional High School is
            # a four-year public high school and regional school district" — stay)
            rec["validation"] = "out_of_scope"
            notes.append("network/district: the article's first sentence says so")
        elif v == "school" and NETWORK.search(desc) \
                and not (k12 and SINGLE_SCHOOL_TITLE.search(rec["title"])) \
                and not (tense == "present" and lead_head_noun(rec.get("lead"))):
            # (the Wikidata description only decides when the article's first
            # sentence doesn't say what the subject is)
            # A single-school district ("Lenape Valley Regional High School" is
            # described as "School district in Sussex County") stays a school.
            rec["validation"] = "out_of_scope"
            notes.append("network/district: " + NETWORK.search(desc).group(0))
        elif v == "school" and rec.get("defunct_category") and tense != "present":
            rec["validation"] = "defunct"
            notes.append(f"in a closed-school category: {rec['defunct_category']}")
        elif v in ("out_of_scope", "non_school", "defunct") and k12 and tense == "present" \
                and SINGLE_SCHOOL_TITLE.search(rec["title"]) and not NETWORK.search(desc):
            rec["validation"] = "school"
            notes.append(f"rescued: K-12 type and the article says it is a school (crawl: {v})")
        elif v == "unverified" and rec["wikidata_qid"] and SCHOOLISH_DESC.search(desc) \
                and not NETWORK.search(desc) and not HIGHER_ED.search(desc):
            rec["validation"] = "school"
            notes.append("rescued: description names a school")
        if rec["validation"] != v:
            changes[f"{v}->{rec['validation']}"] += 1
        rec["validation_note"] = "; ".join(notes)
    return changes


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
