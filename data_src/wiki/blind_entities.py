# Author: Boxuan Shan + support from Google Gemini 3
import spacy
import os
import glob
from collections import defaultdict

def blind_articles():
    # Load the spacy model
    print("Loading spaCy model 'en_core_web_sm'...")
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        print("Model not found. Please run: python -m spacy download en_core_web_sm")
        return

    input_dir = "selected_articles"
    output_dir = "blinded_articles"

    if not os.path.exists(input_dir):
        print(f"Error: Input directory '{input_dir}' does not exist.")
        return

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory '{output_dir}' created.")

    # Get all .txt files
    files = glob.glob(os.path.join(input_dir, "*.txt"))
    print(f"Found {len(files)} files to process.")

    # Target entity labels
    TARGET_LABELS = ["ORG", "GPE", "NORP", "PERSON"]
    
    # Gendered pronouns to target
    GENDERED_PRONOUNS = {
        "he", "she", "him", "her", "his", "hers", "himself", "herself",
        "He", "She", "Him", "Her", "His", "Hers", "Himself", "Herself"
    }

    for file_path in files:
        filename = os.path.basename(file_path)
        print(f"Processing: {filename}")

        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        doc = nlp(text)

        # Dictionary to map specific text string -> Pseudonym (e.g., "Alabama" -> "[GPE-1]")
        # This ensures consistent naming throughout the doc
        entity_map = {}
        type_counters = defaultdict(int)
        
        # List of replacements: (start_char, end_char, replacement_string)
        replacements = []

        # 1. Identify Entities
        # We assume entities don't overlap with themselves in spaCy
        entity_ranges = set() # To track occupied character ranges

        for ent in doc.ents:
            if ent.label_ in TARGET_LABELS:
                # Create consistency map
                ent_text = ent.text
                if ent_text not in entity_map:
                    type_counters[ent.label_] += 1
                    entity_map[ent_text] = f"[{ent.label_}-{type_counters[ent.label_]}]"
                
                replacements.append((ent.start_char, ent.end_char, entity_map[ent_text]))
                
                # Mark range as occupied
                for i in range(ent.start_char, ent.end_char):
                    entity_ranges.add(i)

        # 2. Identify Pronouns (Gender Neutralization)
        for token in doc:
            # Check if token is gendered pronoun
            if token.text in GENDERED_PRONOUNS:
                # Check if this token is already part of an entity replacement
                # (e.g., if a PERSON entity contained the word "She", unlikely but good to be safe)
                is_overlapped = False
                for i in range(token.idx, token.idx + len(token)):
                    if i in entity_ranges:
                        is_overlapped = True
                        break
                
                if not is_overlapped:
                    # Using [PRON] as the neutral placeholder
                    replacement_str = "[PRON]"
                    
                    # Optional: Attempt to preserve case if we wanted to map He->They, he->they
                    # But [PRON] is standard for blinding.
                    replacements.append((token.idx, token.idx + len(token), replacement_str))

        # 3. Apply replacements
        # Sort by start_char descending to replace without messing up earlier indices
        replacements.sort(key=lambda x: x[0], reverse=True)

        blinded_text = text
        for start, end, repl in replacements:
            blinded_text = blinded_text[:start] + repl + blinded_text[end:]

        # Save to new file
        output_path = os.path.join(output_dir, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(blinded_text)
            
        # Optional: Save the mapping key for reference (useful for debugging, but maybe not for the final blinded set)
        # mapping_path = os.path.join(output_dir, filename + ".map")
        # with open(mapping_path, "w") as f:
        #    for k, v in entity_map.items():
        #        f.write(f"{v}: {k}\n")

        print(f"  -> Applied {len(replacements)} changes. Saved to {output_path}")

    print("\nProcessing complete.")

if __name__ == "__main__":
    blind_articles()
