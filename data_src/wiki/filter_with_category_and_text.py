# Author: Boxuan Shan + support from Claude Sonnet 4.5
#!/usr/bin/env python3
"""
Advanced filter using parent category and optional page text verification.
"""

import json
import time
import requests
from typing import Dict


def is_valid_category(category: str) -> bool:
    """Check if parent category is valid (not an exclusion category)."""
    category_lower = category.lower()

    # Exclude categories about violence/tragedy
    violence_cats = ["shooting", "massacre", "killing", "violence", "attack"]
    if any(keyword in category_lower for keyword in violence_cats):
        return False

    # Exclude categories about media
    media_cats = ["films", "movies", "television", "video games", "albums",
                  "magazines", "newspapers", "publications", "episode",
                  "redirects to", "series"]
    if any(keyword in category_lower for keyword in media_cats):
        return False

    # Exclude categories about sports organizations/awards
    sports_cats = ["athletic association", "athletic conference", "championship",
                  "tournament", "all-america", "all-usa", "player of the year",
                  "high school sports", "scholastic wrestling", "high school football",
                  "high school basketball", "high school baseball", "season", "league",
                  "activities association"]
    if any(keyword in category_lower for keyword in sports_cats):
        return False

    # Exclude categories about districts/systems
    district_cats = ["school district", "school board", "school system", "school union",
                    "regional school unit", "school administrative district", "school department"]
    if any(keyword in category_lower for keyword in district_cats):
        return False

    # Exclude categories about non-high schools
    non_high_school_cats = ["elementary schools", "primary schools", "middle schools",
                           "junior high schools", "grade schools", "k–8 schools", "k-8 schools"]
    if any(keyword in category_lower for keyword in non_high_school_cats):
        return False

    # Exclude categories about historic buildings and defunct schools
    historic_defunct_cats = ["school buildings on the national register of historic places",
                            "defunct"]
    if any(keyword in category_lower for keyword in historic_defunct_cats):
        return False

    # Exclude categories about universities and colleges
    university_college_cats = ["university of", "colleges and schools", "university campus",
                              "university stubs", "universities and colleges"]
    if any(keyword in category_lower for keyword in university_college_cats):
        return False

    # Exclude categories about software, games, and other tech
    tech_cats = ["software", "video games", "ios games", "android games", "mobile games",
                "computer games", "educational software"]
    if any(keyword in category_lower for keyword in tech_cats):
        return False

    # Exclude categories about people (alumni, etc.)
    people_cats = ["alumni", "people"]
    if any(keyword in category_lower for keyword in people_cats):
        return False

    # Exclude miscellaneous non-school categories
    misc_cats = ["list of", "lists of"]
    if any(keyword in category_lower for keyword in misc_cats):
        return False

    # Generic school stub categories should be handled more strictly
    # These might contain school districts mixed with schools
    # This will be checked in the title filter

    return True


