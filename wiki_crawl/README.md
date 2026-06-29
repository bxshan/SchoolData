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
