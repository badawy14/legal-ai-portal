import os
import sys
import uuid
import time
import requests

# Force UTF-8 encoding for stdout/stderr on Windows to prevent UnicodeEncodeError (charmap codec)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import backend helper functions from app.py
from app import (
    load_settings, load_registry, save_registry, 
    load_index, save_index, process_pdf_file, get_embedding,
    DEFAULT_LIBRARY_DIR, calculate_file_hash
)

def main():
    print("==================================================")
    print("    بوابة القانون الذكية - أداة مزامنة المكتبة المحلية    ")
    print("==================================================")
    
    settings = load_settings()
    lib_path = settings.get("local_library_path", DEFAULT_LIBRARY_DIR)
    
    print(f"\n[*] جاري قراءة المجلد المحلي: {lib_path}")
    
    if not os.path.exists(lib_path):
        print(f"[!] خطأ: المجلد المحدد غير موجود: {lib_path}")
        print("[*] جاري إنشاء المجلد الافتراضي...")
        os.makedirs(lib_path, exist_ok=True)
        print(f"[+] تم إنشاء المجلد. يرجى وضع كتب الـ PDF بداخله وإعادة تشغيل السكربت.")
        sys.exit(0)
        
    registry = load_registry()
    index = load_index()
    
    # Scan PDFs recursively (including subfolders)
    files_in_folder = []
    for root_dir, sub_dirs, files in os.walk(lib_path):
        for file in files:
            if file.lower().endswith('.pdf'):
                rel_path = os.path.relpath(os.path.join(root_dir, file), lib_path)
                files_in_folder.append(rel_path)
                
    # Clean up deleted files from index and registry FIRST
    deleted_count = 0
    keys_to_remove = []
    for reg_filename, info in registry.items():
        path_str = info.get("path") or ""
        if reg_filename not in files_in_folder and (path_str.startswith(lib_path) or not os.path.exists(path_str)):
            old_id = info.get("doc_id")
            index = [item for item in index if item['doc_id'] != old_id]
            keys_to_remove.append(reg_filename)
            deleted_count += 1
            print(f"[-] تم حذف الكتاب '{reg_filename}' من الفهرس لحذفه من المجلد.")
            
    for k in keys_to_remove:
        del registry[k]
        
    if deleted_count > 0:
        save_index(index)
        save_registry(registry)
        
    if not files_in_folder:
        print("[!] المجلد فارغ! يرجى وضع بعض كتب القانون بصيغة PDF فيه أولاً.")
        print(f"المسار: {lib_path}")
        sys.exit(0)
        
    print(f"[+] تم العثور على {len(files_in_folder)} كتاب قانوني في المجلد (بما في ذلك المجلدات الفرعية).")
    
    scanned = 0
    indexed = 0
    skipped = 0
    errors = 0
    
    active_filenames = []
    
    for filename in files_in_folder:
        active_filenames.append(filename)
        file_path = os.path.join(lib_path, filename)
        stat = os.stat(file_path)
        file_size = stat.st_size
        last_modified = stat.st_mtime
        
        scanned += 1
        
        # Check registry
        reg_entry = registry.get(filename)
        if reg_entry and reg_entry.get("file_size") == file_size and reg_entry.get("last_modified") == last_modified:
            skipped += 1
            print(f"[{scanned}/{len(files_in_folder)}] {filename} -> مؤرشف بالفعل (تم التخطي)")
            continue
        # Calculate file hash to detect duplicates
        file_hash = calculate_file_hash(file_path)
        
        # Check for duplicate content (same hash) in the registry
        duplicate_found = False
        if file_hash:
            for reg_name, reg_val in registry.items():
                if reg_name != filename and reg_val.get("file_hash") == file_hash:
                    if reg_name in files_in_folder:
                        print(f"[{scanned}/{len(files_in_folder)}] {filename} -> متطابق تماماً في المحتوى مع '{reg_name}' (تم التخطي للحد من التكرار)")
                        duplicate_found = True
                        break
        
        if duplicate_found:
            skipped += 1
            continue

        print(f"\n[{scanned}/{len(files_in_folder)}] جاري معالجة كتاب جديد: {filename}")
        
        # Clean up old index if exists
        if reg_entry:
            old_id = reg_entry.get("doc_id")
            index = [item for item in index if item['doc_id'] != old_id]
            
        try:
            doc_id = str(uuid.uuid4())
            start_time = time.time()
            
            # Extract texts & pages (performs OCR internally using fitz and Gemini)
            chunks, pages_count = process_pdf_file(file_path, filename, settings)
            
            if not chunks:
                print(f"[!] تحذير: لم يتم استخراج أي نصوص من {filename}. تأكد من صحة الملف.")
                skipped += 1
                continue
                
            print(f"[+] تم استخراج {pages_count} صفحة وتقسيمها إلى {len(chunks)} جزء.")
            print("[*] جاري توليد التضمينات (Embeddings) وحفظ المتجهات...")
            
            # Generate embeddings
            indexed_chunks = 0
            for i, chunk in enumerate(chunks):
                chunk["doc_id"] = doc_id
                chunk["doc_name"] = filename
                
                # Fetch embedding vector
                embedding = get_embedding(chunk["text"], settings)
                chunk["embedding"] = embedding
                index.append(chunk)
                indexed_chunks += 1
                
                # Print progress percentage for long books
                if (i + 1) % 10 == 0 or (i + 1) == len(chunks):
                    print(f"    - معالجة المتجهات: {i+1}/{len(chunks)}")
            
            # Update registry
            registry[filename] = {
                "doc_id": doc_id,
                "file_size": file_size,
                "last_modified": last_modified,
                "pages_count": pages_count,
                "chunks_count": indexed_chunks,
                "path": file_path,
                "file_hash": file_hash
            }
            
            indexed += 1
            duration = time.time() - start_time
            print(f"[+] نجحت الفهرسة! تم حفظ {indexed_chunks} مادة خلال {duration:.1f} ثانية.")
            
        except Exception as e:
            errors += 1
            print(f"[!] خطأ أثناء معالجة {filename}: {e}")
            
    if indexed > 0:
        save_index(index)
        save_registry(registry)
        
    print("\n==================================================")
    print("                   اكتمل الفحص                    ")
    print(f" إجمالي الكتب التي تم فحصها: {scanned}")
    print(f" كتب جديدة تمت إضافتها: {indexed}")
    print(f" كتب مؤرشفة تم تخطيها: {skipped}")
    print(f" كتب محذوفة تمت إزالتها: {deleted_count}")
    print(f" أخطاء: {errors}")
    print("==================================================")

if __name__ == "__main__":
    main()
