import os
import sys
import fitz  # PyMuPDF

# Force UTF-8 encoding for stdout/stderr on Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def check_pdf_type(file_path):
    try:
        doc = fitz.open(file_path)
        total_pages = len(doc)
        text_pages = 0
        scanned_pages = 0
        
        # Check first 5 pages to determine type
        pages_to_check = min(5, total_pages)
        for i in range(pages_to_check):
            page = doc[i]
            text = page.get_text().strip()
            if len(text) > 100:
                text_pages += 1
            else:
                scanned_pages += 1
                
        doc.close()
        
        # If majority of checked pages have no text, it's scanned
        if text_pages == 0 and scanned_pages > 0:
            return "scanned"  # مصورة (تحتاج OCR)
        elif text_pages > 0 and scanned_pages == 0:
            return "digital"  # نصية (جاهزة ومجانية 100%)
        else:
            return "mixed"    # مختلطة
    except Exception as e:
        return f"error: {str(e)}"

def main():
    print("==================================================")
    
    # Load settings to get library path
    import json
    settings_path = os.path.join("data", "settings.json")
    lib_path = "library"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                lib_path = settings.get("local_library_path", "library")
        except Exception:
            pass
            
    print(f"[*] جاري فحص مجلد المكتبة: {lib_path}")
    print("==================================================")
    
    if not os.path.exists(lib_path):
        print(f"[!] المجلد غير موجود: {lib_path}")
        return
        
    scanned_books = []
    digital_books = []
    errors = []
    
    for root_dir, sub_dirs, files in os.walk(lib_path):
        for file in files:
            if file.lower().endswith('.pdf'):
                full_path = os.path.join(root_dir, file)
                rel_path = os.path.relpath(full_path, lib_path)
                
                status = check_pdf_type(full_path)
                if status == "scanned":
                    scanned_books.append(rel_path)
                elif status == "digital":
                    digital_books.append(rel_path)
                elif status == "mixed":
                    digital_books.append(rel_path)  # treat as digital (has some text)
                else:
                    errors.append((rel_path, status))
                    
    print(f"\n[+] إحصائيات المجلد:")
    print(f"   - إجمالي كتب الـ PDF: {len(scanned_books) + len(digital_books) + len(errors)}")
    print(f"   - كتب نصية (جاهزة ومجانية): {len(digital_books)}")
    print(f"   - كتب مصورة (تحتاج OCR): {len(scanned_books)}")
    if errors:
        print(f"   - كتب تالفة أو بها أخطاء قراءة: {len(errors)}")
        
    if scanned_books:
        print("\n⚠️ قائمة الكتب المصورة (التي لا تحتوي على نص رقمي وتحتاج OCR لتشغيلها):")
        for idx, book in enumerate(scanned_books[:50], 1):
            print(f"   {idx}. {book}")
        if len(scanned_books) > 50:
            print(f"   ... وثمة {len(scanned_books) - 50} كتب مصورة أخرى.")
            
    print("\n💡 نصيحة: الكتب المصورة أعلاه يمكنك استبدالها بنسخ نصية (تستطيع تظليل النص فيها بـ PDF) لتعمل مجاناً وبسرعة فائقة!")

if __name__ == "__main__":
    main()
