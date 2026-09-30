# Author: Boxuan Shan, with support from Claude (Anthropic)
"""US states, DC and territories — the one copy every pipeline script uses.

NCES covers the 50 states, DC and five territories (AS, GU, MP, PR, VI).
"""

# USPS code -> (name, 2-digit FIPS)
_STATES = {
    "AL": ("Alabama", "01"), "AK": ("Alaska", "02"), "AZ": ("Arizona", "04"),
    "AR": ("Arkansas", "05"), "CA": ("California", "06"), "CO": ("Colorado", "08"),
    "CT": ("Connecticut", "09"), "DE": ("Delaware", "10"),
    "DC": ("District of Columbia", "11"), "FL": ("Florida", "12"),
    "GA": ("Georgia", "13"), "HI": ("Hawaii", "15"), "ID": ("Idaho", "16"),
    "IL": ("Illinois", "17"), "IN": ("Indiana", "18"), "IA": ("Iowa", "19"),
    "KS": ("Kansas", "20"), "KY": ("Kentucky", "21"), "LA": ("Louisiana", "22"),
    "ME": ("Maine", "23"), "MD": ("Maryland", "24"), "MA": ("Massachusetts", "25"),
    "MI": ("Michigan", "26"), "MN": ("Minnesota", "27"), "MS": ("Mississippi", "28"),
    "MO": ("Missouri", "29"), "MT": ("Montana", "30"), "NE": ("Nebraska", "31"),
    "NV": ("Nevada", "32"), "NH": ("New Hampshire", "33"), "NJ": ("New Jersey", "34"),
    "NM": ("New Mexico", "35"), "NY": ("New York", "36"),
    "NC": ("North Carolina", "37"), "ND": ("North Dakota", "38"), "OH": ("Ohio", "39"),
    "OK": ("Oklahoma", "40"), "OR": ("Oregon", "41"), "PA": ("Pennsylvania", "42"),
    "RI": ("Rhode Island", "44"), "SC": ("South Carolina", "45"),
    "SD": ("South Dakota", "46"), "TN": ("Tennessee", "47"), "TX": ("Texas", "48"),
    "UT": ("Utah", "49"), "VT": ("Vermont", "50"), "VA": ("Virginia", "51"),
    "WA": ("Washington", "53"), "WV": ("West Virginia", "54"),
    "WI": ("Wisconsin", "55"), "WY": ("Wyoming", "56"),
    "AS": ("American Samoa", "60"), "GU": ("Guam", "66"),
    "MP": ("Northern Mariana Islands", "69"), "PR": ("Puerto Rico", "72"),
    "VI": ("United States Virgin Islands", "78"),
}

USPS_TO_NAME = {code: name for code, (name, _) in _STATES.items()}
USPS_TO_FIPS = {code: fips for code, (_, fips) in _STATES.items()}

# Lower-case name (and common variants) -> USPS code.
NAME_TO_USPS = {name.lower(): code for code, name in USPS_TO_NAME.items()}
NAME_TO_USPS.update({"virgin islands": "VI", "u.s. virgin islands": "VI",
                     "us virgin islands": "VI", "washington, d.c.": "DC",
                     "washington d.c.": "DC"})

# Names as they read mid-sentence ("... in the District of Columbia").
_NEEDS_THE = {"DC", "MP", "VI"}
PROSE_NAME = {code: ("the " + name if code in _NEEDS_THE else name)
              for code, name in USPS_TO_NAME.items()}
PROSE_NAME["VI"] = "the U.S. Virgin Islands"

# Every spelling that identifies a state inside free text, longest first so
# "West Virginia" wins over "Virginia" and "Arkansas" over "Kansas".
TEXT_NAMES = sorted(set(USPS_TO_NAME.values())
                    | {"U.S. Virgin Islands", "Washington, D.C.", "Washington D.C."},
                    key=len, reverse=True)


def state_code(s):
    """'CA' / 'California' / 'california' -> 'CA'; '' when unknown."""
    s = (s or "").strip()
    if len(s) == 2 and s.upper() in USPS_TO_NAME:
        return s.upper()
    return NAME_TO_USPS.get(s.lower(), "")


def state_in_text(text):
    """Full state name found in free text (longest match wins), or ''."""
    for name in TEXT_NAMES:
        if name in (text or ""):
            return USPS_TO_NAME[state_code(name)]
    return ""
