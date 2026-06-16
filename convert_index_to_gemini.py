import os
import json
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import google.generativeai as genai

# Directories configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
INDEX_FILE = os.path.join(DATA_DIR, 'vector_index.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')

# Threading locks and progress variables
progress_lock = threading.Lock()
api_key_lock = threading.Lock()

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}", flush=True)
    return {}

def get_api_keys(settings):
    raw_key = settings.get("gemini_api_key", "")
    if not raw_key:
        raw_key = os.environ.get("GEMINI_API_KEY", "")
    if not raw_key:
        return []
    # Split keys by comma, semicolon, newline or space
    keys = [k.strip() for k in re.split(r'[,;\n\s]+', raw_key) if k.strip()]
    return keys

def main():
    settings = load_settings()
    keys = get_api_keys(settings)
    if not keys:
        print("Error: No Gemini API keys found in data/settings.json or environment variables.", flush=True)
        return
        
    print(f"Found {len(keys)} Gemini API keys for embedding rotation.", flush=True)
    
    if not os.path.exists(INDEX_FILE):
        print(f"Error: Vector index file {INDEX_FILE} not found.", flush=True)
        return
        
    print(f"Loading vector index from {INDEX_FILE}...", flush=True)
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
        
    total_items = len(index_data)
    print(f"Loaded {total_items} chunks in total.", flush=True)
    
    # Identify items that need conversion (dimension != 768)
    items_to_convert = []
    for idx, item in enumerate(index_data):
        embedding = item.get("embedding", [])
        if len(embedding) != 768:
            items_to_convert.append((idx, item))
            
    items_count = len(items_to_convert)
    print(f"Found {items_count} chunks that need embedding conversion.", flush=True)
    
    if items_count == 0:
        print("All chunks are already converted to 768-dimensional embeddings!", flush=True)
        return
        
    # Global state for key rotation and progress
    state = {
        "current_key_idx": 0,
        "converted_count": 0,
        "start_time": time.time()
    }
    
    # Configure initial key
    genai.configure(api_key=keys[state["current_key_idx"]])
    
    # Worker function for ThreadPoolExecutor
    def process_batch(batch):
        batch_texts = [item.get("text", "") for _, item in batch]
        
        success = False
        retry_delay = 5 # Start with 5 seconds backoff
        
        while not success:
            try:
                # Call Gemini batch embedding model
                response = genai.embed_content(
                    model="models/gemini-embedding-001",
                    content=batch_texts,
                    task_type="retrieval_query"
                )
                
                embeddings = response.get('embedding', [])
                if not embeddings:
                    embeddings = response.get('embeddings', [])
                    
                if len(embeddings) != len(batch):
                    raise ValueError(f"Embeddings count mismatch: got {len(embeddings)}, expected {len(batch)}")
                
                # Assign back safely directly to index data (each thread modifies separate items)
                for (original_idx, item), embedding in zip(batch, embeddings):
                    item["embedding"] = embedding
                    
                success = True
            except Exception as e:
                err_str = str(e)
                # Check for rate limit or quota errors
                is_rate_limit = "429" in err_str or "quota" in err_str.lower() or "limit exceeded" in err_str.lower()
                
                if is_rate_limit:
                    # Rotate key first
                    with api_key_lock:
                        state["current_key_idx"] = (state["current_key_idx"] + 1) % len(keys)
                        print(f"\n[Rate Limit] Rotating globally to key index {state["current_key_idx"]}...", flush=True)
                        genai.configure(api_key=keys[state["current_key_idx"]])
                    
                    # Sleep to let quota reset
                    sleep_time = 65 # 65 seconds to clear per-minute quota
                    print(f"[Rate Limit] 429 Quota Exceeded. Sleeping for {sleep_time} seconds before retrying batch...", flush=True)
                    time.sleep(sleep_time)
                else:
                    # General error (like network glitch), sleep with exponential backoff up to 60s
                    print(f"\n[Error] API call failed: {e}. Retrying in {retry_delay}s...", flush=True)
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
                    
        return success, len(batch)

    # Split items into batches of 30
    batch_size = 30
    batches = [items_to_convert[i : i + batch_size] for i in range(0, items_count, batch_size)]
    
    # max_workers=3 is very safe to not exceed the 100 RPM limit
    print(f"Processing {len(batches)} batches of size {batch_size} in parallel using 3 workers...", flush=True)
    
    # Run ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_batch, b): b for b in batches}
        
        for future in as_completed(futures):
            success, count = future.result()
            
            with progress_lock:
                state["converted_count"] += count
                elapsed = time.time() - state["start_time"]
                speed = state["converted_count"] / elapsed if elapsed > 0 else 0
                pct = (state["converted_count"] / items_count) * 100
                print(f"Progress: {state["converted_count"]}/{items_count} items ({pct:.1f}%) | Speed: {speed:.1f} items/sec", flush=True)
                
                # Auto-save every 300 items to prevent loss
                if state["converted_count"] % 300 == 0 or state["converted_count"] >= items_count:
                    print(f"Auto-saving vector index progress to {INDEX_FILE}...", flush=True)
                    try:
                        with open(INDEX_FILE, 'w', encoding='utf-8') as f:
                            json.dump(index_data, f, ensure_ascii=False, indent=4)
                    except Exception as e:
                        print(f"Failed to auto-save: {e}", flush=True)
                        
    # Final save
    print(f"\nSaving final converted 768-dimension vector index to {INDEX_FILE}...", flush=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, ensure_ascii=False, indent=4)
        
    print("Parallel conversion completed successfully!", flush=True)

if __name__ == "__main__":
    main()
