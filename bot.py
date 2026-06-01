import os
import re
import logging
import datetime
import tempfile
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

from kb_manager import KBManager
from github_integration import GitHubIntegration
from image_annotator import annotate_image
from corrections_manager import CorrectionsManager

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load configuration
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KB_URL = os.getenv("KB_URL")
GITHUB_REPO = os.getenv("GITHUB_REPO", "dor2500/FixyBot")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "fixyadmin123")  # Default password if none set

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in environment or .env file")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in environment or .env file")
if not KB_URL:
    raise ValueError("KB_URL is not set in environment or .env file")

# Initialize KB Manager
kb_manager = KBManager(url=KB_URL)
kb_content = kb_manager.load_kb()

# Initialize GitHub Integration
github_integration = GitHubIntegration(repo_url=GITHUB_REPO, token=GITHUB_TOKEN or None)
try:
    github_integration.fetch_repo_info()
except Exception as e:
    logger.warning(f"Could not load GitHub repo info: {e}")

# Initialize Corrections Manager
corrections_manager = CorrectionsManager()

# In-memory list of authorized admins
admin_users = set()

# Initialize Gemini Client
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# Chat histories in memory: dict[chat_id, list[types.Content]]
chat_histories = {}

# Location detection
location_info = {"city": "ישראל", "country": "ישראל", "timezone": "Asia/Jerusalem"}

