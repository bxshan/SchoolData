# Wikipedia School Article Template

Derived from [Kennedy Middle School (Cupertino, California)](https://en.wikipedia.org/wiki/Kennedy_Middle_School_(Cupertino,_California)).
Use this as a skeleton for other K–12 school articles. Replace every `{{PLACEHOLDER}}`
and delete any field/section that does not apply. Square-bracket notes `[…]` are
guidance and must be removed from the final article.

---

## 1. Title convention

```
{{SCHOOL_NAME}} ({{CITY}}, {{STATE}})
```

- Add the `({{CITY}}, {{STATE}})` disambiguation parenthetical **only** when the
  plain school name collides with another article (very common — many "Kennedy",
  "Lincoln", "Washington" schools exist).
- If the name is globally unique, use just `{{SCHOOL_NAME}}`.

---

## 2. Wikitext skeleton

```wikitext
{{Short description|{{SCHOOL_TYPE}} in {{CITY}}, {{STATE}}}}
{{Use mdy dates|date={{MONTH YEAR}}}}

{{Infobox school
| name                = {{FULL_SCHOOL_NAME}}
| former_name         = {{FORMER_NAME}}            <!-- omit if never renamed -->
| location            = {{STREET_ADDRESS}}
| city                = {{CITY}}
| state               = {{STATE}}
| county              = {{COUNTY}}
| zipcode             = {{ZIP}}
| country             = United States
| coordinates         = {{COORD}}                  <!-- {{Coord|LAT|LON|type:edu_region:US|display=inline,title}} -->
| type                = {{SCHOOL_TYPE}}            <!-- e.g. Public middle school -->
| established         = {{YEAR_ESTABLISHED}}
| district            = {{SCHOOL_DISTRICT}}
| ceeb                =                            <!-- optional -->
| us_nces_district_id = {{NCES_DISTRICT_ID}}
| us_nces_school_id   = {{NCES_SCHOOL_ID}}
| principal           = {{PRINCIPAL}}
| grades              = {{GRADE_RANGE}}            <!-- e.g. 6–8, K–5, 9–12 -->
| enrollment          = {{ENROLLMENT}}
| enrollment_as_of    = {{SCHOOL_YEAR}}            <!-- e.g. 2023–24 -->
| language            = English
| athletics_conference= {{ATHLETICS_CONFERENCE}}  <!-- omit if none -->
| mascot              = {{MASCOT}}
| feeder_to           = {{FEEDER_HIGH_SCHOOL}}     <!-- for elementary/middle -->
| feeder_schools      = {{FEEDER_SCHOOLS}}         <!-- for high schools -->
| colors              = {{SCHOOL_COLORS}}
| website             = {{OFFICIAL_URL}}
}}

'''{{FULL_SCHOOL_NAME}}''' is a {{SCHOOL_TYPE}} in [[{{CITY}}, {{STATE}}]],
United States. {{ONE-SENTENCE_DISTINGUISHING_FACT}}. It is part of the
[[{{SCHOOL_DISTRICT}}]]{{DISTRICT_CONTEXT}}. As of the {{SCHOOL_YEAR}} school
year, it enrolled {{ENROLLMENT}} students.{{cite}}

[Optional lead sentences — include only if independently sourced:]
[- Notable rankings, e.g. "ranked Nth best {{STATE}} {{LEVEL}} by U.S. News".]
[- Awards, e.g. National Blue Ribbon School ({{YEAR}}); {{STATE}} Distinguished School ({{YEAR}}).]

== History ==
{{SCHOOL_NAME}} was founded in {{YEAR_ESTABLISHED}}{{founding_detail}}.{{cite}}
[Chronological prose: original name, name changes with dates, grade-level
reconfigurations, relocations, major expansions. One sourced fact per sentence.]

== Academics ==                <!-- optional; include only if sourced -->
[Programs, curriculum focus, test-score recognition, accreditation.]

== Athletics ==               <!-- optional -->
[Conference, notable teams/championships.]

== Notable alumni ==          <!-- optional; each entry needs a citation -->
* [[{{ALUMNUS}}]] – {{DESCRIPTION}}{{cite}}

== References ==
{{Reflist}}

== External links ==
* {{Official website|{{OFFICIAL_URL}}}}

{{coord|LAT|LON|display=title}}   <!-- if not in infobox -->

[[Category:Public {{LEVEL}} schools in {{STATE}}]]
[[Category:Educational institutions established in {{YEAR_ESTABLISHED}}]]
[[Category:{{YEAR_ESTABLISHED}} establishments in {{STATE}}]]
[[Category:{{LEVEL}} schools in {{COUNTY}}, {{STATE}}]]
[[Category:{{STATE}} school stubs]]   <!-- only while a stub -->

{{{{STATE}}-school-stub}}             <!-- stub template; remove once expanded -->
```

---

## 3. Field sourcing guide (where each value comes from)

| Field | Primary source |
|---|---|
| Location, principal, grades, mascot, colors, website | Official school website |
| NCES district/school IDs, enrollment, school type | NCES (nces.ed.gov) — matches this project's crawl data |
| Established year, former names, history | School "About" page, district records, local news |
| Coordinates | Geocode the street address |
| Rankings | U.S. News & World Report school directory |
| Awards | National Blue Ribbon Schools DB; state Dept. of Education |
| Athletics conference | League/conference website |

---

## 4. Citation format

Numbered footnotes via `<ref>…</ref>` rendered by `{{Reflist}}`. Prefer named refs
for reuse:

```wikitext
<ref name="nces">{{cite web |title={{PAGE_TITLE}} |url={{URL}} |website={{SITE}} |access-date={{DATE}}}}</ref>
```

Each citation should carry: source/organization, page title (in quotes), URL, and
retrieval date. Reuse with `<ref name="nces" />`.

---

## 5. `{{LEVEL}}` value reference

| Grade range | `{{LEVEL}}` | Typical `{{SCHOOL_TYPE}}` |
|---|---|---|
| K–5 / K–6 | elementary | Public elementary school |
| 6–8 / 7–8 | middle | Public middle school |
| 9–12 | high | Public high school |
| K–8 / K–12 | — | Public school (use full grade range) |

---

## 6. Notes / pitfalls

- A new article with only a lead + History is a **stub** — keep the stub template
  and `{{STATE}} school stubs` category until it has multiple developed sections.
- Don't state unsourced rankings/awards; tag with `{{citation needed}}` if claimed
  but unverified, or omit.
- `former_name` / `feeder_*` / `athletics_conference` are optional — delete unused
  infobox lines rather than leaving them blank.
- Keep `enrollment` and `enrollment_as_of` in sync, and refresh both together.
