# Author: Boxuan Shan + support from Claude Opus 4.8
#!/usr/bin/env python3
"""
Combine the public and private NCES masters into a single unified master CSV
covering all K-12 schools in the US.

Reads output_public_schools/public_schools_master.csv (from build_from_bulk.py,
or the search-tool scrape) and output_private_schools/private_schools_master.csv
(from download_schools.py --type private), then:
  1. Maps the shared fields of both sectors to a normalized common core,
  2. Preserves every remaining (sector-specific) column losslessly,
  3. Tags each row with a `sector` column and writes one master CSV.

parse_school_file() also lives here: the search tool's downloaded .xls files are
HTML tables with a banner/notes preamble, parsed with the stdlib HTML parser.

Usage:
    python combine_all_schools.py
"""

import csv
import logging
from html.parser import HTMLParser
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Where the per-state .xls files live and where to write the unified output —
# resolved next to this script, so it runs from any working directory.
HERE = Path(__file__).resolve().parent
PUBLIC_MASTER = HERE / "output_public_schools" / "public_schools_master.csv"
PRIVATE_MASTER = HERE / "output_private_schools" / "private_schools_master.csv"
OUTPUT_DIR = HERE / "output_all_schools"
OUTPUT_FILE = "all_schools_master.csv"

# Normalized common-core columns, in output order.
CORE_COLUMNS = [
    "school_id", "school_name", "low_grade", "high_grade", "address",
    "city", "state", "zip", "county", "phone", "total_students",
    "teachers", "student_teacher_ratio", "type",
]

# Map each sector's native header -> normalized core column.
# NOTE: low_grade/high_grade encodings DIFFER by sector and are kept raw:
#   public  -> 'PK', 'KG', '01'..'12'
#   private -> PSS numeric grade codes (e.g. '2'..'17')
# No cross-sector grade conversion is invented here.
PUBLIC_CORE_MAP = {
    "NCES School ID": "school_id",
    "School Name": "school_name",
    "Low Grade": "low_grade",
    "High Grade": "high_grade",
    "Street Address": "address",
    "City": "city",
    "State": "state",
    "ZIP": "zip",
    "County Name": "county",
    "Phone": "phone",
    "Students": "total_students",
    "Teachers": "teachers",
    "Student Teacher Ratio": "student_teacher_ratio",
    "Type": "type",
}
PRIVATE_CORE_MAP = {
    "PSS_SCHOOL_ID": "school_id",
    "PSS_INST": "school_name",
    "LoGrade": "low_grade",
    "HiGrade": "high_grade",
    "PSS_ADDRESS": "address",
    "PSS_CITY": "city",
    "PSS_STABB": "state",
    "PSS_ZIP5": "zip",
    "PSS_COUNTY_NAME": "county",
    "PSS_PHONE": "phone",
    "PSS_ENROLL_T": "total_students",
    "PSS_FTE_TEACH": "teachers",
    "PSS_STDTCH_RT": "student_teacher_ratio",
    "PSS_TYPE": "type",
}


class _TableParser(HTMLParser):
    """Collect every <tr> as a list of cell strings."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            if self._row is not None:
                self._row.append("".join(self._cell).strip())
            self._cell = []

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def parse_school_file(path, id_marker):
    """Return (header, list_of_record_dicts) from one NCES .xls (HTML) file.

    `id_marker` is the ID column name used to locate the real header row
    (everything above it is the NCES banner/notes preamble).
    """
    parser = _TableParser()
    with open(path, encoding="utf-8", errors="replace") as f:
        parser.feed(f.read())

    header_idx = None
    for i, row in enumerate(parser.rows):
        if any(id_marker == (cell or "").strip() for cell in row):
            header_idx = i
            break
    if header_idx is None:
        logger.warning("  %s: no header row found (marker %r)", path.name, id_marker)
        return None, []

    # Strip the trailing "*" footnote marker NCES adds to some public columns
    # (it varies by export vintage) so core-field matching stays stable.
    header = [c.strip().rstrip("*").strip() for c in parser.rows[header_idx]]
    id_col = header[0]
    records = []
    for row in parser.rows[header_idx + 1:]:
        rec = dict(zip(header, row))
        # Drop blank/footer rows: a real school row has a non-empty ID.
        if rec.get(id_col, "").strip():
            records.append(rec)
    return header, records


def _normalize(records, header, core_map, sector, source_file):
    """Map one sector's records into normalized-core + lossless-extras dicts."""
    extras = [h for h in header if h not in core_map]
    out = []
    for rec in records:
        norm = {"sector": sector, "source_file": source_file}
        for native, core in core_map.items():
            norm[core] = rec.get(native, "")
        for col in extras:
            norm[col] = rec.get(col, "")
        out.append(norm)
    return out, extras


def _load_sector(master, core_map, sector):
    """Read and normalize one sector's master CSV."""
    if not master.exists():
        logger.warning("%s: %s not found", sector.upper(), master)
        return [], []
    with open(master, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        records = [r for r in reader if (r.get(reader.fieldnames[0]) or "").strip()]
    rows, extras = _normalize(records, reader.fieldnames, core_map, sector, master.stem)
    logger.info("%s: %d schools from %s", sector.upper(), len(rows), master.name)
    return rows, extras


def build_unified(output_dir=OUTPUT_DIR, output_file=OUTPUT_FILE):
    """Build the unified all-K-12-schools master CSV from downloaded files."""
    public_rows, public_extras = _load_sector(PUBLIC_MASTER, PUBLIC_CORE_MAP, "public")
    private_rows, private_extras = _load_sector(PRIVATE_MASTER, PRIVATE_CORE_MAP, "private")

    if not public_rows and not private_rows:
        logger.error("No school data found in either download directory.")
        return False

    columns = ["sector", "source_file"] + CORE_COLUMNS + public_extras + private_extras

    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / output_file
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(public_rows)
        writer.writerows(private_rows)

    total = len(public_rows) + len(private_rows)
    logger.info("=" * 70)
    logger.info("SUCCESS")
    logger.info("=" * 70)
    logger.info("Output: %s", output_path.absolute())
    logger.info("Public schools:  %6d", len(public_rows))
    logger.info("Private schools: %6d", len(private_rows))
    logger.info("Total schools:   %6d", total)
    logger.info("Columns:         %6d", len(columns))
    return True


if __name__ == "__main__":
    build_unified()
