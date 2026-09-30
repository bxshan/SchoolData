"""MediaWiki / Wikidata API access shared by the wiki_crawl scripts."""

import sys
import time

import requests

API_URL = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Wikimedia's User-Agent policy: identify the tool and a contact.
USER_AGENT = ("SchoolDataBot/1.0 (https://github.com/bxshan/SchoolData; "
              "contact: boxuan.shan@gmail.com) python-requests")


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