def fetch_location_info():
    """Fetch the geographic location of the host machine from a free IP lookup API."""
    global location_info
    try:
        logger.info("Detecting system location via IP lookup...")
        response = requests.get("http://ip-api.com/json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                location_info["city"] = data.get("city", "ישראל")
                location_info["country"] = data.get("country", "ישראל")
                location_info["timezone"] = data.get("timezone", "Asia/Jerusalem")
                logger.info(f"Detected location: {location_info['city']}, {location_info['country']}")
            else:
                logger.warning(f"IP location service failed: {data.get('message')}")
    except Exception as e:
        logger.warning(f"Could not retrieve location information: {e}")

def get_system_prompt() -> str:
    """Rebuilds the system prompt with the latest KB content and dynamic location/time context."""
    now = datetime.datetime.now()
    current_time = now.strftime("%H:%M:%S")
    current_date = now.strftime("%Y-%m-%d")
    
    prompt = (
        "אתה FixyBot — בוט תמיכה טכנית בכיר (IT Support Tier 2/3) ומומחה טכנולוגי רב-תחומי. "
        "עליך להשתמש במסמך זה כבסיס הידע המרכזי והמועדף עליך. "
        "כאשר משתמש מתאר בעיה או שולח תמונה של תקלה, עליך לנתח תחילה את הסימפטומים מתוך מסמך זה, להרגיע את המשתמש, ולהוביל אותו שלב-אחר-שלב לפעולות התיקון, "
        "מהפעולה הפשוטה ביותר ועד למורכבת ביותר. אל תדלג על שלבים.\n\n"

        "--- תחומי ההתמחות שלך ---\n"
        "התמחות ראשית (Core Focus):\n"
        "- מחשבי PC: מערכות הפעלה Windows (כל הגרסאות), חומרת PC, פתרון תקלות, דרייברים, ביצועים, BIOS/UEFI, אבטחת מידע, רשתות ותקשורת.\n\n"
        "תמיכה היקפית (Auxiliary Support):\n"
        "- מחשבי ושרתי Linux (Ubuntu, CentOS, Debian, Fedora): פקודות CLI, שירותים, הרשאות, ניהול חבילות, SSH, ו-troubleshooting.\n"
        "- טלוויזיות חכמות (Smart TV): Samsung Tizen, LG webOS, Android TV — הגדרות רשת, עדכוני firmware, בעיות אפליקציות ושיקוף מסך.\n"
        "- מוצרי בית חכם (Smart Home): Google Home, Alexa, מנורות חכמות, מצלמות IP, ראוטרים — הגדרות Wi-Fi, אינטגרציות ופתרון תקלות.\n"
        "- מכשירים טכנולוגיים נוספים: סמארטפונים (Android/iOS) בהקשר טכני, מדפסות, סורקים, NAS ביתי, UPS ועוד.\n"
        "------------------------------\n\n"

        "חוקים חשובים נוספים:\n"
        "1. ענה בעברית בלבד.\n"
        "2. ניתוח תמונות (מולטימודאליות): אם המשתמש שולח תמונה של תקלה (למשל צילום מסך של שגיאה, מסך כחול, בעיה בחומרה או הגדרות), עליך לפענח ולקרוא את השגיאה מהתמונה, ולאחר מכן למצוא פתרון מתאים ממאגר הידע או מהאינטרנט.\n"
        "3. עדיפות עליונה למאגר הידע הפנימי: אם יש פתרון במאגר הידע הפנימי, עליך להשתמש אך ורק בו.\n"
        "4. חיפוש ברשת כגיבוי: השתמש בכלי החיפוש (Google Search) **אך ורק** במקרים הבאים כדי לחסוך זמן המתנה ללקוח:\n"
        "   - כשמבקשים המלצה על מוצרים או בניית מפרט מחשב.\n"
        "   - כשהתקלה/השאלה לא קיימת בכלל במאגר הידע ואתה חייב לבדוק מידע עדכני.\n"
        "   במקרה שהשתמשת בחיפוש בגלל חוסר במאגר, הוסף בסוף: <i>*הערה: פתרון זה מבוסס על חיפוש ברשת.*</i>\n"
        "5. סרטוני יוטיוב כעזר: במידה והתקלה מורכבת במיוחד (למשל: הגדרות רשת מתקדמות, פירוק חומרה, התקנת מערכת הפעלה וכו') או דורשת הדגמה ויזואלית, עליך לחפש קישור רלוונטי ליוטיוב (YouTube). הוסף קישור בתשובתך בפורמט: <a href=\"קישור לסרטון\">שם הסרטון או הסבר קצר</a>.\n"
        "6. שאלות כלליות, זמן ומיקום: אם המשתמש שואל שאלות כלליות כמו 'מה השעה?', 'מה התאריך?', 'איפה אני נמצא?', עליך להשתמש בנתוני הזמן והמיקום הדינמיים המוזנים להלן כדי לענות לו ישירות.\n"

        "7. הגבלת תחומים (Scope Guardrails):\n"
        "   אתה בוט תמיכה טכנית מקצועי בלבד. אם המשתמש מבקש ממך משהו שאינו קשור לטכנולוגיה, מחשבים, מכשירים אלקטרוניים, רשתות, תוכנות או ציוד טכנולוגי — עליך לסרב בנימוס.\n"
        "   דוגמאות לבקשות שעליך לסרב:\n"
        "   - מתכונים, בישול, אוכל\n"
        "   - שירים, שירה, כתיבה יצירתית\n"
        "   - ייעוץ רפואי, משפטי, פיננסי\n"
        "   - תכנון טיולים, המלצות מסעדות\n"
        "   - שאלות ידע כללי לא טכנולוגיות (היסטוריה, גיאוגרפיה, ספורט)\n"
        "   - פוליטיקה, דת, נושאים אישיים\n"
        "   תבנית תשובה לסירוב:\n"
        "   'אני FixyBot 🛠️ — בוט תמיכה טכנית מקצועי. אני מתמחה בפתרון תקלות מחשב, רשתות, ציוד טכנולוגי ועוד. אשמח לעזור לך בכל שאלה טכנולוגית! 😊'\n"

        "8. עיצוב הפלט: עליך להשתמש אך ורק בתגיות HTML הבאות לצורך עיצוב בטלגרם:\n"
        "   - <b>טקסט מודגש</b>\n"
        "   - <i>טקסט נטוי</i>\n"
        "   - <code>קוד/פקודות</code>\n"
        "   - <pre>בלוק קוד גדול</pre>\n"
        "   - <a href=\"...\">קישורים</a>\n"
        "   חשוב: אין להשתמש בתגיות רשימה כמו <ul>, <ol>, <li> או בתגית <br>. לביצוע ירידת שורה השתמש בתו ירידת שורה רגיל (\\n). רשימות יש לכתוב באמצעות מקפים (- ) או מספרים פשוטים בתחילת השורה.\n"
        "   אסור להשתמש בסימוני Markdown כגון כוכביות (**), קווים תחתונים (_) או גרשים הפוכים (backticks).\n"
        "   הקפד לסגור את כל תגיות ה-HTML כראוי. אם עליך להציג סימני גדול-מ (>) או קטן-מ (<), המר אותם ל-&gt; ו-&lt;.\n"

        "9. אימות קיום מוצרים ודגמים: לפני שאתה עונה על שאלה הקשורה למוצר, דגם, או גרסה ספציפית של חומרה או תוכנה, עליך לוודא שהמוצר אכן קיים ושוחרר לשוק.\n"

        "10. מחקר שוק, בניית מפרטי מחשב והמלצות מוצרים: כאשר משתמש מבקש המלצה על מוצר טכנולוגי לרכישה "
        "(כגון מחשב שלם, כרטיס מסך, מעבד, מסך מחשב וכדומה), עליך:\n"
        "   א. להשתמש בחיפוש Google כדי למצוא את החומרה המודרנית ביותר מהדורות האחרונים הזמינים כיום בשוק. "
        "אין חובה שהחלק יהיה משנת הייצור הנוכחית, אך הוא חייב להיות מהדור האחרון הקיים (לדוגמה: מעבדים מדורות אחרונים, כרטיסי מסך חדשים). "
        "אסור להמליץ על חומרה מיושנת שהוחלפה בדור חדש יותר, אלא אם המשתמש ביקש מפרט תקציבי במיוחד או יד שנייה.\n"
        "   ב. להציג השוואה או מפרט מסודר בפורמט הבא:\n"
        "      🏆 <b>המלצות / מפרט – עדכני להיום</b>\n\n"
        "      1️⃣ <b>[שם החלק/הדגם]</b> – [מחיר משוער]\n"
        "      ✅ יתרונות / למה בחרתי בו: [הסבר קצר]\n"
        "      📋 מפרט מפתח: [פירוט]\n"
        "      🔗 <a href=\"...\">קישור למידע נוסף</a>\n\n"
        "   ג. להוסיף המלצה אישית מנומקת בסוף ההשוואה.\n"
        "   ד. לציין שמחירים וזמינות עשויים להשתנות ולעודד את המשתמש לבדוק לפני רכישה.\n\n"

        "11. יצירת סקריפטים: כאשר אתה יוצר סקריפט עבור המשתמש (כגון סקריפט .bat, .ps1, .sh לאוטומציה, ניקוי, תיקון וכדומה), "
        "עטוף את קוד הסקריפט בתגיות מיוחדות כך:\n"
        "   [SCRIPT_FILE:שם_הקובץ.סיומת]\n"
        "   ...קוד הסקריפט...\n"
        "   [/SCRIPT_FILE]\n"
        "   לדוגמה: [SCRIPT_FILE:fix_network.bat] ... [/SCRIPT_FILE]\n"
        "   כך המערכת תייצר קובץ מוכן להורדה עבור המשתמש. בנוסף, הצג את הקוד גם כ-code block בתשובה הטקסטואלית.\n\n"

        "12. סימון חזותי על תמונות (Visual Grounding): "
        "כאשר משתמש שולח תמונה ושואל שאלה שדורשת מיקום פיזי (למשל: 'איפה ללחוץ?', 'מה הכפתור?', 'איזה כבל לנתק?'), "
        "עליך למצוא את המיקום בתמונה ולהחזיר קואורדינטות בפורמט מדויק כדי שהמערכת תצייר מסגרת אדומה סביב האזור. "
        "השתמש בתגית הבאה במקום כלשהו בתוך הטקסט שלך:\n"
        "   [VISUAL_MARK:y_min,x_min,y_max,x_max:label]\n"
        "הקואורדינטות צריכות להיות מספרים בין 0 ל-1000 (0,0 היא הפינה השמאלית העליונה, 1000,1000 היא הימנית התחתונה). label הוא הסבר קצר של מילה או שתיים. "
        "דוגמה: 'הנה הכפתור שעליך ללחוץ: [VISUAL_MARK:200,800,250,900:כפתור הפעלה]'\n\n"

        "13. פרויקט GitHub: אם המשתמש שואל על הפרויקט, קוד המקור, קבצים, מבנה הפרויקט, התקנה או תרומה לפרויקט — "
        "ענה על בסיס המידע הבא מה-GitHub repository:\n"
    )

    # Add GitHub repo info
    if github_integration.repo_summary:
        prompt += f"\n{github_integration.repo_summary}\n"
    else:
        prompt += f"\nRepository: https://github.com/{GITHUB_REPO}\n"

    prompt += (
        "\n--- מידע דינמי על המשתמש והמערכת ---\n"
        f"- שעה נוכחית: {current_time}\n"
        f"- תאריך נוכחי: {current_date}\n"
        f"- מיקום גיאוגרפי משוער של המשתמש: {location_info['city']}, {location_info['country']}\n"
        f"- אזור זמן: {location_info['timezone']}\n"
        "---------------------------------------\n\n"
    )

    # Add continuous learning corrections
    corrections_context = corrections_manager.get_context_text()
    if corrections_context:
        prompt += f"{corrections_context}\n\n"

    prompt += f"בסיס הידע הפנימי המלא:\n{kb_manager.kb_content}"
    return prompt

# ─── Script extraction helpers ───

SCRIPT_PATTERN = re.compile(r'\[SCRIPT_FILE:(.+?)\](.*?)\[/SCRIPT_FILE\]', re.DOTALL)
VISUAL_MARK_PATTERN = re.compile(r'\[VISUAL_MARK:([\d\.]+),([\d\.]+),([\d\.]+),([\d\.]+):(.*?)\]')

def extract_scripts(text: str):
    """Extract script blocks from bot response. Returns list of (filename, content) tuples."""
    return [(m.group(1).strip(), m.group(2).strip()) for m in SCRIPT_PATTERN.finditer(text)]

def clean_script_tags(text: str) -> str:
    """Remove [SCRIPT_FILE:...] tags from the text shown to the user, keeping the code readable."""
    def replacer(m):
        filename = m.group(1).strip()
        code = m.group(2).strip()
        return f"📄 <b>{filename}</b>\n<pre>{code}</pre>"
    return SCRIPT_PATTERN.sub(replacer, text)

# ─── Reply-To context helper ───

def build_reply_context(message) -> str:
    """If the user replied to a specific message, extract the original context."""
    if not message.reply_to_message:
        return ""
    
    original = message.reply_to_message
    original_text = original.text or original.caption or ""
    
    if not original_text:
        return ""
    
    if len(original_text) > 500:
        original_text = original_text[:500] + "..."
    
    return f'[המשתמש מגיב (Reply) להודעה קודמת הבאה: "{original_text}"]\n\nתגובת המשתמש: '


# ─── Telegram Handlers ───

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command. Resets chat history and sends welcome message."""
    chat_id = update.effective_chat.id
    chat_histories[chat_id] = []  # Reset history
    
    welcome_text = (
        "<b>שלום! אני FixyBot - בוט התמיכה הטכנית שלך.</b> 🛠️\n\n"
        "אני מבוסס על מאגר ידע מקצועי ובינה מלאכותית מתקדמת.\n\n"
        "<b>תחומי ההתמחות שלי:</b>\n"
        "🖥️ מחשבי PC — Windows, חומרה, דרייברים, תקלות\n"
        "🐧 שרתי ומחשבי Linux\n"
        "📺 טלוויזיות חכמות (Smart TV)\n"
        "🏠 מוצרי בית חכם (Smart Home)\n"
        "🖨️ מדפסות, סורקים וציוד היקפי\n"
        "📧 תוכנות אופיס, Outlook ו-Teams\n"
        "🔍 מחקר שוק והשוואת מוצרי טכנולוגיה\n\n"
        "שלח לי תיאור של תקלה, תמונה של שגיאה, או שאל כל שאלה טכנולוגית!\n\n"
        "לרשימת פקודות: /help"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command. Displays available commands."""
    help_text = (
        "<b>פקודות זמינות:</b>\n"
        "/start - איפוס שיחה והצגת הודעת פתיחה\n"
        "/help - הצגת עזרה ורשימת פקודות\n"
        "/reload - טעינה מחדש של מאגר הידע מ-GitHub\n\n"
        "<b>מה אני יכול לעשות:</b>\n"
        "💬 מענה על שאלות טכניות בעברית\n"
        "📸 ניתוח תמונות של שגיאות (כולל סימון מיקומים על התמונה)\n"
        "📜 יצירת סקריפטים מוכנים להורדה (.bat / .ps1 / .sh)\n"
        "🔍 מחקר שוק והשוואת מוצרי טכנולוגיה\n"
        "🔗 מידע על פרויקט FixyBot ב-GitHub\n\n"
        "<b>טיפ:</b> ניתן להגיב (Reply) להודעה ספציפית כדי לחזור לנושא קודם בשיחה."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /reload command. Updates the local KB cache from GitHub."""
    await update.message.reply_text("🔄 טוען מחדש את מאגר הידע מ-GitHub...")
    
    new_content = kb_manager.load_kb()
    if new_content:
        # Also refresh GitHub repo info
        try:
            github_integration.fetch_repo_info()
        except Exception:
            pass
        await update.message.reply_text("✅ מאגר הידע עודכן בהצלחה!", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ שגיאה בטעינת מאגר הידע. נשארנו עם הגרסה הקודמת.", parse_mode="HTML")

# ─── Admin & Continuous Learning Handlers ───

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for admin login."""
    if not context.args:
        await update.message.reply_text("שימוש: /login <password>")
        return
    password = context.args[0]
    if password == ADMIN_PASSWORD:
        admin_users.add(update.effective_user.id)
        await update.message.reply_text("✅ התחברת בהצלחה כמנהל מערכת!")
    else:
        await update.message.reply_text("❌ סיסמה שגויה.")

async def correct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a correction to the continuous learning database."""
    user_id = update.effective_user.id
    if user_id not in admin_users:
        await update.message.reply_text("❌ אינך מורשה לבצע פעולה זו. התחבר עם /login")
        return

    # Check if replied to a bot message
    if not update.message.reply_to_message or update.message.reply_to_message.from_user.id != context.bot.id:
        await update.message.reply_text("אנא בצע Reply לתשובה השגויה של הבוט והקלד /correct [התשובה הנכונה]")
        return
        
    correct_answer = " ".join(context.args)
    if not correct_answer:
        await update.message.reply_text("אנא ספק את התשובה הנכונה: /correct [תשובה]")
        return
        
    wrong_answer = update.message.reply_to_message.text or ""
    
    # Try to find the preceding question in chat_histories
    question = "שאלה כללית (לא נמצאה בהיסטוריה)"
    chat_id = update.effective_chat.id
    if chat_id in chat_histories:
        for i in range(len(chat_histories[chat_id]) - 1, -1, -1):
            if chat_histories[chat_id][i].role == "user":
                question = chat_histories[chat_id][i].parts[0].text
                break
                
    correction = corrections_manager.add_correction(question, wrong_answer, correct_answer, user_id)
    await update.message.reply_text(f"✅ התיקון נשמר בהצלחה (ID: {correction['id']}) ויתווסף לזיכרון הבוט.")

async def list_corrections_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in admin_users:
        await update.message.reply_text("❌ אינך מורשה לבצע פעולה זו.")
        return
    
    corrections = corrections_manager.get_all_corrections()
    if not corrections:
        await update.message.reply_text("אין תיקונים במערכת.")
        return
        
    text = "<b>רשימת התיקונים במערכת:</b>\n\n"
    for c in corrections:
        text += f"ID: <code>{c['id']}</code>\nשאלה: {c['question']}\nתשובה: {c['correct_answer']}\n---\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def del_correction_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in admin_users:
        return
    
    if not context.args:
        await update.message.reply_text("שימוש: /del_correction <id>")
        return
        
    cid = context.args[0]
    if corrections_manager.delete_correction(cid):
        await update.message.reply_text(f"✅ תיקון {cid} נמחק.")
    else:
        await update.message.reply_text(f"❌ לא נמצא תיקון עם ID {cid}.")

# ─── General Message Handlers ───

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes user text messages, runs Gemini API, and replies by editing a temporary message."""
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    if not user_text:
        return

    # Instantly reply with a cute loading GIF
    LOADING_GIF_URL = "https://media.tenor.com/On7kvXhzml4AAAAj/loading-gif.gif"
    try:
        temp_msg = await update.message.reply_animation(
            animation=LOADING_GIF_URL,
            caption="🔍 <b>מנתח וחושב...</b>",
            parse_mode="HTML"
        )
    except Exception:
        # Fallback to text if GIF fails
        temp_msg = await update.message.reply_text("🔍 <b>מנתח וחושב...</b>", parse_mode="HTML")

    # Trigger typing action in Telegram
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Initialize history for this chat if it doesn't exist
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []

    # --- Feature 2: Reply-To Context ---
    reply_context = build_reply_context(update.message)
    prompt_text = reply_context + user_text if reply_context else user_text
        
    # Append user turn to history
    chat_histories[chat_id].append(
        types.Content(
            role="user",
            parts=[types.Part(text=prompt_text)]
        )
    )
    
    try:
        # Build generation configuration with latest system instruction and Google Search grounding
        config = types.GenerateContentConfig(
            system_instruction=get_system_prompt(),
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,  # Low temperature for high precision and factual recall
        )
        
        # Call the Gemini API using the new google-genai SDK
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=chat_histories[chat_id],
            config=config
        )
        
        bot_response = response.text
        if not bot_response:
            bot_response = "לא הצלחתי למצוא תשובה מתאימה במאגר הידע."
            
        # Append model response to history
        chat_histories[chat_id].append(
            types.Content(
                role="model",
                parts=[types.Part(text=bot_response)]
            )
        )
        
        # Keep history to a reasonable limit (last 20 messages) to manage context token usage
        if len(chat_histories[chat_id]) > 20:
            chat_histories[chat_id] = chat_histories[chat_id][-20:]

        # --- Feature 4: Extract and send script files ---
        scripts = extract_scripts(bot_response)
        display_text = clean_script_tags(bot_response) if scripts else bot_response
            
        # Send the final text and delete the loading animation
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=display_text,
                parse_mode="HTML",
                reply_to_message_id=update.message.message_id
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=temp_msg.message_id)
        except Exception as telegram_html_error:
            logger.warning(f"Telegram HTML failed, falling back to plain text: {telegram_html_error}")
            clean_text = re.sub(r'<[^>]+>', '', display_text)
            await context.bot.send_message(
                chat_id=chat_id,
                text=clean_text,
                reply_to_message_id=update.message.message_id
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=temp_msg.message_id)

        # Send script files as downloadable documents
        for filename, content in scripts:
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix=f'_{filename}', delete=False, encoding='utf-8') as f:
                    f.write(content)
                    temp_path = f.name
                with open(temp_path, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=filename,
                        caption=f"📄 סקריפט מוכן להורדה: {filename}"
                    )
                os.unlink(temp_path)
            except Exception as script_err:
                logger.warning(f"Failed to send script file {filename}: {script_err}")
            
    except Exception as e:
        logger.error(f"Error during message handling: {e}")
        # Clean up history if request failed
        if chat_histories[chat_id] and chat_histories[chat_id][-1].role == "user":
            chat_histories[chat_id].pop()
            
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=temp_msg.message_id,
            text="⚠️ <b>מצטער, חלה שגיאה בעיבוד הבקשה שלך.</b>\nאנא נסה שוב או פנה למנהל המערכת.",
            parse_mode="HTML"
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes images of errors sent by users, calls Gemini API, and replies by editing a temporary message."""
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""
    
    # Instantly reply with a cute loading GIF
    LOADING_GIF_URL = "https://media.tenor.com/On7kvXhzml4AAAAj/loading-gif.gif"
    try:
        temp_msg = await update.message.reply_animation(
            animation=LOADING_GIF_URL,
            caption="🔍 <b>מנתח את התמונה ומחפש פתרון...</b>",
            parse_mode="HTML"
        )
    except Exception:
        # Fallback to text if GIF fails
        temp_msg = await update.message.reply_text("🔍 <b>מנתח את התמונה ומחפש פתרון...</b>", parse_mode="HTML")

    # Trigger typing action in Telegram
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        # Get the photo file from Telegram (highest resolution) or document
        if update.message.photo:
            file_obj = update.message.photo[-1]
        elif update.message.document:
            file_obj = update.message.document
        else:
            raise ValueError("No photo or document found in message.")
            
        photo_file = await file_obj.get_file()
        image_bytearray = await photo_file.download_as_bytearray()
        image_bytes = bytes(image_bytearray)
        
        # Initialize history for this chat if it doesn't exist
        if chat_id not in chat_histories:
            chat_histories[chat_id] = []

        # --- Feature 2: Reply-To Context ---
        reply_context = build_reply_context(update.message)
            
        # Prepare parts: image part + user prompt
        user_prompt = caption.strip() if caption.strip() else "אנא נתח את התמונה וספק פתרון. אם שאלתי על מיקום (למשל 'איפה ללחוץ'), אנא צרף את תגית VISUAL_MARK כפי שהוגדר לך."
        if reply_context:
            user_prompt = reply_context + user_prompt

        parts = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            types.Part(text=user_prompt)
        ]
        
        # Append user turn to history
        chat_histories[chat_id].append(
            types.Content(
                role="user",
                parts=parts
            )
        )
        
        # Build configuration with latest system prompt and search tools
        config = types.GenerateContentConfig(
            system_instruction=get_system_prompt(),
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        )
        
        # Call Gemini API
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=chat_histories[chat_id],
            config=config
        )
        
        bot_response = response.text
        if not bot_response:
            bot_response = "לא הצלחתי לנתח את התמונה או למצוא פתרון מתאים."
            
        # Append model response to history
        chat_histories[chat_id].append(
            types.Content(
                role="model",
                parts=[types.Part(text=bot_response)]
            )
        )
        
        # Keep history to a reasonable limit
        if len(chat_histories[chat_id]) > 20:
            chat_histories[chat_id] = chat_histories[chat_id][-20:]

        # --- Feature 1: Visual Grounding ---
        visual_marks = VISUAL_MARK_PATTERN.findall(bot_response)
        
        if visual_marks:
            annotated_bytes = image_bytes
            for mark in visual_marks:
                try:
                    y_min, x_min, y_max, x_max = map(float, mark[:4])
                    label = mark[4]
                    annotated_bytes = annotate_image(annotated_bytes, [y_min, x_min, y_max, x_max], label)
                except Exception as e:
                    logger.error(f"Error drawing visual mark {mark}: {e}")
            
            # Send the annotated image
            await context.bot.send_photo(chat_id=chat_id, photo=annotated_bytes, reply_to_message_id=update.message.message_id)

        # Remove the VISUAL_MARK tags from the text
        display_text = VISUAL_MARK_PATTERN.sub('', bot_response).strip()

        # --- Feature 4: Extract and send script files ---
        scripts = extract_scripts(display_text)
        display_text = clean_script_tags(display_text) if scripts else display_text
            
        # Send the final text and delete the loading animation
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=display_text,
                parse_mode="HTML",
                reply_to_message_id=update.message.message_id
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=temp_msg.message_id)
        except Exception as telegram_html_error:
            logger.warning(f"Telegram HTML failed for photo analysis, falling back to plain text: {telegram_html_error}")
            clean_text = re.sub(r'<[^>]+>', '', display_text)
            await context.bot.send_message(
                chat_id=chat_id,
                text=clean_text,
                reply_to_message_id=update.message.message_id
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=temp_msg.message_id)

        # Send script files as downloadable documents
        for filename, content in scripts:
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix=f'_{filename}', delete=False, encoding='utf-8') as f:
                    f.write(content)
                    temp_path = f.name
                with open(temp_path, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=filename,
                        caption=f"📄 סקריפט מוכן להורדה: {filename}"
                    )
                os.unlink(temp_path)
            except Exception as script_err:
                logger.warning(f"Failed to send script file {filename}: {script_err}")
            
    except Exception as e:
        logger.error(f"Error during photo handling: {e}")
        # Clean up history if request failed
        if chat_histories[chat_id] and chat_histories[chat_id][-1].role == "user":
            chat_histories[chat_id].pop()
            
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=temp_msg.message_id,
            text="⚠️ <b>מצטער, חלה שגיאה בניתוח התמונה שלך.</b>\nאנא ודא שהתמונה ברורה ונסה שוב.",
            parse_mode="HTML"
        )

def main():
    """Starts the Telegram bot application loop."""
    logger.info("Starting FixyBot application...")
    
    # Detect system location
    fetch_location_info()
    
    # Verify that the KB was loaded
    if not kb_manager.kb_content:
        logger.error("Could not load knowledge base. Exiting.")
        return

    # Build the Application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reload", reload_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("correct", correct_command))
    app.add_handler(CommandHandler("corrections", list_corrections_command))
    app.add_handler(CommandHandler("del_correction", del_correction_command))
    
    # Process photos and image documents (like uncompressed screenshots)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    
    # Process all text messages (excluding commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Check if running on Render (webhook mode) or locally (polling mode)
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    
    if render_url:
        # === WEBHOOK MODE (Render.com) ===
        port = int(os.getenv("PORT", "10000"))
        webhook_url = f"{render_url}/webhook"
        
        logger.info(f"Running in WEBHOOK mode on port {port}")
        logger.info(f"Webhook URL: {webhook_url}")
        
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="webhook",
            webhook_url=webhook_url,
        )
    else:
        # === POLLING MODE (Local development) ===
        logger.info("Running in POLLING mode (local development)")
        logger.info("Bot is polling. Press Ctrl+C to stop.")
        app.run_polling()

if __name__ == "__main__":
    main()
