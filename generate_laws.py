"""
generate_laws.py - Generates comprehensive Egyptian law database using Gemini API
Run: .venv\Scripts\python.exe generate_laws.py
"""
import json, time, os, sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
from google import genai as genai_sdk

# Load API key from settings
settings_path = os.path.join(os.path.dirname(__file__), 'data', 'settings.json')
with open(settings_path, 'r', encoding='utf-8') as f:
    settings = json.load(f)

API_KEY = settings.get('gemini_api_key', '')
client = genai_sdk.Client(api_key=API_KEY)

LAWS = [
    {"id": "civil", "name": "القانون المدني المصري", "number": "131", "year": "1948",
     "topics": ["أحكام عامة","العقد وأركانه","البيع والإيجار","التعويض","التقادم","الحقوق العينية","الرهن","الوكالة","الهبة"]},
    {"id": "penal", "name": "قانون العقوبات المصري", "number": "58", "year": "1937",
     "topics": ["العقوبات وأنواعها","القصد الجنائي","الجنايات والجنح","القتل العمد والخطأ","السرقة","النصب والاحتيال","الرشوة","التزوير","الإخلال بالنظام العام"]},
    {"id": "labor", "name": "قانون العمل", "number": "12", "year": "2003",
     "topics": ["عقد العمل","الأجور والمكافآت","ساعات العمل والإجازات","الفصل التعسفي","مكافأة نهاية الخدمة","التأمينات الاجتماعية","السلامة المهنية","النزاعات العمالية"]},
    {"id": "criminal_proc", "name": "قانون الإجراءات الجنائية", "number": "150", "year": "1950",
     "topics": ["الضبط القضائي","الاستدلال والتحقيق","القبض والتفتيش","الحبس الاحتياطي","المحاكمة والطعن","أحكام البراءة والإدانة","التقادم الجنائي"]},
    {"id": "commerce", "name": "قانون التجارة المصري", "number": "17", "year": "1999",
     "topics": ["الأعمال التجارية","الشركات التجارية","العقود التجارية","الأوراق التجارية","السندات والكمبيالات","الإفلاس والإعسار","النزاعات التجارية"]},
    {"id": "civil_proc", "name": "قانون المرافعات المدنية والتجارية", "number": "13", "year": "1968",
     "topics": ["الاختصاص القضائي","رفع الدعوى وقيدها","إجراءات التقاضي","الأحكام وطرق الطعن","الاستئناف والنقض","التنفيذ الجبري","الحجز والأوامر على عرائض"]},
    {"id": "personal_status", "name": "قانون الأحوال الشخصية", "number": "25", "year": "1929",
     "topics": ["الزواج وأركانه","الطلاق وأنواعه","النفقة والمتعة","الحضانة وحق الرؤية","الميراث والوصية","النسب وإثباته","الولاية القانونية"]},
    {"id": "companies", "name": "قانون الشركات المساهمة وشركات التوصية بالأسهم وذات المسئولية المحدودة", "number": "159", "year": "1981",
     "topics": ["تأسيس الشركات","رأس المال والأسهم","مجلس الإدارة","الجمعية العمومية","توزيع الأرباح","حل الشركة وتصفيتها","حماية الأقلية"]},
    {"id": "income_tax", "name": "قانون ضريبة الدخل", "number": "91", "year": "2005",
     "topics": ["الوعاء الضريبي","الإعفاءات الضريبية","ضريبة المرتبات","ضريبة الأرباح التجارية","الضريبة على رأس المال","الإقرارات الضريبية","التقاضي الضريبي"]},
    {"id": "intellectual", "name": "قانون حماية الملكية الفكرية", "number": "82", "year": "2002",
     "topics": ["حقوق المؤلف","براءات الاختراع","العلامات التجارية","النماذج الصناعية","حماية قواعد البيانات","الجزاءات والعقوبات"]},
    {"id": "consumer", "name": "قانون حماية المستهلك", "number": "181", "year": "2018",
     "topics": ["حقوق المستهلك","الغش التجاري","البيع بالتقسيط","الضمانات والإصلاح","الإعلان المضلل","التسوية والشكاوى","العقوبات"]},
    {"id": "investment", "name": "قانون الاستثمار", "number": "72", "year": "2017",
     "topics": ["ضمانات المستثمر","الإعفاءات الضريبية للمستثمرين","المناطق الاستثمارية","نزاعات الاستثمار","التحكيم الدولي","الاستثمار الأجنبي"]},
    {"id": "arbitration", "name": "قانون التحكيم في المواد المدنية والتجارية", "number": "27", "year": "1994",
     "topics": ["اتفاق التحكيم","هيئة التحكيم","إجراءات التحكيم","القانون الواجب التطبيق","حكم التحكيم وتنفيذه","بطلان حكم التحكيم"]},
    {"id": "antimonopoly", "name": "قانون حماية المنافسة ومنع الممارسات الاحتكارية", "number": "3", "year": "2005",
     "topics": ["الممارسات الاحتكارية","الاندماجات والاستحواذ","الهيمنة على السوق","التحقيقات والجزاءات","حماية المنافسة العادلة"]},
    {"id": "aml", "name": "قانون مكافحة غسل الأموال وتمويل الإرهاب", "number": "80", "year": "2002",
     "topics": ["جريمة غسل الأموال","الإخطار بالعمليات المشبوهة","التجميد والمصادرة","التعاون الدولي","العقوبات والجزاءات"]},
]

