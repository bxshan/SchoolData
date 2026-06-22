#!/usr/bin/env python3
"""Diagnostic: check each seed category's health and where the volume lives.

For every seed it prints whether the category exists, how many direct article
pages and subcategories it has, and (for the broad roots) lists the first-level
subcategories so we can see if names resolve and where schools are filed.

Run:  python diag.py            # optionally: python diag.py --proxy http://127.0.0.1:7890
"""
import argparse
import sys
import requests

API = "https://en.wikipedia.org/w/api.php"
UA = "K12SchoolCrawler-diag/1.0 (contact: boxuan.shan@gmail.com)"

SEEDS = [
    "Category:Schools in the United States by state",
    "Category:High schools in the United States by state",
    "Category:Middle schools in the United States by state",
    "Category:Elementary schools in the United States by state",
    "Category:Private elementary schools in the United States",
    "Category:Private middle schools in the United States",
    "Category:Private high schools in the United States",
    "Category:Catholic schools in the United States by state",
    # extra candidates to test alternative names:
    "Category:Schools in the United States",
    "Category:Public elementary schools in the United States",
    "Category:Charter schools in the United States",
]


def get(session, **params):
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    r = session.get(API, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def count_members(session, cat, cmtype):
    """Return (count, sample_titles) across all continuation pages."""
    titles, cont = [], {}
    while True:
        d = get(session, action="query", list="categorymembers", cmtitle=cat,
                cmtype=cmtype, cmlimit="500", cmprop="title", **cont)
        titles += [m["title"] for m in d.get("query", {}).get("categorymembers", [])]
        if "continue" in d:
            cont = d["continue"]
        else:
            break
    return len(titles), titles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy")
    args = ap.parse_args()
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    if args.proxy:
        s.proxies.update({"http": args.proxy, "https": args.proxy})

    for cat in SEEDS:
        # does it exist?
        d = get(s, action="query", titles=cat, prop="info")
        page = d["query"]["pages"][0]
        exists = "missing" not in page
        if not exists:
            print(f"\n### {cat}\n    !!! MISSING (name does not exist)")
            continue
        npages, _ = count_members(s, cat, "page")
        nsub, subs = count_members(s, cat, "subcat")
        print(f"\n### {cat}\n    pages={npages}  subcats={nsub}")
        for t in subs[:60]:
            print(f"      - {t}")
        if nsub > 60:
            print(f"      ... (+{nsub - 60} more)")


if __name__ == "__main__":
    main()
