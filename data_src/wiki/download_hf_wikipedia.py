# Author: Boxuan Shan + support from Google Gemini 3
import argparse
import json
import csv
import os
import time
from datasets import load_dataset

def download_articles(count, output_prefix, random_mode, output_formats):
    dataset_name = "wikimedia/wikipedia"
    config = "20231101.en"
    
    print("="*60)
    print(f"WIKIPEDIA DOWNLOADER")
    print(f"Target Count:   {count}")
    print(f"Random Mode:    {random_mode}")
    print(f"Output Formats: {', '.join(output_formats)}")
    print(f"Output Prefix:  {output_prefix}")
    print("="*60)
    
    start_time = time.time()
    
    # 1. Load Dataset
    print(f"Initializing stream from {dataset_name} ({config})...")
    dataset = load_dataset(dataset_name, config, split='train', streaming=True)
    
    # 2. Shuffle if requested
    if random_mode:
        print("Shuffling stream (buffer_size=10,000)...")
        dataset = dataset.shuffle(seed=42, buffer_size=10000)
    
    collected_articles = []
    
    # 3. Determine Mode (Streaming vs Memory)
    # If we only need JSONL, we can stream write.
    # If we need JSON or CSV, we generally need to collect in memory (or use complex append logic).
    # For simplicity and safety with large counts, if count > 10,000 and JSON/CSV is requested, warn user.
    
    stream_write_jsonl = 'jsonl' in output_formats and len(output_formats) == 1
    
    if stream_write_jsonl:
        output_file = f"{output_prefix}.jsonl"
        print(f"Streaming write to {output_file}...")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            current_count = 0
            for article in dataset:
                f.write(json.dumps(article) + '\n')
                current_count += 1
                
                if current_count % 1000 == 0:
                    print(f"Collected {current_count} articles...", end='\r')
                
                if current_count >= count:
                    break
        collected_count = current_count
        
    else:
        # Memory collection mode (for JSON/CSV)
        print("Collecting articles into memory...")
        current_count = 0
        for article in dataset:
            collected_articles.append(article)
            current_count += 1
            
            if current_count % 1000 == 0:
                print(f"Collected {current_count} articles...", end='\r')
            
            if current_count >= count:
                break
        
        collected_count = len(collected_articles)
        print(f"\nFinished collecting {collected_count} articles.")

        # Save JSON
        if 'json' in output_formats:
            fname = f"{output_prefix}.json"
            print(f"Saving JSON to {fname}...")
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(collected_articles, f, indent=2, ensure_ascii=False)

        # Save CSV
        if 'csv' in output_formats:
            fname = f"{output_prefix}.csv"
            print(f"Saving CSV to {fname}...")
            with open(fname, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                if collected_articles:
                    header = list(collected_articles[0].keys())
                    writer.writerow(header)
                    for art in collected_articles:
                        writer.writerow([art.get(k, "") for k in header])

        # Save JSONL (if requested alongside others)
        if 'jsonl' in output_formats:
            fname = f"{output_prefix}.jsonl"
            print(f"Saving JSONL to {fname}...")
            with open(fname, 'w', encoding='utf-8') as f:
                for art in collected_articles:
                    f.write(json.dumps(art) + '\n')

    total_time = time.time() - start_time
    print(f"\nDone! Processed {collected_count} articles in {total_time:.2f} seconds.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Wikipedia articles (Sequential or Random).")
    
    parser.add_argument(
        "-n", "--count", 
        type=int, 
        default=1000,
        help="Number of articles to download."
    )
    
    parser.add_argument(
        "-r", "--random", 
        action="store_true", 
        help="Enable random shuffling of the dataset."
    )
    
    parser.add_argument(
        "-o", "--output", 
        type=str, 
        default="wiki_data",
        help="Output filename prefix (extension will be added based on formats)."
    )
    
    parser.add_argument(
        "-f", "--formats", 
        nargs="+", 
        choices=['json', 'csv', 'jsonl'], 
        default=['json', 'csv'],
        help="Output formats to generate (default: json csv). Use 'jsonl' for large datasets."
    )

    args = parser.parse_args()
    
    download_articles(args.count, args.output, args.random, args.formats)
