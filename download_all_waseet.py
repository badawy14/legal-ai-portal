import os
import sys
import urllib.parse
import requests

# Force UTF-8 encoding for Windows console to prevent UnicodeEncodeError (charmap codec)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Target directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, 'library')
os.makedirs(LIBRARY_DIR, exist_ok=True)

# List of files in the collection "9_20250410" on Archive.org
# We will download the searchable versions ending in "_text.pdf"
COLLECTION_FILES = [
    {"display": "الوسيط 1 - مصادر الالتزام.pdf", "name": "1-نظرية-اللتزام-بوجه-عام-مصادر-الإلتزام (1)_text.pdf"},
    {"display": "الوسيط 2 - الإثبات وآثار الالتزام.pdf", "name": "2-نظرية-الإلتزام-بوجه-عام-الإثبات-آثار-الإلتزام_text.pdf"},
    {"display": "الوسيط 3 - الأوصاف والحوالة والانقضاء.pdf", "name": "3-نظرية-الإلتزام-بوجه-عام-الأوصاف-،-الحوالة-،-الإنقضاء_text.pdf"},
    {"display": "الوسيط 4 - عقد البيع والمقايضة.pdf", "name": "4-العقود-التي-تقع-على-الملكية-البيع_text.pdf"},
    {"display": "الوسيط 5 - باقي العقود التي تقع على الملكية.pdf", "name": "5-باقي-العقود-التي-تقع-على-الملكية_text.pdf"},
    {"display": "الوسيط 6-1 - عقد الإيجار.pdf", "name": "6-1-العقود-الواردة-على-الإنتفاع-بالشيء-الإيجار-و-العارية-المجلد-الأول-الإيجار_text.pdf"},
    {"display": "الوسيط 6-2 - عقد العارية.pdf", "name": "6-2-العقود-الواردة-على-الإنتفاع-بالشيء-الإيجار-و-العارية-المجلد-الثاني-العارية_text.pdf"},
    {"display": "الوسيط 7-1 - العقود الواردة على العمل.pdf", "name": "7-1-العقود-الواردة-على-العمل_text.pdf"},
    {"display": "الوسيط 7-2 - عقود الغرر وعقد التأمين.pdf", "name": "7-2-عقود-الغرر-و-عقد-التأمين_text.pdf"},
    {"display": "الوسيط 8 - حق الملكية.pdf", "name": "8-حق-الملكية_text.pdf"},
    {"display": "الوسيط 9 - أسباب كسب الملكية.pdf", "name": "9-أسباب-كسب-الملكية_text.pdf"},
    {"display": "الوسيط 10 - التأمينات الشخصية والعينية.pdf", "name": "10-التأمينات-الشخصية-و-العينية_text.pdf"}
]

def download_file(url, output_path, display_name):
    print(f"\n[+] جاري تحميل: {display_name}...")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024 * 1024  # 1MB
        downloaded = 0
        
        with open(output_path, 'wb') as f:
            for data in response.iter_content(block_size):
                f.write(data)
                downloaded += len(data)
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    print(f"\r    - التقدم: {percent:.1f}% ({mb_downloaded:.1f}MB / {mb_total:.1f}MB)", end='', flush=True)
                else:
                    mb_downloaded = downloaded / (1024 * 1024)
                    print(f"\r    - تم تحميل: {mb_downloaded:.1f}MB", end='', flush=True)
        print(f"\n[نجاح] تم الحفظ بنجاح في: {output_path}")
        return True
    except Exception as e:
        print(f"\n[خطأ] فشل تحميل الكتاب: {e}")
        return False

def main():
    print("==================================================")
    print("    تحميل موسوعة الوسيط الكاملة (10 أجزاء نصية)   ")
    print("==================================================")
    
    success_count = 0
    for book in COLLECTION_FILES:
        # Save filename on disk (cleaned name)
        clean_name = book["display"]
        dest_path = os.path.join(LIBRARY_DIR, clean_name)
        
        # Check if already exists and is valid
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000000:
            print(f"\n[!] الجزء '{clean_name}' موجود مسبقاً، تخطي التحميل.")
            success_count += 1
            continue
            
        # URL encode the filename for archive.org
        encoded_name = urllib.parse.quote(book["name"])
        download_url = f"https://archive.org/download/9_20250410/{encoded_name}"
        
        success = download_file(download_url, dest_path, clean_name)
        if success:
            success_count += 1
            
    print("\n==================================================")
    print(f"[+] اكتمل التحميل! تم تنزيل {success_count} من أصل {len(COLLECTION_FILES)} مجلدات.")
    print("[+] يمكنك الآن مزامنة المجلد المحلي بالكامل مجاناً 100%.")
    print("==================================================")

if __name__ == "__main__":
    main()