def generate_law_articles(law):
    topics_str = " - ".join(law["topics"])
    prompt = f"""أنت مرجع قانوني مصري متخصص. اكتب محتوى تفصيلياً شاملاً عن {law['name']} رقم {law['number']} لسنة {law['year']}.

المحتوى المطلوب:
1. نبذة تعريفية عن القانون وأهميته (فقرة)
2. أهم المواد القانونية الفعلية مع نصوصها التقريبية (15-20 مادة مهمة)
3. المبادئ الجوهرية التي يقوم عليها القانون
4. الموضوعات الرئيسية: {topics_str}

الصيغة المطلوبة - JSON فقط بدون أي نص خارجه:
{{
  "description": "وصف شامل للقانون",
  "key_principles": ["مبدأ 1", "مبدأ 2", "مبدأ 3"],
  "articles": [
    {{"number": "المادة 1", "title": "عنوان المادة", "text": "نص المادة التفصيلي"}},
    ...
  ]
}}"""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        text = response.text.strip()
        # Clean markdown code blocks if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        return json.loads(text.strip())
    except Exception as e:
        print(f"  ERROR parsing {law['name']}: {e}")
        return None

output_path = os.path.join(os.path.dirname(__file__), 'data', 'legislation.json')

# Load existing data if any
try:
    with open(output_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)
    existing_ids = {law.get('id') for law in existing}
except:
    existing = []
    existing_ids = set()

print(f"Starting generation of {len(LAWS)} laws...")
print(f"Already have: {len(existing)} laws in database")
print("="*60)

new_laws = list(existing)

for i, law in enumerate(LAWS):
    if law['id'] in existing_ids:
        print(f"[{i+1}/{len(LAWS)}] SKIP (exists): {law['name']}")
        continue

    print(f"[{i+1}/{len(LAWS)}] Generating: {law['name']}...")
    content = generate_law_articles(law)

    if content:
        entry = {
            "id": law['id'],
            "name": law['name'],
            "number": law['number'],
            "year": law['year'],
            "topics": law['topics'],
            "description": content.get("description", ""),
            "key_principles": content.get("key_principles", []),
            "articles": content.get("articles", [])
        }
        new_laws.append(entry)
        article_count = len(content.get("articles", []))
        print(f"  ✓ Done! Generated {article_count} articles")

        # Save after each law
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(new_laws, f, ensure_ascii=False, indent=2)
    else:
        print(f"  ✗ Failed to generate {law['name']}")

    # Respect rate limit (15 RPM = 4 sec between calls)
    if i < len(LAWS) - 1:
        print("  Waiting 5s for rate limit...")
        time.sleep(5)

print("="*60)
print(f"DONE! Total laws in database: {len(new_laws)}")
print(f"Saved to: {output_path}")
