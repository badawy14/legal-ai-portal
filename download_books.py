import os
import sys
import urllib.parse
import requests

# Force UTF-8 for Windows console
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Target directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, 'library')
os.makedirs(LIBRARY_DIR, exist_ok=True)

# Famous legal books to download from Archive.org (Direct PDF links with proper URL encoding)
BOOKS_TO_DOWNLOAD = [
    {
        "name": "موسوعة_الوسيط_في_شرح_القانون_المدني_السنهوري_الجزء_1.pdf",
        # URL-encoded path for: "507 كتاب     pdf الوسيط في شرح القانون المدني 1 - السنهوري_text.pdf"
        "url": "https://archive.org/download/507-pdf-1/507%20%D9%83%D8%AA%D8%A7%D8%A8%20%20%20%20%20pdf%20%D8%A7%D9%84%D9%88%D8%B3%D9%8A%D8%B7%20%D9%81%D9%8A%20%D8%B4%D8%B1%D8%AD%20%D8%A7%D9%84%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%A7%D9%84%D9%85%D8%AF%D9%86%D9%8A%201%20-%20%D8%A7%D9%84%D8%B3%D9%86%D9%87%D9%88%D8%B1%D9%8A_text.pdf"
    },
    {
        "name": "مذكرات_الدكتور_عبد_الرزاق_السنهوري_الشخصية.pdf",
        # URL-encoded path for: "مذكرات السنهورى_text.pdf"
        "url": "https://archive.org/download/20220319_20220319_1630/%D9%85%D8%B0%D9%83%D8%B1%D8%A7%D8%AA%20%D8%A7%D9%84%D8%B3%D9%86%D9%87%D9%88%D8%B1%D9%89_text.pdf"
    }
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
        print(f"\n[نجاح] تم حفظ الكتاب بنجاح في: {output_path}")
        return True
    except Exception as e:
        print(f"\n[خطأ] فشل تحميل الكتاب من الرابط: {e}")
        return False

if __name__ == "__main__":
    print("==================================================")
    print(" محرك تحميل أمهات الكتب القانونية المصرية التلقائي ")
    print("==================================================")
    
    success_count = 0
    for book in BOOKS_TO_DOWNLOAD:
        dest_path = os.path.join(LIBRARY_DIR, book["name"])
        
        # Check if already exists
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000000:
            print(f"\n[!] كتاب '{book['name']}' موجود مسبقاً، تخطي التحميل.")
            success_count += 1
            continue
            
        success = download_file(book["url"], dest_path, book["name"])
        if success:
            success_count += 1
            
    print(f"\n[+] العملية اكتملت بنجاح! تم تنزيل {success_count} من أصل {len(BOOKS_TO_DOWNLOAD)} كتب.")
    print("[+] يمكنك الآن الانتقال لصفحة المزامنة بالمتصفح للبدء في الفهرسة الفورية للكتب التي تم تنزيلها.")