def is_high_school_article_basic(title: str) -> bool:
    """Basic title-based filtering (same as before)."""
    if title.startswith("Category:") or title.startswith("List of") or title.startswith("Template:"):
        return False

    # Exclude violence/tragedy-related pages
    violence_keywords = [
        "shooting", "massacre", "killing", "murder", "attack", "bombing",
        "violence", "incident", "tragedy", "death"
    ]
    if any(keyword in title.lower() for keyword in violence_keywords):
        return False

    # Exclude media-related pages
    media_keywords = [
        " (film)", " (movie)", " (television", " (tv ", " (series)",
        " (show)", " (musical)", " (play)", " (anime)", " (manga)",
        " (video game)", " (album)", " (song)", " (soundtrack)",
        " magazine", " newspaper", " publication"
    ]
    if any(keyword in title.lower() for keyword in media_keywords):
        return False

    # Exclude sports awards
    sports_awards_keywords = [
        "all-usa", "all-america", "all-american", "all usa", "all america",
        "player of the year", "coach of the year", "team of the year",
        "defensive player", "offensive player", "athlete of the year",
        "mr. basketball", "ms. basketball", "mr. football", "gatorade player",
        "mcdonald's all-american", "parade all-american"
    ]
    if any(keyword in title.lower() for keyword in sports_awards_keywords):
        return False

    # Exclude sports organizations and sports-related pages
    sports_org_keywords = [
        "athletic association", "athletic conference", "school league",
        "championship", "tournament", "all-star", "hall of fame",
        "sports association", "activities association", "school association",
        " conference-", "athletic conferences:", " conference (", " league (",
        " (wrestling)", " (football)", " (basketball)", " (baseball)",
        " (soccer)", " (softball)", " (volleyball)", " (track)", " (swimming)"
    ]
    if any(keyword in title.lower() for keyword in sports_org_keywords):
        return False

    # Exclude other non-school pages
    other_exclusions = [
        "school district", "school board", "board of education",
        "education department", "school system", "school division",
        "unified school", " isd", " usd", "school union",
        "regional school unit", "school administrative district",
        "school department", "schoolhouse", "state board for",
        "facilities board", "school commission", "historic district",
        "school corporation", "schools corporation", "history of ", "alumni field",
        "network of", "association of", "athletic league",
        "charter schools association", "district schools", "(historic)",
        "high schools district"
    ]
    if any(keyword in title.lower() for keyword in other_exclusions):
        return False

    # Exclude administrative boards (but keep "Boarding School")
    if " board" in title.lower() and "boarding school" not in title.lower():
        # Check if it ends with "Board" (likely an administrative entity)
        if title.endswith(" Board") or title.endswith(" Board)"):
            return False

    # Exclude school districts (common patterns)
    # These typically have "City Schools", "County Schools", "Public Schools", etc.
    # May have state/location disambiguators at the end like "(Alabama)"
    district_patterns = [
        " city schools", " county schools", " public schools", " area schools",
        " union schools", " township schools", " community schools", " central schools",
        " regional schools"
    ]
    # Check if pattern exists in title (may be followed by disambiguation)
    for pattern in district_patterns:
        if pattern in title.lower():
            # Make sure it's not a high school name containing these words
            # e.g., "X County High School" vs "X County Schools"
            if "high school" not in title.lower():
                return False

    # Exclude non-high schools (elementary, middle, etc.)
    non_high_schools = [
        "elementary school", "primary school", "middle school",
        "junior high school", "grade school", "grammar school",
        "k-8 school", "k–8 school", "intermediate school"
    ]
    for keyword in non_high_schools:
        if keyword in title.lower():
            # Allow if it's a combined school, e.g., "Middle/High School"
            # But "Intermediate School" by itself is usually not a high school
            if "high school" not in title.lower() and "secondary school" not in title.lower():
                return False

    # Exclude physical facilities
    facility_keywords = [
        "school gymnasium", "school auditorium", "school stadium",
        "school building", "school site", "schoolhouse"
    ]
    if any(keyword in title.lower() for keyword in facility_keywords):
        return False

    # Exclude universities and colleges (but keep "College Preparatory" and "University High School")
    title_lower = title.lower()

    # Check for university departments/schools
    if "university of" in title_lower and "school of" in title_lower:
        return False

    if "school of" in title_lower and ("university" in title_lower or "college" in title_lower):
        # Allow if it contains "high school" (like "School of High School Studies")
        if "high school" not in title_lower:
            return False

    # Exclude standalone colleges (but keep "College Preparatory")
    if title.endswith(" College") or ", College" in title:
        return False

    # Exclude graduate schools, law schools, medical schools, etc.
    university_school_types = [
        "graduate school", "law school", "medical school", "business school",
        "dental school", "nursing school", "divinity school", "library school"
    ]
    if any(keyword in title_lower for keyword in university_school_types):
        return False

    # Exclude software, games, and people with "school" in title
    non_school_patterns = [
        "schoolboy", "schoolgirl", "school stream", "schooltool", "schoolwork (",
        " (software)", " (app)", " (game)", " (video game)"
    ]
    if any(keyword in title_lower for keyword in non_school_patterns):
        return False

    high_school_keywords = [
        "High School", "high school", "Secondary School",
        "Preparatory School", "Prep School", "School"
    ]

    return any(keyword in title for keyword in high_school_keywords)


def get_page_intro(page_id: int, session: requests.Session) -> str:
    """Fetch the introduction text of a Wikipedia page."""
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "pageids": page_id,
        "prop": "extracts",
        "exintro": True,
        "explaintext": True,
        "format": "json"
    }

    try:
        response = session.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()

        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id), {})
            return page_data.get("extract", "")[:500]

    except requests.exceptions.RequestException:
        pass

    return ""


def is_school_from_text(intro_text: str) -> bool:
    """Verify if the page is actually a school based on intro text."""
    if not intro_text:
        return True  # If we can't fetch text, don't filter out

    intro_lower = intro_text.lower()

    # Strong indicators this is NOT a school
    non_school_patterns = [
        "is a list of", "is an annual award", "is an award given",
        "was a shooting", "was a massacre", "was an attack",
        "is a film", "is a movie", "is a television",
        "is a competition", "is a tournament", "is a championship",
        "is an athletic association", "is a sports league",
        "is a school district", "is an independent school district",
        "is a historic school building", "is a historic building",
        "is a building", "is a station", "is a neighborhood",
        "is a census-designated place", "is an unincorporated community",
        "is a township", "is a city", "is a town", "is a village",
        "is a former high school", "was a high school", "was a public high school",
        "was a secondary school", "was a private school", "defunct high school",
        "closed in", "refer to:", "refers to:", "may refer to:",
        "is a sports team", "is a football team", "is a basketball team"
    ]

    if any(pattern in intro_lower for pattern in non_school_patterns):
        return False

    # Strong indicators this IS a school
    school_patterns = [
        "is a high school", "is a secondary school", "is a public school",
        "is a private school", "is a preparatory school", "is a charter school",
        "is an independent school", "high school located in",
        "secondary school located in", "serves grades"
    ]

    if any(pattern in intro_lower for pattern in school_patterns):
        return True

    return True  # Default: keep if unsure


