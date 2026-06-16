import sys
import os
import json
import math
import uuid
import time
import hashlib
import threading
from flask import Flask, request, jsonify, send_from_directory, send_file, session
import fitz  # PyMuPDF for PDF processing and rendering
import requests
import google.generativeai as genai
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import sqlite3
try:
    import psycopg2
    from urllib.parse import urlparse
except ImportError:
    psycopg2 = None
    urlparse = None
from werkzeug.security import generate_password_hash, check_password_hash


# Force UTF-8 encoding for stdout/stderr on Windows to prevent UnicodeEncodeError (charmap codec)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get("SECRET_KEY", "secure-legal-key-923812")

# Google Client ID Configuration (Update this in production)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ADMIN_EMAIL = "zidanelarab1@gmail.com" # Default administrator email

# Detect if running on Render Free tier
IS_RENDER = os.environ.get("RENDER", "") == "true"


# Directories configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DEFAULT_LIBRARY_DIR = os.path.join(BASE_DIR, 'library')
INDEX_FILE = os.path.join(DATA_DIR, 'vector_index.json')
REGISTRY_FILE = os.path.join(DATA_DIR, 'documents_registry.json')
LEGISLATION_FILE = os.path.join(DATA_DIR, 'legislation.json')
TEMPLATES_FILE = os.path.join(DATA_DIR, 'templates.json')
COURT_RULINGS_FILE = os.path.join(DATA_DIR, 'court_rulings.json')

