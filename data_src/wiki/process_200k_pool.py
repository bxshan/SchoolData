# Author: Boxuan Shan + support from Google Gemini 3
import json
import time
import os
import spacy
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict

# Configuration
INPUT_FILE = "../wiki/raw_200k/wikipedia_200k_random.jsonl"
OUTPUT_FILE = "../wiki/blinded_200k/blinded_articles.jsonl"
MODEL_NAME = "en_core_web_sm"
CHUNK_SIZE = 1000  # As requested: 200 chunks of 1000 articles

def process_batch(batch_lines):
    """
    Process a batch of 1000 raw JSON lines.
    Returns a list of blinded JSON strings.
    """
    # Load model (cached per process)
    try:
        nlp = spacy.load(MODEL_NAME)
    except OSError:
        return []

    # Parse JSON
    articles = [json.loads(line) for line in batch_lines]
    texts = [a.get('text', '') for a in articles]
    
    # Process with spaCy pipe
    results = []
    
    # Constants for blinding
    TARGET_LABELS = {"ORG", "GPE", "NORP", "PERSON"}
    GENDERED_PRONOUNS = {
        "he", "she", "him", "her", "his", "hers", "himself", "herself",
        "He", "She", "Him", "Her", "His", "Hers", "Himself", "Herself"
    }
    
    for i, doc in enumerate(nlp.pipe(texts, batch_size=50)): # Micro-batching within the chunk
        text = texts[i]
        
        # Blinding Logic
        entity_map = {}
        type_counters = defaultdict(int)
        replacements = []
        entity_ranges = [] 

        for ent in doc.ents:
            if ent.label_ in TARGET_LABELS:
                ent_text = ent.text
                if ent_text not in entity_map:
                    type_counters[ent.label_] += 1
                    entity_map[ent_text] = f"[{ent.label_}-{type_counters[ent.label_]}]"
                
                replacements.append((ent.start_char, ent.end_char, entity_map[ent_text]))
                entity_ranges.append((ent.start_char, ent.end_char))

        for token in doc:
            if token.text in GENDERED_PRONOUNS:
                t_start = token.idx
                t_end = token.idx + len(token)
                is_overlapped = False
                for r_start, r_end in entity_ranges:
                    if not ((t_end <= r_start) or (t_start >= r_end)):
                        is_overlapped = True
                        break
                if not is_overlapped:
                    replacements.append((t_start, t_end, "[PRON]"))

        replacements.sort(key=lambda x: x[0], reverse=True)
        
        blinded_text = text
        for start, end, repl in replacements:
            blinded_text = blinded_text[:start] + repl + blinded_text[end:]
            
        # Reconstruct record
        out_record = articles[i].copy()
        out_record['text'] = blinded_text
        results.append(json.dumps(out_record))
        
    return results

def main():
    print("="*60)
    print("PROCESSING 200K ARTICLES (POOL EXECUTOR)")
    print("="*60)
    
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file {INPUT_FILE} not found.")
        print("Please run the download script first.")
        return

    # 1. Read and Chunk Data
    print(f"Reading {INPUT_FILE}...")
    chunks = []
    current_chunk = []
    
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            current_chunk.append(line)
            if len(current_chunk) == CHUNK_SIZE:
                chunks.append(current_chunk)
                current_chunk = []
        
    # Append any remaining lines
    if current_chunk:
        chunks.append(current_chunk)
        
    total_chunks = len(chunks)
    print(f"Split data into {total_chunks} chunks of ~{CHUNK_SIZE} articles.")
    
    # 2. Process with Pool
    num_workers = os.cpu_count()
    print(f"Starting processing pool with {num_workers} workers...")
    
    start_time = time.time()
    processed_chunks = 0
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f_out:
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Submit all chunks
            futures = {executor.submit(process_batch, chunk): i for i, chunk in enumerate(chunks)}
            
            for future in as_completed(futures):
                result_lines = future.result()
                
                # Write results immediately
                for line in result_lines:
                    f_out.write(line + '\n')
                
                processed_chunks += 1
                if processed_chunks % 10 == 0 or processed_chunks == total_chunks:
                    elapsed = time.time() - start_time
                    avg_time = elapsed / processed_chunks
                    eta = avg_time * (total_chunks - processed_chunks)
                    print(f"Completed {processed_chunks}/{total_chunks} chunks. ETA: {eta/60:.2f} min")

    total_time = time.time() - start_time
    print("\n" + "="*60)
    print("PROCESSING COMPLETE")
    print(f"Output: {os.path.abspath(OUTPUT_FILE)}")
    print(f"Total Time: {total_time/60:.2f} minutes")
    print("="*60)

if __name__ == "__main__":
    main()
