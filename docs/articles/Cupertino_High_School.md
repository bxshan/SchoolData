# Cupertino High School — Wikipedia article (draft)

> Generated from NCES data using `docs/school_article_template.md`.
> Fields backed by the NCES record are filled. Fields **not** present in the source
> data are left as `{{PLACEHOLDER}}` and must be sourced (official website, district
> records, geocode) before publishing — do **not** invent these values.

```wikitext
{{Short description|Public high school in Cupertino, California}}
{{Use mdy dates|date=June 2026}}

{{Infobox school
| name                = Cupertino High School
| location            = 10100 Finch Avenue
| city                = Cupertino
| state               = California
| county              = Santa Clara County
| zipcode             = 95014
| country             = United States
| coordinates         = {{COORD}}                  <!-- geocode 10100 Finch Ave, Cupertino -->
| type                = Public high school
| established         = {{YEAR_ESTABLISHED}}       <!-- not in NCES data -->
| district            = Fremont Union High School District
| us_nces_district_id = 0614430
| us_nces_school_id   = 061443001695
| principal           = {{PRINCIPAL}}             <!-- not in NCES data -->
| grades              = 9–12
| enrollment          = 1,800
| enrollment_as_of    = {{NCES_REPORTING_YEAR}}
| ratio               = 22.9
| faculty             = 78.5 (FTE)
| language            = English
| athletics_conference= {{ATHLETICS_CONFERENCE}}  <!-- not in NCES data -->
| mascot              = {{MASCOT}}                 <!-- not in NCES data -->
| feeder_schools      = {{FEEDER_SCHOOLS}}        <!-- not in NCES data -->
| colors              = {{SCHOOL_COLORS}}         <!-- not in NCES data -->
| website             = {{OFFICIAL_URL}}          <!-- not in NCES data -->
}}

'''Cupertino High School''' is a public high school in [[Cupertino, California]],
United States. It is part of the [[Fremont Union High School District]] and serves
students in grades 9 through 12. As of the most recent
[[National Center for Education Statistics]] (NCES) reporting, the school enrolled
approximately 1,800 students, with about 78.5 full-time-equivalent teachers and a
student–teacher ratio of roughly 23 to 1.<ref name="nces" />

== History ==
{{Cupertino High School was established in {{YEAR_ESTABLISHED}}.}}<!-- founding details not in NCES data; source from school/district records -->

== References ==
{{Reflist}}

<ref name="nces">{{cite web |title=Cupertino High |url=https://nces.ed.gov/ccd/schoolsearch/school_detail.asp?ID=061443001695 |website=National Center for Education Statistics |publisher=U.S. Department of Education |access-date=June 27, 2026}}</ref>

== External links ==
* {{Official website|{{OFFICIAL_URL}}}}

[[Category:Public high schools in California]]
[[Category:High schools in Santa Clara County, California]]
[[Category:Fremont Union High School District]]
[[Category:California school stubs]]

{{California-school-stub}}
```

---

## Markdown mirror

> Same content as the wikitext above, rendered in plain Markdown for non-wiki use
> (README, internal docs, site preview). Placeholders carried over unchanged.

# Cupertino High School

**Cupertino High School** is a public high school in Cupertino, California, United
States. It is part of the Fremont Union High School District and serves students in
grades 9 through 12. As of the most recent National Center for Education Statistics
(NCES) reporting, the school enrolled approximately 1,800 students, with about 78.5
full-time-equivalent teachers and a student–teacher ratio of roughly 23 to 1.[^nces]

| | |
|---|---|
| **Location** | 10100 Finch Avenue, Cupertino, Santa Clara County, California 95014, United States |
| **Coordinates** | _{{COORD}}_ (geocode 10100 Finch Ave, Cupertino) |
| **Type** | Public high school |
| **Established** | _{{YEAR_ESTABLISHED}}_ (not in NCES data) |
| **School district** | Fremont Union High School District |
| **NCES District ID** | 0614430 |
| **NCES School ID** | 061443001695 |
| **Principal** | _{{PRINCIPAL}}_ (not in NCES data) |
| **Grades** | 9–12 |
| **Enrollment** | 1,800 (as of _{{NCES_REPORTING_YEAR}}_) |
| **Faculty (FTE)** | 78.5 |
| **Student–teacher ratio** | 22.9 |
| **Language** | English |
| **Athletics conference** | _{{ATHLETICS_CONFERENCE}}_ (not in NCES data) |
| **Mascot** | _{{MASCOT}}_ (not in NCES data) |
| **Feeder schools** | _{{FEEDER_SCHOOLS}}_ (not in NCES data) |
| **Colors** | _{{SCHOOL_COLORS}}_ (not in NCES data) |
| **Website** | _{{OFFICIAL_URL}}_ (not in NCES data) |

## History

Cupertino High School was established in _{{YEAR_ESTABLISHED}}_. _(Founding details
not in NCES data; source from school/district records.)_

[^nces]: "Cupertino High," National Center for Education Statistics, U.S. Department
of Education. <https://nces.ed.gov/ccd/schoolsearch/school_detail.asp?ID=061443001695>
Retrieved June 27, 2026.

---

## Fields still needed before publishing

These are **not** in the NCES row and must be sourced separately:

| Field | Where to get it |
|---|---|
| `established` (founding year) | School "About" page / district history |
| `principal` | Official school website |
| `mascot`, `colors` | Official school website / athletics page |
| `athletics_conference` | League website (likely a CCS / El Camino-type league) |
| `feeder_schools` | District attendance-boundary / feeder map |
| `website` | Official school URL |
| `coordinates` | Geocode `10100 Finch Ave, Cupertino, CA 95014` |
| `enrollment_as_of` | The reporting year of the NCES dataset used |

## Source data (NCES row)

```
public, California_06, 061443001695, Cupertino High, 09, 12, 10100 Finch Ave.,
Cupertino, CA, 95014, Santa Clara County, (408)366-7300, enrollment=1800,
FTE_teachers=78.54, ratio=22.92, Regular, state_school_id=CA-4369468-4331799,
nces_district=0614430, state_district=CA-4369468, Fremont Union High,
locale="City, Small", charter=No, status=Open
```