for d in [DATA_DIR, DEFAULT_LIBRARY_DIR]:
    os.makedirs(d, exist_ok=True)

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url and psycopg2 is not None:
        # Use DSN directly so ?sslmode=require (Neon.tech) is respected
        conn = psycopg2.connect(dsn=db_url)
        return conn
    else:
        db_path = os.path.join(DATA_DIR, 'users.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    db_url = os.environ.get("DATABASE_URL")
    if db_url and psycopg2 is not None:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
    conn.commit()
    cur.close()
    conn.close()

init_db()


# Default Settings
DEFAULT_SETTINGS = {
    "provider": "gemini",
    "embedding_provider": "gemini",
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "lmstudio_url": "http://localhost:1234/v1",
    "lmstudio_model": "qwen2.5-7b",
    "local_library_path": DEFAULT_LIBRARY_DIR,
    "ocr_enabled": False
}

# --- Thread-safe Global Sync Progress Tracker ---
ocr_disabled_globally = False
sync_lock = threading.Lock()
sync_status = {
    "status": "idle",        # idle, syncing, done, error
    "total_files": 0,
    "processed_files": 0,
    "current_file": "",
    "current_page": 0,
    "total_pages": 0,
    "pages_per_second": 0.0,
    "elapsed_time": 0.0,
    "current_action": "",    # scanning, reading, ocr, embedding
    "logs": []               # list of strings (progress updates)
}

def log_progress(message):
    timestamp = time.strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    with sync_lock:
        sync_status["logs"].append(formatted_msg)
        # Keep logs at reasonable length (last 100 messages)
        if len(sync_status["logs"]) > 100:
            sync_status["logs"].pop(0)
    print(formatted_msg)

# --- Database for Encyclopedia, Rulings & Templates ---

LEGISLATION_DATABASE = [
    {
        "id": "civil",
        "name": "القانون المدني المصري",
        "description": "ينظم المعاملات المالية والالتزامات والحقوق الشخصية والعينية.",
        "articles": [
            {"num": 1, "text": "تسري النصوص التشريعية على جميع المسائل التي تتناولها هذه النصوص في لفظها أو في فحواها. فإذا لم يوجد نص تشريعي يمكن تطبيقه، حكم القاضي بمقتضى العرف، فإذا لم يوجد، فبمقتضى مبادئ الشريعة الإسلامية، فإذا لم توجد، فبمقتضى مبادئ القانون الطبيعي وقواعد العدالة."},
            {"num": 4, "text": "من استعمل حقه استعمالاً مشروعاً لا يكون مسئولاً عما ينشأ عن ذلك من ضرر."},
            {"num": 5, "text": "يكون استعمال الحق غير مشروع في الأحوال الآتية: (أ) إذا لم يقصد به سوى الإضرار بالغير. (ب) إذا كانت المصالح التي يرمي إلى تحقيقها قليلة الأهمية بحيث لا تتناسب البتة مع ما يصيب الغير من ضرر بسببها. (ج) إذا كانت المصالح التي يرمي إلى تحقيقها غير مشروعة."},
            {"num": 147, "text": "العقد شريعة المتعاقدين، فلا يجوز نقضه ولا تعديله إلا باتفاق الطرفين، أو للأسباب التي يقررها القانون. ومع ذلك إذا طرأت حوادث استثنائية عامة لم يكن في الوسع توقعها وترتب على حدوثها أن تنفيذ الالتزام التعاقدي، وإن لم يصبح مستحيلاً، صار مرهقاً للمدين بحيث يهدده بخسارة فادحة، جاز للقاضي تبعاً للظروف وسداً للمصلحة أن يرد الالتزام المرهق إلى الحد المعقول."},
            {"num": 148, "text": "يجب تنفيذ العقد طبقاً لما اشتمل عليه وبطريقة تتفق مع ما يوجبه حسن النية. ولا يقتصر العقد على إلزام المتعاقد بما ورد فيه، بل يتناول أيضاً ما هو من مستلزماته وفقاً للقانون والعرف والعدالة بحسب طبيعة الالتزام."},
            {"num": 163, "text": "كل خطأ سبب ضرراً للغير يلزم من ارتكبه بالتعويض."},
            {"num": 223, "text": "يجوز للمتعاقدين أن يحددا مقدماً قيمة التعويض بالنص عليها في العقد أو في اتفاق لاحق (الشرط الجزائي)."}
        ]
    },
    {
        "id": "penal",
        "name": "قانون العقوبات المصري",
        "description": "يحدد الجرائم والعقوبات المقررة لها وقواعد المسؤولية الجنائية.",
        "articles": [
            {"num": 1, "text": "تسري أحكام هذا القانون على كل من يرتكب في القطر المصري جريمة من الجرائم المنصوص عليها فيه."},
            {"num": 60, "text": "لا تسري أحكام قانون العقوبات على كل فعل ارتكب بنية سليمة عملاً بحق مقرر بمقتضى الشريعة."},
            {"num": 61, "text": "لا عقاب على من ارتكب جريمة ألجاته إلى ارتكابها ضرورة وقاية نفسه أو غيره من خطر جسيم على النفس على وشك الوقوع به أو بغيره ولم يكن لإرادته دخل في حلوله ولا في قدرته منعه بطريقة أخرى."},
            {"num": 302, "text": "يعد قاذفاً كل من أسند لغيره بواسطة إحدى الطرق المبينة بالمادة 171 من هذا القانون أموراً لو كانت صادقة لأوجبت عقاب من أسندت إليه بالعقوبات المقررة لذلك قانوناً أو أوجبت احتقاره عند أهل وطنه."},
            {"num": 336, "text": "يعاقب بالحبس كل من توصل إلى الاستيلاء على نقود أو عروض أو سندات دين أو سندات مخالصة أو أي مال منقول وكان ذلك بالاحتيال لسلب كل ثروة الغير أو بعضها إما باستعمال طرق احتيالية من شأنها إيهام الناس بوجود مشروع كاذب أو واقعة مزورة أو إحداث الأمل بحصول ربح وهمي (جريمة النصب)."}
        ]
    },
    {
        "id": "labor",
        "name": "قانون العمل المصري",
        "description": "ينظم علاقات العمل الفردية والجماعية وحقوق العمال وأصحاب الأعمال.",
        "articles": [
            {"num": 31, "text": "العقد غير محدد المدة هو العقد الذي يبرم لعمل غير مؤقت ولم تحدد له مدة معينة لإنهاائه."},
            {"num": 47, "text": "تكون مدة الإجازة السنوية 21 يوماً بأجر كامل لمن أمضى في الخدمة سنة كاملة، تزاد إلى ثلاثين يوماً متى أمضى العامل في الخدمة عشر سنوات لدى صاحب عمل أو أكثر، كما تكون الإجازة لمدة ثلاثين يوماً لمن تجاوز سن الخمسين."},
            {"num": 69, "text": "لا يجوز فصل العامل إلا إذا ارتكب خطأ جسيماً، ويعتبر من قبيل الخطأ الجسيم الحالات الآتية: (1) إذا ثبت انتحال العامل لشخصية غير صحيحة أو قدم شهادات أو توصيات مزورة. (2) إذا ثبت ارتكاب العامل لخطأ نشأت عنه أضرار جسيمة لصاحب العمل بشرط إبلاغ الجهات المختصة خلال 24 ساعة. (3) إذا تكرر من العامل عدم مراعاة تعليمات سلامة العمل والعمال. (4) إذا تغيب العامل بدون عذر مقبول أكثر من عشرين يوماً متقطعة خلال السنة الواحدة أو أكثر من عشرة أيام متتالية."}
        ]
    }
]

COURT_RULINGS_DATABASE = [
    {
        "id": "1",
        "case_num": "طعن رقم 1450 لسنة 82 قضائية",
        "court": "محكمة النقض - الدائرة المدنية",
        "date": "2015-04-12",
        "category": "مدني",
        "principle": "العقد شريعة المتعاقدين - عدم جواز تدخل القاضي لتعديل شروط العقد إلا في حالات الظروف الطارئة.",
        "details": "المقرر في قضاء محكمة النقض أن العقد شريعة المتعاقدين، فلا يجوز نقضه ولا تعديله إلا باتفاق الطرفين، أو للأسباب التي يقررها القانون، وأن التزام القاضي بالوقوف عند شروط العقد وتفسيرها طبقاً لإرادة المتعاقدين الظاهرة دون تجاوزها يعتبر مبدأ أساسياً من مبادئ استقرار المعاملات."
    },
    {
        "id": "2",
        "case_num": "طعن رقم 568 لسنة 78 قضائية",
        "court": "محكمة النقض - الدائرة الجنائية",
        "date": "2010-11-20",
        "category": "جنائي",
        "principle": "جريمة النصب - الركن المادي - ضرورة استخدام طرق احتيالية لخلق الأمل بربح وهمي أو مشروع كاذب.",
        "details": "المقرر أن مجرد الأقوال والادعاءات الكاذبة مهما بلغت في اتقانها لا تكفي بمجردها لتكوين الطرق الاحتيالية المنصوص عليها في المادة 336 من قانون العقوبات، بل يجب أن يقترن الكذب بمظاهر خارجية أو أعمال مادية تحمل المجني عليه على تصديقه والاستسلام لطلبات الجاني."
    },
    {
        "id": "3",
        "case_num": "طعن رقم 12 لسنة 34 قضائية دستورية",
        "court": "المحكمة الدستورية العليا",
        "date": "2018-06-03",
        "category": "دستوري",
        "principle": "عدم دستورية فرض الحراسة بقرار إداري - حماية الملكية الخاصة وصونها كحق دستوري أصيل.",
        "details": "حيث إن الدستور قد كفل حماية الملكية الخاصة وصونها، وحظر مصادرتها إلا للمصلحة العامة وبمقتضى قانون ومقابل تعويض عادل، فإن فرض الحراسة على أموال المواطنين بقرار إداري دون حكم قضائي يعد اعتداءً على الملكية الخاصة ويخالف أحكام الدستور."
    }
]

LEGAL_TEMPLATES_DATABASE = [
    {
        "id": "contract_sale",
        "title": "عقد بيع شقة سكنية ابتدائي",
        "category": "عقود وملحقاتها",
        "content": """عقد بيع شقة سكنية ابتدائي (خاضع للقانون المدني)

إنه في يوم ............. الموافق    /    / 2026 م
تحرر هذا العقد بين كل من:

أولاً: السيد/ ................................. المقيم في .................................
ويحمل بطاقة رقم قومي: .................................
(ويشار إليه في هذا العقد بصفته: البائـع)

ثانياً: السيد/ ................................. المقيم في .................................
ويحمل بطاقة رقم قومي: .................................
(ويشار إليه في هذا العقد بصفته: المشـتري)

بعد أن أقر الطرفان بأهليتهما للتعاقد والتصرف قانوناً، اتفقا على ما يلي:

البند الأول: موضوع العقد
باع وأسقط وتنازل الطرف الأول (البائع) بكافة الضمانات القانونية والفعلية إلى الطرف الثاني (المشتري) القابل لذلك ما هو الشقة السكنية الكائنة بالعقار رقم (...) بالدور (...) شقة رقم (...) بمدينة/منطقة ............................. وتبلغ مساحتها الإجمالية (...) متر مربع تقريباً.

البند الثاني: الثمن وطريقة الدفع
تم هذا البيع نظير ثمن إجمالي وجزافي وقدره .................... جنيه مصري فقط لا غير، قام الطرف الثاني بدفعه بالكامل للطرف الأول عند التوقيع على هذا العقد ويعتبر توقيع الطرف الأول بمثابة إقرار باستلام المبلغ.

البند الثالث: الملكية
يقر الطرف الأول (البائع) بأن ملكية الشقة المباعة قد آلت إليه بطريق (الشراء بموجب عقد مسجل/الميراث الشرعي/أخرى)، كما يقر بخلو الشقة من كافة الحقوق العينية الأصلية والتبعية.

البند الرابع: المعاينة والاستلام
يقر الطرف الثاني (المشتري) بأنه قد عاين الشقة موضوع هذا العقد المعاينة التامة النافية للجهالة شرعاً وقانوناً، وقبلها بحالتها الراهنة، ويتم تسليم الشقة فور التوقيع على هذا العقد.

البند الخامس: الاختصاص القضائي
تختص المحكمة المدنية الواقع بدائرتها العقار بنظر أي نزاع قد ينشأ بخصوص تفسير أو تنفيذ بنود هذا العقد.

الطرف الأول (البائع)                    الطرف الثاني (المشتري)
الاسم:                                 الاسم:
التوقيع:                               التوقيع:
"""
    },
    {
        "id": "contract_lease",
        "title": "عقد إيجار شقة سكنية طبقاً للقانون رقم 4 لسنة 1996",
        "category": "عقود وملحقاتها",
        "content": """عقد إيجار شقة سكنية (طبقاً لأحكام القانون المدني والقانون رقم 4 لسنة 1996)

إنه في يوم ............. الموافق    /    / 2026 م
تحرر هذا العقد بين كل من:

أولاً: السيد/ ................................. المقيم في ................................. (المؤجـر)
ثانياً: السيد/ ................................. المقيم في ................................. (المستأجـر)

اتفق الطرفان على ما يلي:

البند الأول: العين المؤجرة
بموجب هذا العقد قام الطرف الأول بتأجير الشقة رقم (...) بالدور (...) بالعقار رقم (...) بالشارع ..................... لغرض السكن العائلي فقط.

البند الثاني: مدة الإيجار
مدة هذا الإيجار هي (...) تبدأ من    /    / 2026 م وتنتهي في    /    / 2026 م، ويلتزم المستأجر بتسليم العين فور انتهاء المدة دون حاجة لتنبيه أو إنذار.

البند الثالث: القيمة الإيجارية
الأجرة المتفق عليها هي مبلغ قدره ............... جنيه مصري شهرياً، يلتزم المستأجر بدفعه للمؤجر مقدماً في الأسبوع الأول من كل شهر مقابل إيصال موقع.

البند الرابع: التأمين
قام المستأجر بدفع مبلغ وقدره ................ جنيه كتأمين لا يرد إلا عند انتهاء العقد وتسليم العين خالية من التلفيات وسداد كافة الفواتير (كهرباء، مياه، غاز).

المؤجـر                                المستأجـر
التوقيع:                               التوقيع:
"""
    },
    {
        "id": "lawsuit_validity",
        "title": "صحيفة دعوى صحة ونفاذ عقد بيع ابتدائي",
        "category": "صحف دعاوى وطلبات",
        "content": """صحيفة دعوى صحة ونفاذ عقد بيع

إنه في يوم ............. الموافق    /    / 2026 م
بناءً على طلب السيد/ ................................. المقيم في .................................
ومحله المختار مكتب الأستاذ/ ................................. المحامي بـ .................................

أنا ................................. محضر محكمة ................................. قد انتقلت وأعلنت:
السيد/ ................................. المقيم في ................................. مخاطباً مع/ .................................

الموضوع
بموجب عقد بيع ابتدائي مؤرخ    /    / 2026 م اشترى الطالب من المعلن إليه ما هو الشقة السكنية رقم (...) بالعقار رقم (...) بالدور (...) الكائنة بـ ................................. لقاء ثمن إجمالي مدفوع قدره ..................... جنيه مصري.

وحيث يهم الطالب إقامة هذه الدعوى للحكم بصحة ونفاذ عقد البيع المذكور لتسجيل الحكم ونقل الملكية رسمياً.

بناءً عليه
أنا المحضر سالف الذكر قد أعلنت المعلن إليه بصورة من هذه الصحيفة وكلفته بالحضور أمام محكمة ..................... الكلية الكائن مقرها بـ ..................... بجلستها التي ستنعقد يوم ............. الموافق    /    / 2026 من الساعة الثامنة صباحاً ليسمع الحكم بصحة ونفاذ عقد البيع الابتدائي المؤرخ    /    / 2026 وإلزامه بالمصاريف وأتعاب المحاماة.

ولأجل العلم،،
"""
    }
]

# --- General System Helpers ---

def calculate_file_hash(file_path):
    hash_md5 = hashlib.md5()
    try:
        # Hashing only up to first 10MB of the file is extremely fast
        # and 100% sufficient for identifying duplicate legal books.
        with open(file_path, "rb") as f:
            chunk = f.read(1024 * 1024 * 10)  # Read 10MB
            hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print(f"Error calculating hash for {file_path}: {e}")
        return None

def load_legislation():
    if os.path.exists(LEGISLATION_FILE):
        try:
            with open(LEGISLATION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading legislation.json: {e}")
    return LEGISLATION_DATABASE

def load_court_rulings():
    if os.path.exists(COURT_RULINGS_FILE):
        try:
            with open(COURT_RULINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading court_rulings.json: {e}")
    return COURT_RULINGS_DATABASE

def load_templates():
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading templates.json: {e}")
    return LEGAL_TEMPLATES_DATABASE

def get_user_data_dir(user_id=None):
    if not user_id:
        return DATA_DIR
    user_hash = hashlib.md5(user_id.lower().strip().encode('utf-8')).hexdigest()
    user_dir = os.path.join(DATA_DIR, 'users', user_hash)
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, 'uploads'), exist_ok=True)
    return user_dir

def get_user_settings_file(user_id=None):
    return os.path.join(get_user_data_dir(user_id), 'settings.json')

def get_user_cases_file(user_id=None):
    return os.path.join(get_user_data_dir(user_id), 'cases.json')

def get_user_chat_file(user_id=None):
    return os.path.join(get_user_data_dir(user_id), 'chat_history.json')

def load_chat_sessions(user_id=None):
    chat_file = get_user_chat_file(user_id)
    if os.path.exists(chat_file):
        try:
            with open(chat_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_chat_sessions(sessions, user_id=None):
    chat_file = get_user_chat_file(user_id)
    with open(chat_file, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)

from functools import wraps

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "غير مصرح. يرجى تسجيل الدخول أولاً."}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id or user_id.lower().strip() != ADMIN_EMAIL.lower().strip():
            return jsonify({"error": "غير مصرح. هذه الصلاحية مخصصة للمسؤول فقط."}), 403
        return f(*args, **kwargs)
    return decorated_function


def load_settings(user_id=None):
    settings_file = get_user_settings_file(user_id)
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in settings:
                        settings[k] = v
                return settings
        except Exception:
            pass
    if user_id is not None:
        return load_settings(None)
    return DEFAULT_SETTINGS.copy()

def save_settings(settings, user_id=None):
    settings_file = get_user_settings_file(user_id)
    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

# --- SQLite Vector Database Integration ---
import numpy as np

GLOBAL_EMBEDDINGS = None # numpy array of shape (N, 768)
GLOBAL_METADATA = None # list of dicts
GLOBAL_INDEX_LOCK = threading.Lock()

def serialize_embedding(embedding_list):
    return np.array(embedding_list, dtype=np.float32).tobytes()

def deserialize_embedding(blob):
    return np.frombuffer(blob, dtype=np.float32).tolist()

def migrate_json_to_sqlite_if_needed():
    db_path = os.path.join(DATA_DIR, 'vector_index.db')
    json_path = os.path.join(DATA_DIR, 'vector_index.json')
    
    if os.path.exists(db_path):
        return
        
    if not os.path.exists(json_path):
        return
        
    print("Migrating vector_index.json to SQLite database...", flush=True)
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                doc_name TEXT,
                page INTEGER,
                text TEXT,
                embedding BLOB
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON document_chunks(doc_id)")
        conn.commit()
        
        with open(json_path, 'r', encoding='utf-8') as f:
            index_list = json.load(f)
            
        print(f"Loaded {len(index_list)} chunks from JSON. Inserting into SQLite...", flush=True)
        
        to_insert = []
        for chunk in index_list:
            emb_blob = np.array(chunk["embedding"], dtype=np.float32).tobytes()
            to_insert.append((
                chunk["doc_id"],
                chunk["doc_name"],
                chunk["page"],
                chunk["text"],
                emb_blob
            ))
            
        if to_insert:
            for i in range(0, len(to_insert), 5000):
                batch = to_insert[i:i+5000]
                cur.executemany("""
                    INSERT INTO document_chunks (doc_id, doc_name, page, text, embedding)
                    VALUES (?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
                print(f"  - Migrated {i + len(batch)} / {len(to_insert)} chunks...", flush=True)
                
        cur.close()
        conn.close()
        print("Migration to SQLite completed successfully!", flush=True)
        
        try:
            bak_path = json_path + ".bak"
            if os.path.exists(bak_path):
                os.remove(bak_path)
            os.rename(json_path, bak_path)
            print(f"Renamed {json_path} to {bak_path}", flush=True)
        except Exception as rename_err:
            print(f"Could not rename JSON file: {rename_err}", flush=True)
            
    except Exception as e:
        print(f"Error migrating JSON to SQLite: {e}", flush=True)

# Run migration at load time
migrate_json_to_sqlite_if_needed()

# Vector similarity search using numpy array cache
def load_vector_db():
    global GLOBAL_EMBEDDINGS, GLOBAL_METADATA
    if GLOBAL_EMBEDDINGS is not None:
        return GLOBAL_EMBEDDINGS, GLOBAL_METADATA
        
    with GLOBAL_INDEX_LOCK:
        if GLOBAL_EMBEDDINGS is not None:
            return GLOBAL_EMBEDDINGS, GLOBAL_METADATA
            
        db_path = os.path.join(DATA_DIR, 'vector_index.db')
        if not os.path.exists(db_path):
            download_url = os.environ.get("VECTOR_INDEX_URL")
            if download_url:
                print(f"vector_index.db not found. Downloading from {download_url}...", flush=True)
                try:
                    import urllib.request
                    # Create data directory if missing
                    os.makedirs(DATA_DIR, exist_ok=True)
                    
                    # Set a user-agent to bypass basic cloud blocks
                    req = urllib.request.Request(
                        download_url, 
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                    )
                    with urllib.request.urlopen(req) as response, open(db_path, 'wb') as out_file:
                        shutil_copy = True
                        # Use shutil to copy response stream to file
                        import shutil
                        shutil.copyfileobj(response, out_file)
                    print("Vector index database downloaded successfully!", flush=True)
                except Exception as dl_err:
                    print(f"Error downloading vector_index.db: {dl_err}", flush=True)
                    
        if not os.path.exists(db_path):
            GLOBAL_EMBEDDINGS = np.empty((0, 768), dtype=np.float32)
            GLOBAL_METADATA = []
            return GLOBAL_EMBEDDINGS, GLOBAL_METADATA
            
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT id, doc_id, doc_name, page, embedding FROM document_chunks")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            
            if not rows:
                GLOBAL_EMBEDDINGS = np.empty((0, 768), dtype=np.float32)
                GLOBAL_METADATA = []
                return GLOBAL_EMBEDDINGS, GLOBAL_METADATA
                
            embeddings_list = []
            metadata_list = []
            
            # Detect embedding dimension dynamically from the first row
            first_emb = np.frombuffer(rows[0][4], dtype=np.float32)
            emb_dim = len(first_emb) if len(first_emb) > 0 else 768
            print(f"Detected Vector DB embedding dimension: {emb_dim}", flush=True)
            
            for row in rows:
                row_id, doc_id, doc_name, page, emb_blob = row
                emb = np.frombuffer(emb_blob, dtype=np.float32)
                if len(emb) == emb_dim:
                    embeddings_list.append(emb)
                    metadata_list.append({
                        "id": row_id,
                        "doc_id": doc_id,
                        "doc_name": doc_name,
                        "page": page
                    })
            
            if embeddings_list:
                GLOBAL_EMBEDDINGS = np.vstack(embeddings_list)
                GLOBAL_METADATA = metadata_list
            else:
                GLOBAL_EMBEDDINGS = np.empty((0, emb_dim), dtype=np.float32)
                GLOBAL_METADATA = []
                
            print(f"Vector DB loaded: {GLOBAL_EMBEDDINGS.shape[0]} vectors with dimension {emb_dim}.", flush=True)
            return GLOBAL_EMBEDDINGS, GLOBAL_METADATA
        except Exception as e:
            print(f"Error loading Vector DB: {e}", flush=True)
            GLOBAL_EMBEDDINGS = np.empty((0, 768), dtype=np.float32)
            GLOBAL_METADATA = []
            return GLOBAL_EMBEDDINGS, GLOBAL_METADATA

def search_vector_db(query_vector, top_k=4, min_similarity=0.2):
    embeddings, metadata = load_vector_db()
    if embeddings.shape[0] == 0:
        return []
        
    qv = np.array(query_vector, dtype=np.float32)
    qv_norm = np.linalg.norm(qv)
    if qv_norm > 0:
        qv = qv / qv_norm
        
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized_embeddings = embeddings / norms
    
    similarities = np.dot(normalized_embeddings, qv)
    
    top_indices = np.argsort(similarities)[::-1][:top_k]
    
    results = []
    db_path = os.path.join(DATA_DIR, 'vector_index.db')
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        for idx in top_indices:
            score = float(similarities[idx])
            if score < min_similarity:
                continue
                
            meta = metadata[idx]
            row_id = meta["id"]
            
            cur.execute("SELECT text FROM document_chunks WHERE id = ?", (row_id,))
            row = cur.fetchone()
            if row:
                text = row[0]
                results.append({
                    "doc_id": meta["doc_id"],
                    "doc_name": meta["doc_name"],
                    "page": meta["page"],
                    "text": text,
                    "score": score
                })
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching matched texts: {e}", flush=True)
        
    return results

# Load Vector Index (Global Shared Library)
def load_index(user_id=None):
    db_path = os.path.join(DATA_DIR, 'vector_index.db')
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT doc_id, doc_name, page, text, embedding FROM document_chunks")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        index_list = []
        for row in rows:
            doc_id, doc_name, page, text, emb_blob = row
            embedding = np.frombuffer(emb_blob, dtype=np.float32).tolist()
            index_list.append({
                "doc_id": doc_id,
                "doc_name": doc_name,
                "page": page,
                "text": text,
                "embedding": embedding
            })
        return index_list
    except Exception as e:
        print(f"Error in load_index from SQLite: {e}", flush=True)
        return []

# Save Vector Index (Global Shared Library)
def save_index(index_list, user_id=None):
    db_path = os.path.join(DATA_DIR, 'vector_index.db')
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                doc_name TEXT,
                page INTEGER,
                text TEXT,
                embedding BLOB
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON document_chunks(doc_id)")
        conn.commit()
        
        doc_ids_in_list = list(set(chunk["doc_id"] for chunk in index_list))
        
        if doc_ids_in_list:
            placeholders = ",".join("?" for _ in doc_ids_in_list)
            cur.execute(f"DELETE FROM document_chunks WHERE doc_id NOT IN ({placeholders})", doc_ids_in_list)
        else:
            cur.execute("DELETE FROM document_chunks")
            
        cur.execute("SELECT DISTINCT doc_id FROM document_chunks")
        existing_doc_ids = set(row[0] for row in cur.fetchall())
        
        to_insert = []
        for chunk in index_list:
            doc_id = chunk["doc_id"]
            if doc_id not in existing_doc_ids:
                emb_blob = serialize_embedding(chunk["embedding"])
                to_insert.append((
                    doc_id,
                    chunk["doc_name"],
                    chunk["page"],
                    chunk["text"],
                    emb_blob
                ))
                
        if to_insert:
            cur.executemany("""
                INSERT INTO document_chunks (doc_id, doc_name, page, text, embedding)
                VALUES (?, ?, ?, ?, ?)
            """, to_insert)
            
        conn.commit()
        cur.close()
        conn.close()
        
        global GLOBAL_EMBEDDINGS, GLOBAL_METADATA
        GLOBAL_EMBEDDINGS = None
        GLOBAL_METADATA = None
        
        print(f"Successfully saved index to SQLite. Deleted unused docs. Inserted {len(to_insert)} new chunks.", flush=True)
    except Exception as e:
        print(f"Error saving index to SQLite: {e}", flush=True)

# Load/Save Documents Registry (Global Shared Library)
def load_registry(user_id=None):
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_registry(registry, user_id=None):
    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(registry, f, ensure_ascii=False, indent=4)

_local_transformer = None
_local_transformer_lock = threading.Lock()

def get_local_transformer():
    global _local_transformer
    if _local_transformer is None:
        with _local_transformer_lock:
            if _local_transformer is None:
                from sentence_transformers import SentenceTransformer
                # Use a specific multilingual offline model
                _local_transformer = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    return _local_transformer

# API Key rotation helper
def get_gemini_api_keys(settings):
    raw_key = settings.get("gemini_api_key", "")
    if not raw_key:
        raw_key = os.environ.get("GEMINI_API_KEY", "")
    if not raw_key:
        return []
    import re
    # Split keys by comma, semicolon, newline or space
    keys = [k.strip() for k in re.split(r'[,;\n\s]+', raw_key) if k.strip()]
    return keys

# Global rotation state
_current_key_index = 0
_key_lock = threading.Lock()

def execute_with_gemini_retry(settings, api_func, *args, **kwargs):
    global _current_key_index
    keys = get_gemini_api_keys(settings)
    if not keys:
        raise ValueError("مفتاح API الخاص بـ Gemini غير مدخل في الإعدادات.")
        
    num_keys = len(keys)
    last_err = None
    
    with _key_lock:
        start_idx = _current_key_index % num_keys if num_keys > 0 else 0
        
    for attempt in range(num_keys):
        current_idx = (start_idx + attempt) % num_keys
        key = keys[current_idx]
        
        try:
            genai.configure(api_key=key)
            result = api_func(*args, **kwargs)
            # Update active index to the successful key
            with _key_lock:
                _current_key_index = current_idx
            return result
        except Exception as e:
            err_str = str(e)
            print(f"Error executing Gemini API with key index {current_idx}: {err_str}")
            last_err = e
            # Rotate key on 429 quota exhaustion or API errors
            continue
            
    # If all keys failed, raise the last error
    raise last_err if last_err else ValueError("فشلت كافة مفاتيح Gemini API المتاحة.")

# Vector similarity calculation
def cosine_similarity(v1, v2):
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)

# Generate embedding vector
def get_embedding(text, settings):
    provider = settings.get("embedding_provider", "local")
    if IS_RENDER:
        provider = "gemini"

    
    if provider == "local":
        model = get_local_transformer()
        embedding = model.encode(text).tolist()
        return embedding
        
    elif provider == "gemini":
        def call_embed():
            response = genai.embed_content(
                model="models/gemini-embedding-001",
                content=text,
                task_type="retrieval_query"
            )
            return response['embedding']
        return execute_with_gemini_retry(settings, call_embed)
        
    elif provider == "lmstudio":
        url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
        embed_endpoint = f"{url}/embeddings"
        try:
            response = requests.post(
                embed_endpoint,
                headers={"Content-Type": "application/json"},
                json={
                    "input": text,
                    "model": settings.get("lmstudio_model", "qwen2.5-7b")
                },
                timeout=15
            )
            response.raise_for_status()
            res_json = response.json()
            if "data" in res_json and len(res_json["data"]) > 0:
                return res_json["data"][0]["embedding"]
            raise ValueError("تنسيق استجابة Embedding من LM Studio غير معروف.")
        except Exception as e:
            print(f"Embedding failed: {e}")
            raise ValueError(f"فشل الاتصال بـ LM Studio: {e}")

# Generate batch embedding vectors
def get_embeddings_batch(texts, settings):
    if not texts:
        return []
    provider = settings.get("embedding_provider", "local")
    if IS_RENDER:
        provider = "gemini"

    
    if provider == "local":
        model = get_local_transformer()
        embeddings = model.encode(texts).tolist()
        return embeddings
        
    elif provider == "gemini":
        def call_embed_batch(batch):
            response = genai.embed_content(
                model="models/gemini-embedding-001",
                content=batch,
                task_type="retrieval_query"
            )
            return response['embedding']
            
        batch_size = 100
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            embeddings = execute_with_gemini_retry(settings, call_embed_batch, batch_texts)
            all_embeddings.extend(embeddings)
        return all_embeddings
        
    elif provider == "lmstudio":
        url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
        embed_endpoint = f"{url}/embeddings"
        try:
            response = requests.post(
                embed_endpoint,
                headers={"Content-Type": "application/json"},
                json={
                    "input": texts,
                    "model": settings.get("lmstudio_model", "qwen2.5-7b")
                },
                timeout=30
            )
            response.raise_for_status()
            res_json = response.json()
            if "data" in res_json:
                data_sorted = sorted(res_json["data"], key=lambda x: x.get("index", 0))
                return [item["embedding"] for item in data_sorted]
            raise ValueError("تنسيق استجابة Embedding من LM Studio غير معروف.")
        except Exception as e:
            print(f"Batch embedding in LM Studio failed, falling back to sequential: {e}")
            all_embeddings = []
            for text in texts:
                all_embeddings.append(get_embedding(text, settings))
            return all_embeddings


# Text Chunking Helper
def split_text_into_chunks(text, chunk_size=700, overlap=100):
    chunks = []
    if not text:
        return chunks
    
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            for i in range(end, max(start, end - 80), -1):
                if text[i] in ['.', '\n', '،']:
                    end = i + 1
                    break
        chunks.append(text[start:end].strip())
        start += (end - start) - overlap
        if (end - start) <= overlap:
            break
    return [c for c in chunks if len(c) > 10]

# Extract and chunk single PDF (Updating thread status in real-time)
def process_pdf_file(file_path, filename, settings, start_time=None, total_pages_ref=None):
    if start_time is None:
        start_time = time.time()
    if total_pages_ref is None:
        total_pages_ref = [0]
    global ocr_disabled_globally
    import concurrent.futures
    doc = fitz.open(file_path)
    total_pages = len(doc)
    
    with sync_lock:
        sync_status["total_pages"] = total_pages
        sync_status["current_page"] = 0
        
    log_progress(f"تحليل كتاب: '{filename}' (إجمالي الصفحات: {total_pages})")
    
    # Check if OCR is enabled in settings
    ocr_enabled = settings.get("ocr_enabled", False)
    
    # Step 1: Fast local scan of all pages (Extract text or render to image)
    pages_data = [] # List of dicts: {"page_num": int, "text": str, "img_bytes": bytes/None}
    
    for page_idx in range(total_pages):
        page = doc[page_idx]
        text = page.get_text()
        img_bytes = None
        
        # If scanned and OCR enabled, render to JPG bytes
        if ocr_enabled and len(text.strip()) < 100:
            pix = page.get_pixmap(dpi=100)
            img_bytes = pix.tobytes("jpg")
            
        pages_data.append({
            "page_num": page_idx + 1,
            "text": text,
            "img_bytes": img_bytes
        })
        
    doc.close() # Close document immediately
    
    ocr_tasks = [p for p in pages_data if p["img_bytes"] is not None]
    
    # Step 2: Run OCR in parallel for scanned pages
    provider = settings.get("provider", "gemini")
    api_key = settings.get("gemini_api_key")
    
    if ocr_tasks and provider == "gemini" and api_key and ocr_enabled and not ocr_disabled_globally:
        log_progress(f"    - تم كشف {len(ocr_tasks)} صفحة ممسوحة ضوئياً. تشغيل الـ OCR المتوازي (8 خيوط معالجة بالتزامن)...")
        
        def perform_ocr(task):
            global ocr_disabled_globally
            if ocr_disabled_globally:
                return
                
            page_num = task["page_num"]
            img_bytes = task["img_bytes"]
            
            with sync_lock:
                sync_status["current_action"] = "ocr"
                sync_status["current_page"] = page_num
            
            ocr_text = ""
            def call_ocr():
                model = genai.GenerativeModel("gemini-2.5-flash")
                prompt = "هذه الصورة هي صفحة ممسوحة ضوئياً من كتاب قانوني عربي. قم باستخراج النص العربي الكامل والواضح الموجود في هذه الصورة بدقة شديدة وبدون أي تعليق أو إضافات منك. اكتب النص فقط كما هو لتتم فهرسته."
                response = model.generate_content([
                    {"mime_type": "image/jpeg", "data": img_bytes},
                    prompt
                ])
                return response.text.strip()
                
            try:
                ocr_text = execute_with_gemini_retry(settings, call_ocr)
            except Exception as api_err:
                err_str = str(api_err)
                log_progress(f"    - الصفحة {page_num}: فشل الـ OCR: {api_err}")
                if "404" in err_str or "not found" in err_str.lower() or "API_KEY_INVALID" in err_str or "not valid" in err_str.lower():
                    log_progress(f"    - خطأ فادح في مفاتيح الـ API المتاحة. سيتم إيقاف الـ OCR مؤقتاً لتسريع المزامنة.")
                    ocr_disabled_globally = True
            
            if ocr_text:
                task["text"] = ocr_text
                log_progress(f"    - الصفحة {page_num}: نجح الـ OCR بالتوازي. (استخلاص {len(ocr_text)} حرف)")
            else:
                log_progress(f"    - الصفحة {page_num}: فشل الـ OCR بالتوازي أو تم إرجاع نص فارغ.")
                
            with sync_lock:
                total_pages_ref[0] += 1
                # Update speed metrics live
                elapsed = time.time() - start_time
                if elapsed > 0:
                    sync_status["elapsed_time"] = elapsed
                    sync_status["pages_per_second"] = round(total_pages_ref[0] / elapsed, 1)
                    
        # Run with ThreadPoolExecutor
        # Use 8 workers for fast parallel OCR
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            executor.map(perform_ocr, ocr_tasks)
            
    # For non-scanned pages, we need to update the total processed pages and speed metrics too!
    for p in pages_data:
        if p["img_bytes"] is None:
            with sync_lock:
                total_pages_ref[0] += 1
                elapsed = time.time() - start_time
                if elapsed > 0:
                    sync_status["elapsed_time"] = elapsed
                    sync_status["pages_per_second"] = round(total_pages_ref[0] / elapsed, 1)
                    
    # Reconstruct pages_text list
    pages_text = [(p["page_num"], p["text"]) for p in pages_data]
    
    # Split text into chunks
    chunks = []
    for page_num, text in pages_text:
        if not text.strip():
            continue
        page_chunks = split_text_into_chunks(text)
        for idx, chunk in enumerate(page_chunks):
            chunks.append({
                "page": page_num,
                "text": chunk
            })
    return chunks, total_pages

# --- Background Sync Thread Worker ---

def sync_library_thread_worker(settings):
    global ocr_disabled_globally
    ocr_disabled_globally = False
    lib_path = settings.get("local_library_path", DEFAULT_LIBRARY_DIR)
    
    with sync_lock:
        sync_status["status"] = "syncing"
        sync_status["logs"] = []
        sync_status["processed_files"] = 0
        sync_status["total_files"] = 0
        sync_status["pages_per_second"] = 0.0
        sync_status["elapsed_time"] = 0.0
        sync_status["current_action"] = "scanning"
        
    log_progress("بدء فحص ومزامنة المجلد المحلي...")
    
    if not os.path.exists(lib_path):
        log_progress(f"[خطأ] المجلد غير موجود: {lib_path}")
        with sync_lock:
            sync_status["status"] = "error"
        return
        
    try:
        # Verify API key if using gemini
        if settings.get("provider") == "gemini":
            api_key = settings.get("gemini_api_key")
            is_valid_prefix = api_key and (api_key.startswith("AIzaSy") or api_key.startswith("AQ"))
            if not api_key or api_key.strip() == "" or api_key == "test_key" or not is_valid_prefix:
                log_progress("[خطأ فادح] مفتاح Gemini API غير صالح أو غير مدخل. يرجى الحصول على مفتاح صحيح يبدأ بـ 'AIzaSy' أو 'AQ' من Google AI Studio وضبطه في 'إعدادات المحرك' بالأسفل.")
                with sync_lock:
                    sync_status["status"] = "error"
                return

        registry = load_registry()
        index = load_index()
        
        # Check if the existing index has a different embedding dimension than the current provider
        if index and len(index[0].get("embedding", [])) != len(get_embedding("اختبار", settings)):
            log_progress("[تنبيه] تم كشف تغيير في مزود خدمة الـ Embedding (أبعاد المتجهات غير متطابقة). جاري إعادة بناء الفهرس تلقائياً لتجنب المشاكل...")
            registry = {}
            index = []
            save_index(index)
            save_registry(registry)
        
        # Scan folder recursively for PDFs (including all subfolders)
        files_in_folder = []
        for root_dir, sub_dirs, files in os.walk(lib_path):
            for file in files:
                if file.lower().endswith('.pdf'):
                    rel_path = os.path.relpath(os.path.join(root_dir, file), lib_path)
                    files_in_folder.append(rel_path)
        total_files = len(files_in_folder)
        
        with sync_lock:
            sync_status["total_files"] = total_files
            
        log_progress(f"تم العثور على {total_files} ملفات PDF في مجلد المكتبة (بما يشمل المجلدات الفرعية).")
        
        # Clean up deleted files from index and registry FIRST
        deleted_count = 0
        keys_to_remove = []
        for reg_filename, info in registry.items():
            # Check if file has been deleted from folder
            path_str = info.get("path") or ""
            if reg_filename not in files_in_folder and (path_str.startswith(lib_path) or not os.path.exists(path_str)):
                old_id = info.get("doc_id")
                index = [item for item in index if item['doc_id'] != old_id]
                keys_to_remove.append(reg_filename)
                log_progress(f"[-] تم حذف '{reg_filename}' من الفهرس لحذفه من المجلد.")
                deleted_count += 1
                
        for k in keys_to_remove:
            del registry[k]
            
        if deleted_count > 0:
            save_index(index)
            save_registry(registry)
        
        if total_files == 0:
            log_progress("[تحذير] لم يتم العثور على أي ملفات PDF في مجلد المكتبة. تم إيقاف المزامنة تلقائياً لحفظ الفهارس الحالية.")
            with sync_lock:
                sync_status["status"] = "done"
            return
        
        indexed_count = 0
        skipped_count = 0
        error_count = 0
        active_filenames = []
        
        start_time = time.time()
        total_pages_processed = [0]  # wrapped in list for mutable reference in inner loops
        
        for idx, filename in enumerate(files_in_folder):
            active_filenames.append(filename)
            file_path = os.path.join(lib_path, filename)
            stat = os.stat(file_path)
            file_size = stat.st_size
            last_modified = stat.st_mtime
            
            with sync_lock:
                sync_status["current_file"] = filename
                sync_status["processed_files"] = idx
                sync_status["current_action"] = "reading"
            
            # Check if file has changed
            reg_entry = registry.get(filename)
            if reg_entry and reg_entry.get("file_size") == file_size and reg_entry.get("last_modified") == last_modified:
                skipped_count += 1
                log_progress(f"الكتاب '{filename}' مؤرشف مسبقاً وبدون تعديلات. تم التخطي.")
                continue
                
            # Calculate file hash to detect duplicates
            file_hash = calculate_file_hash(file_path)
            
            # Check for duplicate content (same hash) in the registry
            duplicate_found = False
            if file_hash:
                for reg_name, reg_val in registry.items():
                    if reg_name != filename and reg_val.get("file_hash") == file_hash:
                        if reg_name in files_in_folder:
                            log_progress(f"[تخطي تكرار] الكتاب '{filename}' متطابق في المحتوى تماماً مع كتاب آخر '{reg_name}'. تم التخطي.")
                            duplicate_found = True
                            break
            
            if duplicate_found:
                skipped_count += 1
                continue

            # If changed/new, clean up old index records
            if reg_entry:
                old_id = reg_entry.get("doc_id")
                index = [item for item in index if item['doc_id'] != old_id]
                log_progress(f"تم العثور على تعديل في '{filename}'. جاري إعادة معالجته...")
                
            try:
                doc_id = str(uuid.uuid4())
                chunks, pages_count = process_pdf_file(file_path, filename, settings, start_time, total_pages_processed)
                
                if not chunks:
                    log_progress(f"[تحذير] لم يتم العثور على نصوص في '{filename}'.")
                    skipped_count += 1
                    continue
                    
                log_progress(f"جاري توليد التضمينات (Embeddings) لـ {len(chunks)} جزء دفعة واحدة...")
                with sync_lock:
                    sync_status["current_action"] = "embedding"
                    
                chunk_texts = [c["text"] for c in chunks]
                embeddings = get_embeddings_batch(chunk_texts, settings)
                
                indexed_chunks = 0
                for chunk_idx, chunk in enumerate(chunks):
                    chunk["doc_id"] = doc_id
                    chunk["doc_name"] = filename
                    chunk["embedding"] = embeddings[chunk_idx]
                    index.append(chunk)
                    indexed_chunks += 1
                    
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
                
                # Save progress incrementally to disk after each file to prevent data loss on reloads
                save_index(index)
                save_registry(registry)
                
                indexed_count += 1
                log_progress(f"[نجاح] تم حفظ الفهرس التراكمي لكتاب '{filename}' بنجاح.")
                
            except Exception as e:
                error_count += 1
                log_progress(f"[خطأ] فشل معالجة '{filename}': {str(e)}")
                
        # End of file loop
        
        with sync_lock:
            sync_status["processed_files"] = total_files
            sync_status["status"] = "done"
            sync_status["elapsed_time"] = time.time() - start_time
            
        log_progress(f"المزامنة مكتملة! تمت إضافة {indexed_count} كتب وتخطي {skipped_count} كتب. الأخطاء: {error_count}.")
        
    except Exception as e:
        log_progress(f"[خطأ فادح في المزامنة] {str(e)}")
        with sync_lock:
            sync_status["status"] = "error"

# --- Flask Web API Endpoints ---

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# Expose public config to frontend (e.g. Google Client ID)
@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        "google_client_id": GOOGLE_CLIENT_ID
    })

# --- Auth Routes ---
@app.route('/api/auth/google', methods=['POST'])
def google_auth():
    try:
        data = request.json or {}
        token = data.get('token')
        if not token:
            return jsonify({"error": "Missing token"}), 400
            
        try:
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), GOOGLE_CLIENT_ID)
            email = idinfo['email']
            name = idinfo.get('name', email.split('@')[0])
            picture = idinfo.get('picture', '')
        except Exception as oauth_err:
            if not GOOGLE_CLIENT_ID or GOOGLE_CLIENT_ID == "":
                print(f"OAuth verification bypassed/failed: {oauth_err}")
                if '@' in token:
                    email = token
                    name = token.split('@')[0]
                    picture = ''
                else:
                    return jsonify({"error": f"OAuth verification failed: {str(oauth_err)}"}), 401
            else:
                return jsonify({"error": f"OAuth verification failed: {str(oauth_err)}"}), 401
        
        session['user_id'] = email
        session['email'] = email
        session['name'] = name
        session['picture'] = picture
        
        # Initialize user directory
        get_user_data_dir(email)
        
        return jsonify({
            "status": "success",
            "user": {
                "email": email,
                "name": name,
                "picture": picture,
                "is_admin": email.lower().strip() == ADMIN_EMAIL.lower().strip()
            }
        })
    except Exception as e:
        print(f"Auth error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/auth/signup', methods=['POST'])
def auth_signup():
    try:
        data = request.json or {}
        name = data.get('name', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not name or not email or not password:
            return jsonify({"error": "جميع الحقول مطلوبة."}), 400
            
        if '@' not in email:
            return jsonify({"error": "البريد الإلكتروني غير صالح."}), 400
            
        password_hash = generate_password_hash(password)
        user_id = str(uuid.uuid4())
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        else:
            cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "هذا البريد الإلكتروني مسجل بالفعل."}), 400
            
        if db_url:
            cur.execute(
                "INSERT INTO users (id, name, email, password_hash) VALUES (%s, %s, %s, %s)",
                (user_id, name, email, password_hash)
            )
        else:
            cur.execute(
                "INSERT INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, email, password_hash, created_at)
            )
            
        conn.commit()
        cur.close()
        conn.close()
        
        session['user_id'] = email
        session['email'] = email
        session['name'] = name
        session['picture'] = ''
        
        get_user_data_dir(email)
        
        return jsonify({
            "status": "success",
            "user": {
                "email": email,
                "name": name,
                "picture": '',
                "is_admin": email.lower().strip() == ADMIN_EMAIL.lower().strip()
            }
        }), 201
        
    except Exception as e:
        print(f"Signup error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء إنشاء الحساب: {str(e)}"}), 500


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    try:
        data = request.json or {}
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"error": "البريد الإلكتروني وكلمة المرور مطلوبان."}), 400
            
        conn = get_db_connection()
        cur = conn.cursor()
        
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            cur.execute("SELECT name, password_hash FROM users WHERE email = %s", (email,))
        else:
            cur.execute("SELECT name, password_hash FROM users WHERE email = ?", (email,))
            
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row or not check_password_hash(row[1], password):
            return jsonify({"error": "البريد الإلكتروني أو كلمة المرور غير صحيحة."}), 401
            
        name = row[0]
        
        session['user_id'] = email
        session['email'] = email
        session['name'] = name
        session['picture'] = ''
        
        get_user_data_dir(email)
        
        return jsonify({
            "status": "success",
            "user": {
                "email": email,
                "name": name,
                "picture": '',
                "is_admin": email.lower().strip() == ADMIN_EMAIL.lower().strip()
            }
        })
        
    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء تسجيل الدخول: {str(e)}"}), 500


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"logged_in": False}), 200
    return jsonify({
        "logged_in": True,
        "user": {
            "email": session.get('email'),
            "name": session.get('name'),
            "picture": session.get('picture'),
            "is_admin": session.get('email', '').lower().strip() == ADMIN_EMAIL.lower().strip()
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({"status": "success", "message": "تم تسجيل الخروج بنجاح."})

# --- Chat History Management Routes ---
@app.route('/api/chat/history', methods=['GET'])
@login_required
def get_chat_history():
    user_id = session.get('user_id')
    sessions = load_chat_sessions(user_id)
    return jsonify(sessions)

@app.route('/api/chat/history', methods=['POST'])
@login_required
def update_chat_history():
    user_id = session.get('user_id')
    data = request.json or {}
    session_id = data.get("id")
    title = data.get("title", "")
    messages = data.get("messages", [])
    
    if not session_id:
        return jsonify({"error": "معرف الجلسة مطلوب"}), 400
        
    sessions = load_chat_sessions(user_id)
    found = False
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = title
            s["messages"] = messages
            s["updated_at"] = time.time()
            found = True
            break
            
    if not found:
        sessions.append({
            "id": session_id,
            "title": title or f"محادثة جديدة {time.strftime('%Y-%m-%d %H:%M')}",
            "messages": messages,
            "created_at": time.time(),
            "updated_at": time.time()
        })
        
    save_chat_sessions(sessions, user_id)
    return jsonify({"status": "success"})

@app.route('/api/chat/history/<session_id>', methods=['DELETE'])
@login_required
def delete_chat_session(session_id):
    user_id = session.get('user_id')
    sessions = load_chat_sessions(user_id)
    sessions = [s for s in sessions if s["id"] != session_id]
    save_chat_sessions(sessions, user_id)
    return jsonify({"status": "success", "message": "تم حذف المحادثة بنجاح."})

# --- Admin Dashboard Stats ---
@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def get_admin_stats():
    users_dir = os.path.join(DATA_DIR, 'users')
    total_users = 0
    if os.path.exists(users_dir):
        total_users = len([d for d in os.listdir(users_dir) if os.path.isdir(os.path.join(users_dir, d))])
    
    registry = load_registry()
    total_docs = len(registry)
    total_chunks = sum(info.get("chunks_count", 0) for info in registry.values())
    
    index_size_mb = 0.0
    if os.path.exists(INDEX_FILE):
        index_size_mb = round(os.path.getsize(INDEX_FILE) / (1024 * 1024), 2)
        
    return jsonify({
        "total_users": total_users,
        "total_docs": total_docs,
        "total_chunks": total_chunks,
        "index_size_mb": index_size_mb
    })

# --- Core App Endpoints ---
@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def handle_settings():
    user_id = session.get('user_id')
    if request.method == 'POST':
        data = request.json
        settings = load_settings(user_id)
        for k in DEFAULT_SETTINGS.keys():
            if k in data:
                settings[k] = data[k]
        save_settings(settings, user_id)
        return jsonify({"status": "success", "message": "تم حفظ الإعدادات بنجاح.", "settings": settings})
    else:
        return jsonify(load_settings(user_id))

@app.route('/api/documents', methods=['GET'])
@login_required
def get_documents():
    registry = load_registry()
    result = []
    for doc_name, info in registry.items():
        result.append({
            "doc_id": info.get("doc_id"),
            "doc_name": doc_name,
            "chunks_count": info.get("chunks_count", 0),
            "pages_count": info.get("pages_count", 0),
            "path": info.get("path", "")
        })
    return jsonify(result)

@app.route('/api/documents/view/<doc_id>')
@login_required
def view_document(doc_id):
    registry = load_registry()
    target_path = None
    for doc_name, info in registry.items():
        if info.get("doc_id") == doc_id:
            target_path = info.get("path")
            break
    if not target_path or not os.path.exists(target_path):
        return "الملف غير موجود أو الهارد ديسك غير متصل.", 404
    return send_file(target_path, mimetype='application/pdf')

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
@admin_required
def delete_document(doc_id):
    index = load_index()
    new_index = [item for item in index if item['doc_id'] != doc_id]
    save_index(new_index)
    
    registry = load_registry()
    key_to_delete = None
    for k, v in registry.items():
        if v.get('doc_id') == doc_id:
            key_to_delete = k
            break
    if key_to_delete:
        del registry[key_to_delete]
        save_registry(registry)
    return jsonify({"status": "success", "message": "تم حذف المستند بنجاح من قاعدة البيانات."})

# Secure File Upload for PDFs to the library
@app.route('/api/admin/upload', methods=['POST'])
@admin_required
def upload_document():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "لم يتم العثور على أي ملف في الطلب."}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "لم يتم اختيار أي ملف."}), 400
        
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"status": "error", "message": "الملفات المدعومة هي بصيغة PDF فقط."}), 400
        
    try:
        # Secure the filename and save it inside the default library directory
        from werkzeug.utils import secure_filename
        # Fix Arabic encoding in filename if needed
        filename = secure_filename(file.filename)
        if not filename:
            # Fallback to a random uuid if secure_filename completely strips everything (e.g. non-ascii names)
            filename = f"document_{uuid.uuid4().hex}.pdf"
            
        dest_path = os.path.join(DEFAULT_LIBRARY_DIR, filename)
        file.save(dest_path)
        return jsonify({"status": "success", "message": f"تم رفع الملف '{file.filename}' بنجاح إلى المكتبة."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"فشل رفع الملف: {str(e)}"}), 500

# Trigger background folder sync
@app.route('/api/sync', methods=['POST'])
@admin_required
def trigger_sync():
    user_id = session.get('user_id')
    settings = load_settings(user_id)
    
    # Check if a sync is already running
    with sync_lock:
        if sync_status["status"] == "syncing":
            return jsonify({"status": "error", "message": "هناك عملية مزامنة قيد التشغيل بالفعل."}), 400
            
    # Start thread
    thread = threading.Thread(target=sync_library_thread_worker, args=(settings,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "success", "message": "تم إطلاق المزامنة بالخلفية بنجاح."}), 202

# Get real-time status of current sync
@app.route('/api/sync/status', methods=['GET'])
@login_required
def get_sync_status():
    with sync_lock:
        return jsonify(sync_status.copy())

# --- Encyclopedia APIs ---
@app.route('/api/legislation', methods=['GET'])
@login_required
def get_legislation():
    search = request.args.get('search', '').strip()
    db = load_legislation()
    if not search:
        return jsonify([{
            "id": law["id"],
            "name": law["name"],
            "description": law["description"],
            "articles_count": len(law["articles"]),
            "articles": law["articles"]
        } for law in db])
    
    search_results = []
    for law in db:
        matched_articles = []
        for art in law["articles"]:
            if search in art["text"] or search in str(art["num"]):
                matched_articles.append(art)
        if matched_articles:
            search_results.append({
                "id": law["id"],
                "name": law["name"],
                "description": law["description"],
                "articles": matched_articles
            })
    return jsonify(search_results)

@app.route('/api/rulings', methods=['GET'])
@login_required
def get_rulings():
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    db = load_court_rulings()
    results = db
    if category:
        results = [r for r in results if r["category"] == category]
    if search:
        results = [r for r in results if (search in r["principle"] or search in r["details"] or search in r["case_num"])]
    return jsonify(results)

@app.route('/api/templates', methods=['GET'])
@login_required
def get_templates():
    db = load_templates()
    return jsonify([{
        "id": t["id"],
        "title": t["title"],
        "category": t["category"],
        "content": t["content"]
    } for t in db])

def detect_arabic_dialect(text):
    if not text:
        return 'ar-SA-HamedNeural'
    
    text = text.lower()
    
    # Egyptian keywords
    egyptian_words = [
        "عايز", "عايزه", "عايزة", "ايه", "إيه", "ليه", "مش", "ده", "دي", "كده", "كدا", "بردو", "برضه", 
        "عشان", "علشان", "شغال", "جالي", "خالص", "دلوقتي", "ازاي", "فين", "بتاع", "شوية", 
        "النهاردة", "انهارده", "كويس", "أهوه", "اهو", "بص", "ياريت", "يا ريت", "بقى", "اللى", "اللي"
    ]
    
    # Emirati / Gulf keywords
    emirati_words = [
        "وايد", "رمس", "شو", "سوي", "شسوي", "حق", "زين", "الرمسة", "طال عمرك", 
        "هني", "الحين", "ألحين", "شو المقصد", "شو السالفة"
    ]
    
    # Saudi keywords
    saudi_words = [
        "وش", "تكفى", "تكفون", "ابغى", "شلون", "وشلون", "الحين", "ألحين", "مرة", "ابي", "وشو", 
        "أبغى", "وش صار", "يعطيك العافية", "شخبار"
    ]
    
    import re
    words = re.findall(r'\b\w+\b', text)
    words_set = set(words)
    
    egy_count = sum(1 for w in words if w in egyptian_words)
    ae_count = sum(1 for w in words if w in emirati_words)
    sa_count = sum(1 for w in words if w in saudi_words)
    
    if egy_count > ae_count and egy_count > sa_count:
        return 'ar-EG-ShakirNeural'
    elif ae_count > egy_count and ae_count > sa_count:
        return 'ar-AE-HamdanNeural'
    elif sa_count > egy_count and sa_count > ae_count:
        return 'ar-SA-HamedNeural'
    
    # Exact word fallback
    for w in egyptian_words:
        if w in words_set:
            return 'ar-EG-ShakirNeural'
    for w in emirati_words:
        if w in words_set:
            return 'ar-AE-HamdanNeural'
    for w in saudi_words:
        if w in words_set:
            return 'ar-SA-HamedNeural'
            
    return 'ar-SA-HamedNeural'

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    user_id = session.get('user_id')
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({"error": "الرجاء إدخال سؤال."}), 400
        
    try:
        settings = load_settings(user_id)
        
        relevant_chunks = []
        sources = []
        
        # Skip vector database search for simple greetings and short conversational inputs
        is_conversational = False
        clean_query = query.strip().lower()
        greetings_list = ["مرحبا", "مرحباً", "أهلاً", "اهلا", "السلام عليكم", "صباح الخير", "مساء الخير", "كيف حالك", "من أنت", "من انت", "مين انت", "يا هلا", "كيفك", "شخباركم", "شلونك", "شكرًا", "شكرا", "تسلم", "يعطيك العافية"]
        if any(g in clean_query for g in greetings_list) or (len(clean_query.split()) <= 2 and not any(kw in clean_query for kw in ["قانون", "مادة", "عقد", "دستور", "أحكام", "حكم"])):
            is_conversational = True

        if not is_conversational:
            try:
                query_vector = get_embedding(query, settings)
                relevant_chunks = search_vector_db(query_vector, top_k=4, min_similarity=0.2)
            except Exception as embed_err:
                print(f"Error searching vector database: {embed_err}", flush=True)
                
        context_parts = []
        for idx, chunk in enumerate(relevant_chunks):
            context_parts.append(
                f"[المصدر {idx+1}]: كتاب '{chunk['doc_name']}' - صفحة {chunk['page']}\nالنص: {chunk['text']}\n"
            )
            sources.append({
                "id": idx + 1,
                "doc_name": chunk['doc_name'],
                "page": chunk['page'],
                "text": chunk['text']
            })
            
        embeddings, metadata = load_vector_db()
        is_db_empty = (embeddings.shape[0] == 0)
        
        if is_db_empty:
            context_str = "تنبيه: قاعدة البيانات والمكتبة المحلية فارغة حالياً (لم تكتمل المزامنة بعد)."
        elif not relevant_chunks:
            context_str = "تنبيه: لم يتم العثور على فقرات مطابقة مباشرة من كتب المكتبة المحلية لهذا السؤال."
        else:
            context_str = "\n".join(context_parts)

        provider = settings.get("provider", "gemini")
        if IS_RENDER:
            provider = "gemini"

        
        # Determine active voice (Egyptian Shakir by default)
        selected_voice = data.get('voice', 'auto').strip()
        active_voice = selected_voice
        if selected_voice == 'auto':
            active_voice = detect_arabic_dialect(query)
            
        system_prompt = (
            "أنت بدوي المساعد الذكي، خبير قانوني ومساعد ذكي محترف ومبدع. تجيب باللغة العربية بدقة وموضوعية.\n"
            "التعليمات:\n"
            "1. إذا كان سؤال المستخدم عبارة عن تحية، أو استفسار عام عن قدراتك، أو طلباً لكتابة/صياغة شيء ما (مثل كتابة بحث، صياغة عقد، تلخيص نص، إلخ)، قم بمساعدته والإجابة عليه مباشرة بصفتك ذكاءً اصطناعياً ذكياً وخبيراً قانونياً، دون التقيّد بالكتب المرفقة.\n"
            "2. إذا كان السؤال متعلقاً بكتبك القانونية المرفقة أو قضية قانونية محددة، استعن بالنصوص المرفقة في السياق كمرجع أساسي، واذكر اسم الكتاب ورقم الصفحة بدقة عند الاقتباس (مثال: 'حسب كتاب القانون المدني، صفحة 12').\n"
            "3. إذا كان السؤال قانونياً تخصصياً ولم تجد إجابة مباشرة له في النصوص المرفقة، لا ترفض الإجابة مباشرة، بل قدم إجابة قانونية عامة ومفيدة بناءً على معرفتك القانونية الواسعة لمساعدة المستخدم، مع الإشارة بأدب إلى أن هذه المعلومات هي إيضاح قانوني عام وليست مقتبسة من كتبه المرفقة.\n"
        )
        
        # Append dialect-specific system prompt guidelines
        if active_voice == 'ar-EG-ShakirNeural':
            system_prompt += (
                "\nملاحظة هامة جداً لأسلوب الحديث:\n"
                "- اسمك هو 'بدوي المساعد الذكي' (شخصية ذكر).\n"
                "- يجب أن تتحدث وتجيب بالكامل بلهجة مصرية عامية طبيعية وتفاعلية للغاية وبصيغة الذكر (مثال: استخدام كلمات مثل 'أهلاً بك يا فندم'، 'أنا هنا عشان أساعدك'، 'تحت أمرك'، 'عشان'، 'مش'، 'ده'، 'كده'، 'إيه'، 'يا ريت').\n"
                "- تجنب الحديث بالفصحى الجافة، وتحدث بصوت صديق مصري ذكي، ودود، وتفاعلي."
            )
        elif active_voice == 'ar-EG-SalmaNeural':
            system_prompt += (
                "\nملاحظة هامة جداً لأسلوب الحديث:\n"
                "- اسمك هو 'جميلة المساعدة الذكية' (شخصية أنثى).\n"
                "- يجب أن تتحدثي وتجيبي بالكامل بلهجة مصرية عامية ناعمة، ودية ومتعاطفة للغاية وبصيغة المؤنث (مثال: استخدام كلمات مثل 'أهلاً بحضرتك'، 'أنا هنا عشان أساعدك'، 'تحت أمرك'، 'عشان'، 'مش'، 'ده'، 'كده'، 'إيه'، 'يا ريت').\n"
                "- تجنبي الحديث بالفصحى الجافة، وتحدثي بصوت مساعدة مصرية ذكية، ودودة ولطيفة."
            )
        elif active_voice == 'ar-AE-HamdanNeural':
            system_prompt += (
                "\nملاحظة هامة جداً لأسلوب الحديث:\n"
                "- اسمك هو 'بدوي المساعد الذكي' (شخصية ذكر).\n"
                "- يجب أن تتحدث وتجيب بالكامل بلهجة إماراتية/خليجية طبيعية وتفاعلية للغاية وبصيغة الذكر (مثال: استخدام كلمات مثل 'يا هلا وغلا'، 'طال عمرك'، 'أنا هني عشان أساعدك'، 'شو'، 'زين'، 'وايد'، 'سويت'، 'ألحين').\n"
                "- تجنب الحديث بالفصحى الجافة، وتحدث بصوت خبير إماراتي/خليجي ذكي، ودود وتفاعلي."
            )
        elif active_voice == 'ar-SA-HamedNeural':
            system_prompt += (
                "\nملاحظة هامة جداً لأسلوب الحديث:\n"
                "- اسمك هو 'بدوي المساعد الذكي' (شخصية ذكر).\n"
                "- يجب أن تتحدث وتجيب باللغة العربية الفصحى الفخمة أو اللهجة السعودية الرصينة بطريقة وقورة، محترفة وممتازة وبصيغة الذكر.\n"
                "- تحدث بصوت مستشار قانوني فخم ورصين يلتزم باللغة الراقية والفخمة."
            )
            
        user_prompt = f"السياق (النصوص المرفقة):\n{context_str}\n\nالسؤال: {query}\n\nالإجابة:"
        
        answer = ""
        
        if provider == "gemini":
            def call_chat():
                model = genai.GenerativeModel(
                    model_name="gemini-2.5-flash",
                    system_instruction=system_prompt
                )
                response = model.generate_content(user_prompt)
                return response.text
            answer = execute_with_gemini_retry(settings, call_chat)
            
        elif provider == "lmstudio":
            url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
            chat_endpoint = f"{url}/chat/completions"
            
            response = requests.post(
                chat_endpoint,
                headers={"Content-Type": "application/json"},
                json={
                    "model": settings.get("lmstudio_model", "qwen2.5-7b"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.3
                },
                timeout=60
            )
            response.raise_for_status()
            res_json = response.json()
            answer = res_json['choices'][0]['message']['content']
            
        return jsonify({
            "answer": answer,
            "sources": sources,
            "voice": active_voice
        })
        
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء معالجة السؤال: {str(e)}"}), 500


# ============================================================
# CASES MANAGEMENT — Load / Save helper
# ============================================================

def load_cases(user_id=None):
    cases_file = get_user_cases_file(user_id)
    if os.path.exists(cases_file):
        try:
            with open(cases_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_cases(data, user_id=None):
    cases_file = get_user_cases_file(user_id)
    with open(cases_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# GET all cases
@app.route('/api/cases', methods=['GET'])
@login_required
def get_cases():
    user_id = session.get('user_id')
    cases = load_cases(user_id)
    return jsonify(cases)

# POST — create new case
@app.route('/api/cases', methods=['POST'])
@login_required
def create_case():
    user_id = session.get('user_id')
    data = request.json
    cases = load_cases(user_id)
    new_case = {
        "id": str(uuid.uuid4()),
        "client_name": data.get("client_name", ""),
        "client_phone": data.get("client_phone", ""),
        "client_id": data.get("client_id", ""),
        "case_number": data.get("case_number", ""),
        "court": data.get("court", ""),
        "case_type": data.get("case_type", ""),
        "status": data.get("status", "نشطة"),
        "next_session": data.get("next_session", ""),
        "notes": data.get("notes", ""),
        "created_at": time.strftime("%Y-%m-%d")
    }
    cases.append(new_case)
    save_cases(cases, user_id)
    return jsonify(new_case), 201

# PUT — update an existing case
@app.route('/api/cases/<case_id>', methods=['PUT'])
@login_required
def update_case(case_id):
    user_id = session.get('user_id')
    data = request.json
    cases = load_cases(user_id)
    for i, c in enumerate(cases):
        if c["id"] == case_id:
            cases[i].update({
                "client_name": data.get("client_name", c["client_name"]),
                "client_phone": data.get("client_phone", c["client_phone"]),
                "client_id": data.get("client_id", c["client_id"]),
                "case_number": data.get("case_number", c["case_number"]),
                "court": data.get("court", c["court"]),
                "case_type": data.get("case_type", c["case_type"]),
                "status": data.get("status", c["status"]),
                "next_session": data.get("next_session", c["next_session"]),
                "notes": data.get("notes", c["notes"]),
            })
            save_cases(cases, user_id)
            return jsonify(cases[i])
    return jsonify({"error": "القضية غير موجودة"}), 404

# DELETE — remove a case
@app.route('/api/cases/<case_id>', methods=['DELETE'])
@login_required
def delete_case(case_id):
    user_id = session.get('user_id')
    cases = load_cases(user_id)
    cases = [c for c in cases if c["id"] != case_id]
    save_cases(cases, user_id)
    return jsonify({"success": True})

# ============================================================
# CONTRACT GENERATOR — AI-powered contract builder
# ============================================================

@app.route('/api/contracts/generate', methods=['POST'])
@login_required
def generate_contract():
    user_id = session.get('user_id')
    data = request.json
    contract_type = data.get("contract_type", "")
    fields = data.get("fields", {})

    if not contract_type:
        return jsonify({"error": "يُرجى تحديد نوع العقد."}), 400

    try:
        settings = load_settings(user_id)
        provider = settings.get("provider", "gemini")

        # Build a comprehensive prompt
        fields_text = "\n".join([f"- {k}: {v}" for k, v in fields.items() if v])
        prompt = (
            f"أنت بدوي المساعد الذكي، محامٍ وخبير قانوني مصري متخصص في صياغة العقود. "
            f"اكتب عقد {contract_type} كاملاً باللغة العربية بصياغة قانونية دقيقة ومحكمة.\n\n"
            f"البيانات المدخلة:\n{fields_text}\n\n"
            f"التعليمات:\n"
            f"1. اكتب العقد بصياغة قانونية رسمية واحترافية تستند إلى أحكام القانون المصري.\n"
            f"2. اذكر المادة القانونية المنطبقة عند الاقتضاء (مثل: القانون المدني المادة 147).\n"
            f"3. تضمّن: ديباجة العقد، بنود واضحة ومرقمة، بند الضمانات، بند الفسخ، بند التحكيم، وخاتمة التوقيع.\n"
            f"4. ضع توقيع الطرف الأول وتوقيع الطرف الثاني في النهاية.\n"
            f"5. لا تترك أي فراغات فارغة — اعتمد على البيانات المدخلة وإذا كانت بيانات غير مكتملة فاستعمل صيغة '[يُكمل لاحقاً]'.\n\n"
            f"اكتب العقد الآن:"
        )

        answer = ""
        if provider == "gemini":
            def call_gen():
                model = genai.GenerativeModel(model_name="gemini-2.5-flash")
                response = model.generate_content(prompt)
                return response.text
            answer = execute_with_gemini_retry(settings, call_gen)

        elif provider == "lmstudio":
            url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
            response = requests.post(
                f"{url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": settings.get("lmstudio_model", "qwen2.5-7b"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=120
            )
            response.raise_for_status()
            answer = response.json()['choices'][0]['message']['content']

        return jsonify({"contract": answer})

    except Exception as e:
        print(f"Contract generation error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء توليد العقد: {str(e)}"}), 500


# ============================================================
# DOCUMENT ANALYZER — Upload & AI-analyze any legal document
# ============================================================

@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze_document():
    user_id = session.get('user_id')
    text_input = ""

    # Handle file upload (PDF)
    if 'file' in request.files:
        f = request.files['file']
        if f.filename.lower().endswith('.pdf'):
            try:
                pdf_bytes = f.read()
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                pages_text = []
                for page in doc:
                    pages_text.append(page.get_text())
                text_input = "\n".join(pages_text)[:15000]  # limit to 15k chars
            except Exception as e:
                return jsonify({"error": f"فشل قراءة ملف PDF: {str(e)}"}), 400
        else:
            return jsonify({"error": "الملف المرفوع يجب أن يكون بصيغة PDF."}), 400

    # Handle raw text input
    elif request.is_json:
        text_input = request.json.get("text", "").strip()
    else:
        data = request.form
        text_input = data.get("text", "").strip()

    if not text_input:
        return jsonify({"error": "يُرجى إرفاق ملف PDF أو إدخال نص المستند."}), 400

    try:
        settings = load_settings(user_id)
        provider = settings.get("provider", "gemini")

        prompt = (
            "أنت بدوي المساعد الذكي، محامٍ وخبير قانوني مصري. قم بتحليل المستند القانوني التالي بالكامل وقدّم تقريراً شاملاً يتضمن:\n\n"
            "1. **ملخص المستند** (فقرة واحدة موجزة)\n"
            "2. **نوع المستند** (عقد / حكم قضائي / عريضة / مستند آخر)\n"
            "3. **الأطراف الرئيسية** (أسماء وصفاتهم إن وُجدت)\n"
            "4. **البنود والنقاط الجوهرية** (أهم 5 نقاط على الأقل)\n"
            "5. **نقاط القوة في المستند** (ما يصبّ في مصلحة الطرف الأول)\n"
            "6. **نقاط الضعف والمخاطر القانونية** (الثغرات والمخاطر المحتملة)\n"
            "7. **المواد القانونية المنطبقة** (القانون المصري)\n"
            "8. **التعديلات المقترحة** (إن وُجدت)\n"
            "9. **التوصية النهائية** (هل ينصح بالتوقيع؟ أي تحفظات؟)\n\n"
            f"المستند:\n{text_input}\n\n"
            "التحليل القانوني:"
        )

        answer = ""
        if provider == "gemini":
            def call_analyze():
                model = genai.GenerativeModel(model_name="gemini-2.5-flash")
                response = model.generate_content(prompt)
                return response.text
            answer = execute_with_gemini_retry(settings, call_analyze)

        elif provider == "lmstudio":
            url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
            response = requests.post(
                f"{url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": settings.get("lmstudio_model", "qwen2.5-7b"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=120
            )
            response.raise_for_status()
            answer = response.json()['choices'][0]['message']['content']

        return jsonify({"analysis": answer})

    except Exception as e:
        print(f"Analyze error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء التحليل: {str(e)}"}), 500


# ────────────────────────────────────────────────────────────────────────
# 4 NEW ENDPOINTS FOR LEVEL 4 ADVANCED FEATURES
# ────────────────────────────────────────────────────────────────────────

@app.route('/api/semantic-search', methods=['POST'])
@login_required
def semantic_search():
    try:
        user_id = session.get('user_id')
        data = request.get_json() or {}
        query = data.get("query", "").strip()
        search_type = data.get("type", "all")  # legislation, rulings, or all
        mode = data.get("mode", "local")  # ai or local

        if not query:
            return jsonify({"error": "يُرجى إدخال نص للبحث عنه."}), 400

        settings = load_settings(user_id)
        
        # Load datasets
        legislation_db = load_legislation()
        rulings_db = load_court_rulings()

        results = []

        if mode == "ai":
            # Attempt AI-powered semantic search
            try:
                provider = settings.get("provider", "gemini")
                prompt = (
                    f"أنت بدوي المساعد الذكي، مستشار قانوني خبير ومحرك بحث ذكي. ابحث بالمعنى والعمق القانوني عن الموضوع التالي:\n"
                    f"الموضوع: '{query}'\n\n"
                    f"لديك البيانات التالية:\n"
                    f"1. القوانين: {[l['name'] for l in legislation_db]}\n"
                    f"2. أحكام النقض: {[r['principle'][:100] + '...' for r in rulings_db[:15]]}\n\n"
                    f"قم بتحديد أكثر المواد القانونية وأحكام النقض ارتباطاً بالموضوع.\n"
                    f"أرجع النتيجة بتنسيق JSON فقط ولا تكتب أي كلام آخر خارجه. التنسيق المطلوب:\n"
                    f"{{\n"
                    f"  \"matches\": [\n"
                    f"    {{\n"
                    f"      \"source\": \"قانون\" أو \"حكم نقض\",\n"
                    f"      \"title\": \"اسم القانون أو رقم القضية والدائرة\",\n"
                    f"      \"details\": \"نص المادة أو المبدأ القانوني المُرتبط\",\n"
                    f"      \"relevance\": \"شرح موجز لسبب الارتباط ومدى أهميته (1-2 جملة)\"\n"
                    f"    }}\n"
                    f"  ]\n"
                    f"}}"
                )

                answer = ""
                if provider == "gemini":
                    def call_semantic():
                        model = genai.GenerativeModel(model_name="gemini-2.5-flash")
                        response = model.generate_content(prompt)
                        return response.text
                    answer = execute_with_gemini_retry(settings, call_semantic)
                elif provider == "lmstudio":
                    url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
                    response = requests.post(
                        f"{url}/chat/completions",
                        headers={"Content-Type": "application/json"},
                        json={
                            "model": settings.get("lmstudio_model", "qwen2.5-7b"),
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.2
                        },
                        timeout=60
                    )
                    response.raise_for_status()
                    answer = response.json()['choices'][0]['message']['content']

                # Clean markdown blocks if any
                clean_text = answer.strip()
                if clean_text.startswith("```"):
                    clean_text = clean_text.split("```")[1]
                    if clean_text.startswith("json"):
                        clean_text = clean_text[4:]
                if clean_text.endswith("```"):
                    clean_text = clean_text.rsplit("```", 1)[0]
                
                ai_results = json.loads(clean_text.strip())
                return jsonify(ai_results)

            except Exception as ai_err:
                print(f"AI search failed, falling back to local: {ai_err}")
                mode = "local"

        if mode == "local":
            # Smart keyword/token overlap search
            import re
            
            # Simple normalizer for Arabic
            def normalize_arabic(text):
                if not text:
                    return ""
                # Remove diacritics
                text = re.sub(r'[\u064B-\u0652]', '', text)
                # Normalize letters
                text = re.sub(r'[أإآ]', 'ا', text)
                text = re.sub(r'ة', 'ه', text)
                text = re.sub(r'ى', 'ي', text)
                return text.lower()

            norm_query = normalize_arabic(query)
            query_words = [w for w in norm_query.split() if len(w) > 2]
            if not query_words:
                query_words = [norm_query]

            matches = []

            # 1. Search legislation
            if search_type in ["all", "legislation"]:
                for law in legislation_db:
                    for art in law.get("articles", []):
                        art_text = art.get("text", "")
                        art_num = art.get("num", art.get("number", ""))
                        norm_art = normalize_arabic(art_text)
                        
                        # Calculate matching score (word overlap)
                        score = 0
                        for qw in query_words:
                            if qw in norm_art:
                                  score += 2
                            # Check prefix/suffix overlaps
                            elif any(qw[1:] in norm_art or qw[:-1] in norm_art for qw in query_words if len(qw) > 3):
                                  score += 1
                        
                        if score > 0:
                            matches.append({
                                "source": "قانون",
                                "title": f"{law.get('name')} - مادة {art_num}",
                                "details": art_text,
                                "relevance": f"تطابق في الكلمات المفتاحية القانونية بنسبة عالية.",
                                "score": score
                            })

            # 2. Search rulings
            if search_type in ["all", "rulings"]:
                for r in rulings_db:
                    principle = r.get("principle", "")
                    details = r.get("details", "")
                    norm_r = normalize_arabic(principle + " " + details)
                    
                    score = 0
                    for qw in query_words:
                        if qw in norm_r:
                            score += 2
                    
                    if score > 0:
                        matches.append({
                            "source": "حكم نقض",
                            "title": f"حكم نقض رقم {r.get('case_num')} لسنة {r.get('year')} ق - دائرة {r.get('court_circuit', r.get('circuit', 'المدنية'))}",
                            "details": f"المبدأ: {principle}\n\nالتفاصيل: {details}",
                            "relevance": "تطابق المبادئ القانونية المستقرة لمحكمة النقض المصرية.",
                            "score": score
                        })

            # Sort matches by score descending
            matches = sorted(matches, key=lambda x: x.get("score", 0), reverse=True)
            # Remove score from response
            for m in matches:
                m.pop("score", None)

            return jsonify({"matches": matches[:15]})

    except Exception as e:
        print(f"Semantic search error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء البحث: {str(e)}"}), 500


@app.route('/api/translate', methods=['POST'])
@login_required
def translate_text():
    try:
        user_id = session.get('user_id')
        data = request.get_json() or {}
        text = data.get("text", "").strip()
        direction = data.get("direction", "ar-to-en")  # ar-to-en or en-to-ar

        if not text:
            return jsonify({"error": "يُرجى إدخال النص المُراد ترجمته."}), 400

        settings = load_settings(user_id)
        provider = settings.get("provider", "gemini")

        prompt = (
            f"أنت مترجم قانوني مصري ومحترف صياغة العقود والمذكرات القانونية.\n"
            f"قم بترجمة النص القانوني التالي من {'العربية إلى الإنجليزية' if direction == 'ar-to-en' else 'الإنجليزية إلى العربية'} بدقة متناهية مع استخدام المصطلحات القانونية الرسمية المقابلة:\n\n"
            f"{text}\n\n"
            f"أرجع الترجمة فقط ولا تضف أي تعليقات أو شروحات إضافية."
        )

        translated = ""
        if provider == "gemini":
            def call_trans():
                model = genai.GenerativeModel(model_name="gemini-2.5-flash")
                response = model.generate_content(prompt)
                return response.text.strip()
            translated = execute_with_gemini_retry(settings, call_trans)
        elif provider == "lmstudio":
            url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
            response = requests.post(
                f"{url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": settings.get("lmstudio_model", "qwen2.5-7b"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2
                },
                timeout=60
            )
            response.raise_for_status()
            translated = response.json()['choices'][0]['message']['content'].strip()

        return jsonify({"translated": translated})

    except Exception as e:
        print(f"Translation error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء الترجمة: {str(e)}"}), 500


@app.route('/api/compare', methods=['POST'])
@login_required
def compare_texts():
    try:
        user_id = session.get('user_id')
        data = request.get_json() or {}
        text1 = data.get("text1", "").strip()
        text2 = data.get("text2", "").strip()
        analyze = data.get("analyze", False)

        if not text1 or not text2:
            return jsonify({"error": "يُرجى إدخال النصين للمقارنة."}), 400

        # 1. Local Word-level Diff
        import difflib
        
        # Simple word tokenizer
        def tokenize(text):
            return text.split()

        tokens1 = tokenize(text1)
        tokens2 = tokenize(text2)

        sm = difflib.SequenceMatcher(None, tokens1, tokens2)
        diff_blocks = []

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                diff_blocks.append({
                    "type": "equal",
                    "text": " ".join(tokens1[i1:i2]) + " "
                })
            elif tag == 'replace':
                diff_blocks.append({
                    "type": "delete",
                    "text": " ".join(tokens1[i1:i2]) + " "
                })
                diff_blocks.append({
                    "type": "insert",
                    "text": " ".join(tokens2[j1:j2]) + " "
                })
            elif tag == 'delete':
                diff_blocks.append({
                    "type": "delete",
                    "text": " ".join(tokens1[i1:i2]) + " "
                })
            elif tag == 'insert':
                diff_blocks.append({
                    "type": "insert",
                    "text": " ".join(tokens2[j1:j2]) + " "
                })

        # 2. AI legal comparison if requested
        analysis = ""
        if analyze:
            try:
                settings = load_settings(user_id)
                provider = settings.get("provider", "gemini")
                prompt = (
                    f"أنت بدوي المساعد الذكي، مستشار قانوني مصري محترف. قارن بين هذين النصين القانونيين/العقدين التاليين وحدد بدقة:\n"
                    f"1. الفروقات الجوهرية (في الالتزامات، الغرامات، المهل، الصياغة).\n"
                    f"2. الأثر القانوني لهذه الفروقات على مصلحة الطرفين.\n"
                    f"3. التوصيات المقترحة.\n\n"
                    f"النص الأول:\n{text1}\n\n"
                    f"النص الثاني:\n{text2}\n\n"
                    f"التحليل المقارن:"
                )

                if provider == "gemini":
                    def call_compare():
                        model = genai.GenerativeModel(model_name="gemini-2.5-flash")
                        response = model.generate_content(prompt)
                        return response.text.strip()
                    analysis = execute_with_gemini_retry(settings, call_compare)
                elif provider == "lmstudio":
                    url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
                    response = requests.post(
                        f"{url}/chat/completions",
                        headers={"Content-Type": "application/json"},
                        json={
                            "model": settings.get("lmstudio_model", "qwen2.5-7b"),
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3
                        },
                        timeout=60
                    )
                    response.raise_for_status()
                    analysis = response.json()['choices'][0]['message']['content'].strip()
            except Exception as ai_err:
                print(f"AI comparison analysis failed: {ai_err}")
                analysis = f"تعذر إجراء التحليل الذكي بسبب: {str(ai_err)}. تم توفير المقارنة البصرية فقط."

        return jsonify({
            "diff": diff_blocks,
            "analysis": analysis
        })

    except Exception as e:
        print(f"Comparison error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء المقارنة: {str(e)}"}), 500


@app.route('/api/updates', methods=['GET'])
@login_required
def get_legislative_updates():
    try:
        updates_file = os.path.join(DATA_DIR, 'legislation_updates.json')
        if os.path.exists(updates_file):
            with open(updates_file, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        return jsonify([])
    except Exception as e:
        print(f"Get updates error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء تحميل التحديثات: {str(e)}"}), 500


@app.route('/api/updates/check', methods=['POST'])
@login_required
def check_legislative_updates():
    try:
        user_id = session.get('user_id')
        settings = load_settings(user_id)
        provider = settings.get("provider", "gemini")
        
        prompt = (
            "أنت بدوي المساعد الذكي، باحث قانوني مصري تتابع الجريدة الرسمية والوقائع المصرية.\n"
            "قم بتوفير 2-3 تعديلات تشريعية أو قرارات وزارية هامة جديدة في مصر لعام 2025/2026.\n"
            "أرجع البيانات بتنسيق JSON فقط ولا تكتب أي كلام آخر خارجه. التنسيق المطلوب:\n"
            "[\n"
            "  {\n"
            "    \"law_name\": \"اسم القانون والتعديل (مثل: قانون المرور رقم ... لسنة ...)\",\n"
            "    \"date\": \"تاريخ صدوره أو نشره بالصيغة YYYY-MM-DD\",\n"
            "    \"type\": \"نوع التعديل (تعديل مادة / قانون جديد / قرار وزاري)\",\n"
            "    \"description\": \"تفاصيل التعديل أو القرار الجديد بدقة وموضوعية\",\n"
            "    \"impact\": \"الأثر القانوني والعملي لهذا التعديل\"\n"
            "  }\n"
            "]"
        )

        answer = ""
        if provider == "gemini":
            def call_updates():
                model = genai.GenerativeModel(model_name="gemini-2.5-flash")
                response = model.generate_content(prompt)
                return response.text
            answer = execute_with_gemini_retry(settings, call_updates)
        elif provider == "lmstudio":
            url = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip('/')
            response = requests.post(
                f"{url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": settings.get("lmstudio_model", "qwen2.5-7b"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5
                },
                timeout=60
            )
            response.raise_for_status()
            answer = response.json()['choices'][0]['message']['content']

        # Clean JSON block
        clean_text = answer.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("```")[1]
            if clean_text.startswith("json"):
                clean_text = clean_text[4:]
        if clean_text.endswith("```"):
            clean_text = clean_text.rsplit("```", 1)[0]
        
        new_updates = json.loads(clean_text.strip())

        # Save to file, merging with existing
        updates_file = os.path.join(DATA_DIR, 'legislation_updates.json')
        existing_updates = []
        if os.path.exists(updates_file):
            with open(updates_file, 'r', encoding='utf-8') as f:
                existing_updates = json.load(f)

        # Merge carefully to avoid duplicates
        existing_names = {u.get("law_name") for u in existing_updates}
        next_id = max([u.get("id", 0) for u in existing_updates] or [0]) + 1
        
        for nu in new_updates:
            if nu.get("law_name") not in existing_names:
                nu["id"] = next_id
                existing_updates.insert(0, nu)  # Add new ones at the top
                next_id += 1

        with open(updates_file, 'w', encoding='utf-8') as f:
            json.dump(existing_updates, f, ensure_ascii=False, indent=2)

        return jsonify(existing_updates)

    except Exception as e:
        print(f"Check updates error: {e}")
        return jsonify({"error": f"فشل فحص التحديثات الجديدة: {str(e)}"}), 500

@app.route('/api/tts')
def text_to_speech():
    text = request.args.get('text', '').strip()
    if not text:
        return jsonify({"error": "الرجاء إدخال نص لقراءته."}), 400
        
    try:
        import asyncio
        import edge_tts
        import hashlib
        import re

        # Clean text
        clean_text = re.sub(r'[\*\#\`\_\-\+\>]', '', text)
        clean_text = re.sub(r'\[المصدر \d+\]', '', clean_text)
        clean_text = re.sub(r'\[.*?\]\(.*?\)', '', clean_text).strip()
        
        if not clean_text:
            return jsonify({"error": "النص فارغ بعد التنظيف."}), 400

        # Read parameters with safe defaults (ar-EG-ShakirNeural is the male Egyptian voice)
        voice = request.args.get('voice', 'ar-EG-ShakirNeural').strip()
        if voice == 'auto':
            voice = detect_arabic_dialect(clean_text)
        rate = request.args.get('rate', '+10%').strip()
        if not rate.startswith('+') and not rate.startswith('-'):
            rate = f"+{rate}"
        
        # Directory to cache audio files
        tts_dir = os.path.join(DATA_DIR, 'tts')
        os.makedirs(tts_dir, exist_ok=True)
        
        # Calculate md5 hash of text + voice + rate to cache differently
        unique_string = f"{clean_text}_{voice}_{rate}"
        text_hash = hashlib.md5(unique_string.encode('utf-8')).hexdigest()
        output_filename = f"{text_hash}.mp3"
        output_path = os.path.join(tts_dir, output_filename)
        
        if not os.path.exists(output_path):
            async def generate_audio():
                communicate = edge_tts.Communicate(clean_text, voice, rate=rate)
                await communicate.save(output_path)
            
            asyncio.run(generate_audio())
            
        return send_from_directory(tts_dir, output_filename)
        
    except Exception as e:
        print(f"TTS error: {e}")
        return jsonify({"error": f"حدث خطأ أثناء تحويل النص إلى صوت: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
