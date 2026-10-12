#!/usr/bin/env python3
# Author: Boxuan Shan, with support from Claude (Anthropic)
"""Fill a copy of the Google Doc template with one school's fact sheet.

The template is a formatted Google Doc (page setup, fonts, and a dropdown in
the "Your review" column). To make a school's doc: copy the template in Drive,
read the copy with the Google Docs API (documents.get), then run this script
on that JSON and the school's sheet. It prints a documents.batchUpdate body
that replaces, in place:
  - the title (the first paragraph ending in "— Public Fact Sheet"),
  - the three bulleted questions,
  - the Fact, Value and Source cells of rows 1–15,
and leaves the dropdown and correction columns, and all formatting, untouched.

Requests run from the highest index down, so earlier edits never shift later
ones. The batch is guarded by the copy's revisionId.

Usage:
    python gdoc_requests.py COPY.json sheets/<nces_id>.md > requests.json
"""

import json
import re
import sys

LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
ITALIC = re.compile(r"\*([^*]+)\*")
LINK_STYLE = {"underline": True, "foregroundColor": {"color": {"rgbColor": {"blue": 0.93333334}}}}


def u16(text):
    return len(text.encode("utf-16-le")) // 2


def segments(cell):
    """Markdown cell -> [(text, url or None, italic)]. Bare URLs become links."""
    out, pos = [], 0
    for m in LINK.finditer(cell):
        out += _plain(cell[pos:m.start()])
        out.append((m.group(1), m.group(2), False))
        pos = m.end()
    out += _plain(cell[pos:])
    return [s for s in out if s[0]]


def _plain(text):
    out, pos = [], 0
    for m in ITALIC.finditer(text):
        out.append((text[pos:m.start()], None, False))
        out.append((m.group(1), None, True))
        pos = m.end()
    out.append((text[pos:], None, False))
    return [(t, t.strip(), False) if re.fullmatch(r"https?://\S+", t.strip()) else (t, u, i)
            for t, u, i in out]


def read_sheet(path):
    text = open(path, encoding="utf-8").read()
    title = re.search(r"^\*\*(.+?) — Public Fact Sheet", text, re.M).group(1)
    questions = re.findall(r"^\d\.\s+(.+)$", text.split("## Facts")[0], re.M)
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0].isdigit():
            rows.append(cells[1:4])
    if len(questions) != 3 or len(rows) != 15:
        raise ValueError(f"{path}: {len(questions)} questions, {len(rows)} rows")
    return title, questions, rows


def build(doc, title, questions, rows):
    tab = doc["tabs"][0]
    tab_id = tab["tabProperties"]["tabId"]
    body = tab["documentTab"]["body"]["content"]

    def text_of(p):
        return "".join(e.get("textRun", {}).get("content", "") for e in p["paragraph"]["elements"])

    paras = [e for e in body if "paragraph" in e]
    heads = [p for p in paras if text_of(p).rstrip("\n").endswith("— Public Fact Sheet")]
    bullets = [p for p in paras if "bullet" in p["paragraph"]]
    tables = [e for e in body if "table" in e]
    if len(heads) != 1 or len(bullets) != 3 or len(tables) != 1:
        raise ValueError("template layout changed: expected 1 title, 3 questions, 1 table")

    # (start, end, segments, is_table_cell)
    ops = [(heads[0]["startIndex"], heads[0]["endIndex"],
            [(f"{title} — Public Fact Sheet", None, False)], False)]
    ops += [(p["startIndex"], p["endIndex"], [(q, None, False)], False)
            for p, q in zip(bullets, questions)]
    table_rows = tables[0]["table"]["tableRows"]
    for r, row in enumerate(rows, 1):
        for c, cell in enumerate(row, 1):
            content = table_rows[r]["tableCells"][c]["content"]
            if len(content) != 1:
                raise ValueError(f"cell ({r},{c}) has {len(content)} paragraphs")
            segs = segments(cell) if c > 1 else [(cell, None, False)]
            ops.append((content[0]["startIndex"], content[0]["endIndex"], segs, True))

    def rng(a, b):
        return {"startIndex": a, "endIndex": b, "tabId": tab_id}

    reqs = []
    for start, end, segs, in_cell in sorted(ops, key=lambda o: -o[0]):
        if end - 1 > start:  # keep the paragraph's newline and style
            reqs.append({"deleteContentRange": {"range": rng(start, end - 1)}})
        text = "".join(s[0] for s in segs)
        if not text:
            continue
        reqs.append({"insertText": {"location": {"index": start, "tabId": tab_id}, "text": text}})
        if in_cell:  # inserted text inherits the old first character's link or italic
            reqs.append({"updateTextStyle": {"range": rng(start, start + u16(text)), "textStyle": {},
                                             "fields": "link,italic,underline,foregroundColor"}})
        pos = start
        for t, url, italic in segs:
            n = u16(t)
            if url:
                reqs.append({"updateTextStyle": {"range": rng(pos, pos + n),
                                                 "textStyle": dict(LINK_STYLE, link={"url": url}),
                                                 "fields": "link,underline,foregroundColor"}})
            if italic:
                reqs.append({"updateTextStyle": {"range": rng(pos, pos + n),
                                                 "textStyle": {"italic": True}, "fields": "italic"}})
            pos += n
    return {"documentId": doc["documentId"], "requests": reqs,
            "writeControl": {"requiredRevisionId": doc["revisionId"]}}


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    doc = raw.get("content", raw)  # the Docs connector wraps documents.get in "content"
    json.dump(build(doc, *read_sheet(sys.argv[2])), sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
