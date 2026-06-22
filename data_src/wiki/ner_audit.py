import json
import random
import requests
import spacy
from spacy import displacy
import os

def main():
    print("Loading spaCy model 'en_core_web_sm'...")
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        print("Model not found. Please run: python -m spacy download en_core_web_sm")
        return

    TARGET_LABELS = ["ORG", "GPE", "NORP", "PERSON"]

    json_path = "us_high_schools_bfs_v2.json"
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return

    print("Loading high schools list...")
    with open(json_path, "r", encoding="utf-8") as f:
        high_schools = json.load(f)

    print(f"Total schools loaded: {len(high_schools)}")
    
    # Sample 50 articles
    random.seed(42) # For reproducibility in case user wants to run it again
    sampled_schools = random.sample(high_schools, min(50, len(high_schools)))

    docs = []
    session = requests.Session()
    session.headers.update({'User-Agent': 'ResearchBot/1.0 (contact@example.com)'})

    print("Fetching text and running NER...")
    for i, school in enumerate(sampled_schools):
        title = school.get('title', '')
        if not title:
            continue
            
        print(f"[{i+1}/{len(sampled_schools)}] Fetching: {title}")
        
        # Fetch from Wikipedia API
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1
        }
        
        try:
            response = session.get(url, params=params)
            data = response.json()
            pages = data['query']['pages']
            page_id = list(pages.keys())[0]
            if page_id == "-1":
                print(f"  -> Page not found for {title}")
                continue
                
            text = pages[page_id].get('extract', '')
            if not text:
                print(f"  -> No text for {title}")
                continue
                
            # Run NER
            doc = nlp(text)
            doc.user_data["title"] = title
            docs.append(doc)
            
        except Exception as e:
            print(f"  -> Error fetching {title}: {e}")

    print(f"Successfully processed {len(docs)} documents.")
    
    print("Generating HTML report...")
    os.makedirs("audit", exist_ok=True)
    
    # Custom HTML to clearly separate documents
    html_content = "<html><head><title>NER Audit</title></head><body>"
    html_content += "<h1>NER Audit - 50 Random High School Articles</h1>"
    
    # Generate displacy HTML for each document and concatenate
    for doc in docs:
        html_content += f"<hr><h2>Article: {doc.user_data.get('title', 'Unknown')}</h2>"
        html = displacy.render(doc, style="ent", page=False, options={"ents": TARGET_LABELS})
        html_content += html
        
    html_content += "</body></html>"

    output_path = os.path.join("audit", "ner_audit_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"NER Audit report saved to {os.path.abspath(output_path)}")
    print("Open this file in a browser to review False Positives and False Negatives.")

if __name__ == "__main__":
    main()
