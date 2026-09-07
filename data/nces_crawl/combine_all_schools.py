# Author: Boxuan Shan + support from Claude Opus 4.8
#!/usr/bin/env python3
"""
Combine downloaded NCES public AND private school files into a single
unified master CSV covering all K-12 schools in the US.

The downloaded .xls files are actually HTML tables with a 5-6 row banner/notes
preamble before the real header row. This script:
  1. Parses each file (stdlib HTML parser - no lxml/pandas required),
  2. Strips the preamble and promotes the real header row,
  3. Maps the shared fields of both sectors to a normalized common core,
  4. Preserves every remaining (sector-specific) column losslessly,
  5. Tags each row with a `sector` column and writes one master CSV.

Usage:
    python combine_all_schools.py
"""

import csv
import glob
import logging
from html.parser import HTMLParser
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Where the per-state .xls files live and where to write the unified output.
PUBLIC_DOWNLOAD_DIR = Path("public_school_downloads")
PRIVATE_DOWNLOAD_DIR = Path("private_school_downloads")
OUTPUT_DIR = Path("output_all_schools")
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


def _load_sector(download_dir, id_marker, core_map, sector):
    """Parse and normalize every .xls in a sector's download directory."""
    files = sorted(glob.glob(str(download_dir / "*.xls")))
    logger.info("%s: found %d files in %s", sector.upper(), len(files), download_dir)
    rows, extras_order = [], []
    for fp in files:
        path = Path(fp)
        header, records = parse_school_file(path, id_marker)
        if not records:
            logger.warning("  %s: 0 schools", path.name)
            continue
        norm, extras = _normalize(records, header, core_map, sector, path.stem)
        if not extras_order:
            extras_order = extras
        rows.extend(norm)
        logger.info("  %s: %d schools", path.name, len(records))
    return rows, extras_order


def build_unified(output_dir=OUTPUT_DIR, output_file=OUTPUT_FILE):
    """Build the unified all-K-12-schools master CSV from downloaded files."""
    public_rows, public_extras = _load_sector(
        PUBLIC_DOWNLOAD_DIR, "NCES School ID", PUBLIC_CORE_MAP, "public"
    )
    private_rows, private_extras = _load_sector(
        PRIVATE_DOWNLOAD_DIR, "PSS_SCHOOL_ID", PRIVATE_CORE_MAP, "private"
    )

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
