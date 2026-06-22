# Author: Boxuan Shan + support from Google Gemini 3
import json
import time
import os
import spacy
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict

# Configuration
INPUT_FILE = "../wiki/raw_200k/wikipedia_200k_random.jsonl"
OUTPUT_DIR = "../wiki/blinded_200k/chunks"
MODEL_NAME = "en_core_web_sm"
CHUNK_SIZE = 1000

def process_batch(batch_lines):
    """
    Process a batch of raw JSON lines.
    Returns a list of blinded JSON strings.
    """
    # Load model (cached per process)
    try:
        nlp = spacy.load(MODEL_NAME)
    except OSError:
        # In a real deployment, we might want to raise an error or handle this gracefully
        return []

    # Parse JSON
    articles = [json.loads(line) for line in batch_lines]
    texts = [a.get('text', '') for a in articles]
    
    results = []
    
    # Constants
    TARGET_LABELS = {"ORG", "GPE", "NORP", "PERSON"}
    GENDERED_PRONOUNS = {
        "he", "she", "him", "her", "his", "hers", "himself", "herself",
        "He", "She", "Him", "Her", "His", "Hers", "Himself", "Herself"
    }
    
    # Process with spaCy pipe
    # batch_size=50 is a good balance for memory/speed within the worker
    for i, doc in enumerate(nlp.pipe(texts, batch_size=50)):
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
    print("RESUMABLE PROCESSING (200K ARTICLES)")
    print("="*60)
    
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file {INPUT_FILE} not found.")
        return

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

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
        
    if current_chunk:
        chunks.append(current_chunk)
        
    total_chunks = len(chunks)
    print(f"Total chunks found: {total_chunks}")
    
    # 2. Check for existing progress
    chunks_to_process = [] # list of (index, chunk_data)
    
    for i, chunk in enumerate(chunks):
        chunk_file = os.path.join(OUTPUT_DIR, f"chunk_{i}.jsonl")
        if os.path.exists(chunk_file):
            # We assume if the file exists, it's done. 
            # For stricter checking, we could verify line count == len(chunk)
            continue
        else:
            chunks_to_process.append((i, chunk))
            
    completed_chunks = total_chunks - len(chunks_to_process)
    print(f"Already completed:  {completed_chunks}")
    print(f"Remaining to do:    {len(chunks_to_process)}")
    
    if not chunks_to_process:
        print("All chunks processed! Nothing to do.")
        return

    # 3. Process with Pool
    num_workers = os.cpu_count()
    print(f"Starting processing with {num_workers} workers...")
    
    start_time = time.time()
    processed_count = 0
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        # Map future -> chunk_index
        futures = {
            executor.submit(process_batch, chunk): idx 
            for idx, chunk in chunks_to_process
        }
        
        print(f"Submitted {len(futures)} tasks to pool.")
        
        for future in as_completed(futures):
            chunk_idx = futures[future]
            try:
                result_lines = future.result()
                
                # Write to specific chunk file
                chunk_filename = os.path.join(OUTPUT_DIR, f"chunk_{chunk_idx}.jsonl")
                with open(chunk_filename, 'w', encoding='utf-8') as f_out:
                    for line in result_lines:
                        f_out.write(line + '\n')
                
                processed_count += 1
                total_done = completed_chunks + processed_count
                
                # Progress logging
                elapsed = time.time() - start_time
                avg_time_per_chunk = elapsed / processed_count
                remaining_chunks = len(chunks_to_process) - processed_count
                eta_seconds = avg_time_per_chunk * remaining_chunks
                
                print(f"[{total_done}/{total_chunks}] Saved chunk_{chunk_idx}.jsonl (ETA: {eta_seconds/60:.1f} min)")

            except Exception as e:
                print(f"Error processing chunk {chunk_idx}: {e}")

    total_time = time.time() - start_time
    print("\n" + "="*60)
    print("PROCESSING COMPLETE")
    print(f"Results directory: {os.path.abspath(OUTPUT_DIR)}")
    print(f"Session Time:      {total_time/60:.2f} minutes")
    print("="*60)

if __name__ == "__main__":
    main()
