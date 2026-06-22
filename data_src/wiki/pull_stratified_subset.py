import os
import json
import time
import argparse
from datasets import load_dataset

def classify_article(text):
    """
    Heuristic-based classification of Wikipedia articles into Biography, History, Politics.
    Uses the first 500 characters (lead paragraph) for quick matching.
    """
    intro = text[:500].lower()
    
    # Biography: Look for typical birth date patterns or "is a"/"was a" followed by nationality/occupation
    if "(born " in intro or " is a " in intro or " was a " in intro or " is an " in intro or " was an " in intro:
        if " politician" in intro or " member of parliament" in intro or " senator" in intro or " mayor" in intro:
            return "Politics"
        if "(born " in intro or "(c. " in intro:
            return "Biography"
            
    # History
    history_keywords = [
        " was a war ", " was a battle ", " dynasty", " empire", 
        " treaty of ", " was a conflict ", " was a military ", 
        " revolution", " civil war", " uprising"
    ]
    if any(k in intro for k in history_keywords):
        return "History"
        
    # Politics (Non-biography)
    politics_keywords = [
        " is a political party ", " was a political party ", 
        " general election", " presidential election", 
        " legislative election", " parliament", " legislature"
    ]
    if any(k in intro for k in politics_keywords):
        return "Politics"
        
    return "Other"

def pull_subset(target_tokens=300_000_000):
    print("Initializing stream from wikimedia/wikipedia (20231101.en)...")
    dataset = load_dataset("wikimedia/wikipedia", "20231101.en", split='train', streaming=True)
    
    # Approx 1 token ≈ 4 characters
    # We want 100M tokens per category, so ~400M characters per category.
    target_chars_per_category = (target_tokens // 3) * 4
    
    categories = {
        "Biography": {"chars": 0, "articles": 0, "file": open("data_src/wiki/subset_biography.jsonl", "w", encoding="utf-8")},
        "History": {"chars": 0, "articles": 0, "file": open("data_src/wiki/subset_history.jsonl", "w", encoding="utf-8")},
        "Politics": {"chars": 0, "articles": 0, "file": open("data_src/wiki/subset_politics.jsonl", "w", encoding="utf-8")}
    }
    
    start_time = time.time()
    processed = 0
    
    print(f"Targeting ~{target_tokens:,} tokens total (~{target_tokens//3:,} per category).")
    
    for article in dataset:
        processed += 1
        text = article.get("text", "")
        if not text:
            continue
            
        cat = classify_article(text)
        
        if cat in categories:
            stats = categories[cat]
            if stats["chars"] < target_chars_per_category:
                # Save to JSONL
                stats["file"].write(json.dumps(article) + "\n")
                stats["chars"] += len(text)
                stats["articles"] += 1
                
        # Status update every 10,000 processed
        if processed % 10000 == 0:
            print(f"Processed: {processed:,} | "
                  f"Bio: {categories['Biography']['articles']} | "
                  f"Hist: {categories['History']['articles']} | "
                  f"Pol: {categories['Politics']['articles']}", end="\r")
                  
        # Check if done
        if all(c["chars"] >= target_chars_per_category for c in categories.values()):
            break

    print("\n\nExtraction Complete!")
    for cat, stats in categories.items():
        stats["file"].close()
        approx_tokens = stats["chars"] // 4
        print(f"{cat}: {stats['articles']:,} articles, ~{approx_tokens:,} tokens")
        
    total_time = time.time() - start_time
    print(f"Finished in {total_time:.2f} seconds.")

if __name__ == "__main__":
    os.makedirs("data_src/wiki", exist_ok=True)
    pull_subset(300_000_000)
