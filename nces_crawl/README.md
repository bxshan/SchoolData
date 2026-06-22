# NCES School Data Scraper

This project downloads and combines school data from the National Center for Education Statistics (NCES).

## Project Structure

- `download_schools.py` - Main scraper for public and private schools
- `combine_all_schools.py` - Combines downloaded files into the unified all-K-12 master CSV
- `public_school_downloads/` - Downloaded public school Excel files (56 states/territories)
- `private_school_downloads/` - Downloaded private school Excel files (51 states)
- `public_school_output/` - Master CSV for public schools
- `private_school_output/` - Master CSV for private schools

## Coding Conventions

**IMPORTANT**: All Python files in this project must include the following as the first line:

```python
# Author: Boxuan Shan + support from Claude Sonnet 4.5
```

This authorship line must be present before the shebang (`#!/usr/bin/env python3`) and module docstring.

## Data Sources

- **Public Schools**: NCES Common Core of Data (CCD) - 2023-24 school year
- **Private Schools**: NCES Private School Survey (PSS) - 2023-24 school year

## Usage

### Download Schools

Download public schools:
```bash
python3 download_schools.py --type public
```

Download private schools:
```bash
python3 download_schools.py --type private
```

Download both and build the unified all-K-12 master in one run:
```bash
python3 download_schools.py --type all
```

### Combine into Unified Master (All K-12 Schools)

Merge already-downloaded public and private files into a single master CSV
covering all K-12 schools, with a `sector` column. Public and private fields
are normalized to a shared common core; all sector-specific columns are
preserved (the other sector's columns are blank per row). Uses only the Python
standard library (no `lxml`/`pandas` required):
```bash
python3 combine_all_schools.py
```

**Note:** `low_grade`/`high_grade` keep their native encodings — public uses
`PK`/`KG`/`01`–`12`; private uses PSS numeric grade codes. No cross-sector
grade conversion is applied.

## Output Files

### Public Schools Master CSV
- **Location**: `public_school_output/public_schools_master.csv`
- **Schools**: 100,771 schools
- **Size**: 26 MB
- **Columns**: 27 (26 data columns + source_file)
- **Coverage**: All 50 states + DC + 5 territories

### Private Schools Master CSV
- **Location**: `private_school_output/private_schools_master.csv`
- **Schools**: 22,756 schools
- **Size**: 6.1 MB
- **Columns**: 72 (71 data columns + source_file)
- **Coverage**: All 50 states + DC

### Unified All-K-12 Master CSV
- **Location**: `all_schools_output/all_schools_master.csv`
- **Schools**: ~122,936 (100,435 public + 22,501 private)
- **Size**: ~40 MB
- **Columns**: 85 (`sector` + `source_file` + 14 normalized core + sector-specific columns)
- **Coverage**: All 50 states + DC + 5 territories (public), all 50 states + DC (private)

## Technical Notes

### File Format
Downloaded files are HTML tables saved as `.xls` files (Excel-compatible). They are parsed using pandas `read_html()` function with the `lxml` parser.

### Timeout Fix for Large States
California (10,347 schools) and other large states required timeout adjustments:
- Popup wait: 2s → 10s
- Excel generation wait: 2s → 30s
- Download completion: 18s → 60s

### Dependencies
```bash
pip install pandas lxml selenium webdriver-manager
```

## Data Columns

### Public Schools (26 columns)
- NCES School ID, State School ID
- NCES District ID, State District ID
- School Name, District Name
- Low Grade, High Grade
- Address, City, State, ZIP
- County Name, Phone
- Locale Code, Locale Description
- Charter Status
- Students, Teachers, Student-Teacher Ratio
- Free Lunch, Reduced Lunch, Directly Certified
- Type, Status

### Private Schools (71 columns)
- School ID, Institution Name
- Grades, Address, City, State, ZIP
- County, Phone
- Enrollment by grade (UG, PK, K-12)
- Total enrollment
- Demographics (race/ethnicity percentages)
- FTE Teachers, Student-Teacher Ratio
- School characteristics (library, days, hours)
- Religious affiliation, Orientation
- Coed status, Type, Level
- Associations (15 fields)

## Author

Boxuan Shan + support from Claude Sonnet 4.5