def filter_data(input_file: str, output_file: str, verify_with_text: bool = False):
    """Filter dataset using category and optionally page text."""
    print(f"Reading {input_file}...")

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"Original dataset: {len(data)} entries")
    print(f"Text verification: {'ENABLED (slower but more accurate)' if verify_with_text else 'DISABLED (faster)'}")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'HighSchoolFilter/1.0 (Educational/Research Purpose)'
    })

    valid_schools = []
    removed_entries = {
        'title': [],
        'category': [],
        'text': []
    }

    for i, entry in enumerate(data, 1):
        if i % 100 == 0:
            print(f"  Processing {i}/{len(data)}...")

        title = entry.get('title', '')
        category = entry.get('direct_parent_category', '')
        page_id = entry.get('page_id')

        # Filter 1: Basic title check
        if not is_high_school_article_basic(title):
            removed_entries['title'].append(title)
            continue

        # Filter 2: Category check
        if not is_valid_category(category):
            removed_entries['category'].append(title)
            continue

        # Filter 3: Optional text verification
        if verify_with_text and page_id:
            intro = get_page_intro(page_id, session)
            if not is_school_from_text(intro):
                removed_entries['text'].append(title)
                time.sleep(0.1)  # Rate limiting
                continue
            time.sleep(0.1)  # Rate limiting

        valid_schools.append(entry)

    total_removed = len(data) - len(valid_schools)
    print(f"\nFiltered dataset: {len(valid_schools)} valid schools")
    print(f"Removed: {total_removed} entries")
    print(f"  - Filtered by title: {len(removed_entries['title'])}")
    print(f"  - Filtered by category: {len(removed_entries['category'])}")
    print(f"  - Filtered by text: {len(removed_entries['text'])}")

    # Show examples
    if removed_entries['category']:
        print(f"\nExamples removed by category check ({len(removed_entries['category'])} total):")
        for title in removed_entries['category'][:10]:
            cat = next((e['direct_parent_category'] for e in data if e['title'] == title), '')
            print(f"  - {title}")
            print(f"    Category: {cat}")

    if removed_entries['text']:
        print(f"\nExamples removed by text check ({len(removed_entries['text'])} total):")
        for title in removed_entries['text'][:5]:
            print(f"  - {title}")

    # Save filtered data
    print(f"\nSaving filtered data to {output_file}...")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(valid_schools, f, indent=2, ensure_ascii=False)

    # Save TXT
    txt_file = output_file.replace('.json', '.txt')
    with open(txt_file, 'w', encoding='utf-8') as f:
        for school in valid_schools:
            f.write(f"{school['title']}\n")

    # Save CSV
    csv_file = output_file.replace('.json', '.csv')
    with open(csv_file, 'w', encoding='utf-8') as f:
        f.write("Title,Page ID,URL,State,School Type,Direct Parent Category\n")
        for school in valid_schools:
            title = school['title'].replace('"', '""')
            url = school['url']
            state = (school.get('state') or "").replace('"', '""')
            school_type = school.get('school_type', 'unknown')
            category = school.get('direct_parent_category', '').replace('"', '""')
            f.write(f'"{title}",{school["page_id"]},"{url}","{state}","{school_type}","{category}"\n')

    # Save summary
    state_counts = {}
    type_counts = {}
    for school in valid_schools:
        state = school.get('state') or "Unknown/General"
        state_counts[state] = state_counts.get(state, 0) + 1
        school_type = school.get('school_type', 'unknown')
        type_counts[school_type] = type_counts.get(school_type, 0) + 1

    summary = {
        "total_schools": len(valid_schools),
        "schools_by_type": dict(sorted(type_counts.items())),
        "schools_by_state": dict(sorted(state_counts.items())),
        "removed_entries": {
            "total": total_removed,
            "by_title": len(removed_entries['title']),
            "by_category": len(removed_entries['category']),
            "by_text": len(removed_entries['text'])
        }
    }

    summary_file = output_file.replace('.json', '_summary.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Save removed entries details
    removed_file = output_file.replace('.json', '_removed.json')
    with open(removed_file, 'w', encoding='utf-8') as f:
        json.dump(removed_entries, f, indent=2, ensure_ascii=False)

    print(f"\nSaved files:")
    print(f"  - {output_file}")
    print(f"  - {txt_file}")
    print(f"  - {csv_file}")
    print(f"  - {summary_file}")
    print(f"  - {removed_file}")
    print("\nFiltering complete!")


if __name__ == "__main__":
    import os
    import argparse

    parser = argparse.ArgumentParser(description='Filter Wikipedia high schools data')
    parser.add_argument('--verify-text', action='store_true',
                       help='Fetch and verify page intro text (slower but more accurate)')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))

    filter_data(
        os.path.join(script_dir, "us_high_schools_bfs_v2.json"),
        os.path.join(script_dir, "us_high_schools_filtered_v2.json"),
        verify_with_text=args.verify_text
    )
