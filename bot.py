import os
import logging
import re
import datetime
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

from kb_manager import KBManager

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

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in environment or .env file")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in environment or .env file")
if not KB_URL:
    raise ValueError("KB_URL is not set in environment or .env file")

# Initialize KB Manager
kb_manager = KBManager(url=KB_URL)
kb_content = kb_manager.load_kb()

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
        "אתה בוט תמיכה טכנית בכיר (IT Support Tier 2/3). עליך להשתמש במסמך זה כבסיס הידע המרכזי והמועדף עליך. "
        "כאשר משתמש מתאר בעיה או שולח תמונה של תקלה, עליך לנתח תחילה את הסימפטומים מתוך מסמך זה, להרגיע את המשתמש, ולהוביל אותו שלב-אחר-שלב לפעולות התיקון, "
        "מהפעולה הפשוטה ביותר ועד למורכבת ביותר. אל תדלג על שלבים.\n\n"
        "חוקים חשובים נוספים:\n"
        "1. ענה בעברית בלבד.\n"
        "2. ניתוח תמונות (מולטימודאליות): אם המשתמש שולח תמונה של תקלה (למשל צילום מסך של שגיאה, מסך כחול, בעיה בחומרה או הגדרות), עליך לפענח ולקרוא את השגיאה מהתמונה, ולאחר מכן למצוא פתרון מתאים ממאגר הידע או מהאינטרנט.\n"
        "3. עדיפות עליונה למאגר הידע הפנימי: אם יש פתרון במאגר הידע הפנימי, עליך להשתמש אך ורק בו.\n"
        "4. חיפוש ברשת כגיבוי: אם השאלה או התמונה קשורות למחשבים/טכנולוגיה אך התשובה או הבעיה אינן מופיעות במאגר הידע הפנימי, עליך להשתמש בכלי החיפוש של גוגל (Google Search tool) כדי למצוא פתרון אמין ומקצועי ברשת.\n"
        "   במקרה כזה, עליך להוסיף את ההערה הבאה בדיוק בסוף התשובה שלך (בשורה נפרדת):\n"
        "   <i>*הערה: פתרון זה מבוסס על חיפוש ברשת ולא מופיע במאגר הידע הפנימי.*</i>\n"
        "5. סרטוני יוטיוב כעזר: במידה והתקלה מורכבת במיוחד (למשל: הגדרות רשת מתקדמות, פירוק חומרה, התקנת מערכת הפעלה וכו') או דורשת הדגמה ויזואלית, עליך להשתמש בכלי החיפוש של גוגל כדי לחפש סרטון הדרכה רלוונטי ביוטיוב (YouTube). אם מצאת סרטון מתאים, הוסף קישור אליו בתשובתך בפורמט HTML תקין: <a href=\"קישור לסרטון\">שם הסרטון או הסבר קצר</a> (למשל: <a href=\"https://www.youtube.com/watch?v=...\">מדריך וידאו לתיקון התקלה</a>).\n"
        "6. שאלות כלליות, זמן ומיקום: אם המשתמש שואל שאלות כלליות כמו 'מה השעה?', 'מה התאריך?', 'איפה אני נמצא?', או 'מה מזג האוויר אצלי?', עליך להשתמש בנתוני הזמן והמיקום הדינמיים המוזנים להלן כדי לענות לו ישירות, או להשתמש בחיפוש בגוגל לצורך מידע עדכני (כמו מזג אוויר).\n"
        "7. שאלות שאינן קשורות לטכנולוגיה/מחשבים/זמן/מיקום: אם השאלה אינה קשורה לתקלות או לנושאים טכניים, זמן או מיקום כלל (למשל מתכונים, ספורט, פוליטיקה וכו'), הסבר בנימוס שאתה בוט תמיכה טכנית המיועד לענות על שאלות הקשורות למחשבים וטכנולוגיה בלבד.\n"
        "8. עיצוב הפלט: עליך להשתמש אך ורק בתגיות HTML הבאות לצורך עיצוב בטלגרם:\n"
        "   - <b>טקסט מודגש</b>\n"
        "   - <i>טקסט נטוי</i>\n"
        "   - <code>קוד/פקודות</code>\n"
        "   - <pre>בלוק קוד גדול</pre>\n"
        "   - <a href=\"...\">קישורים</a>\n"
        "   חשוב: אין להשתמש בתגיות רשימה כמו <ul>, <ol>, <li> או בתגית <br>. לביצוע ירידת שורה השתמש בתו ירידת שורה רגיל (\\n). רשימות יש לכתוב באמצעות מקפים (- ) או מספרים פשוטים בתחילת השורה.\n"
        "   אסור להשתמש בסימוני Markdown כגון כוכביות (**), קווים תחתונים (_) או גרשים הפוכים (backticks).\n"
        "   הקפד לסגור את כל תגיות ה-HTML כראוי. אם עליך להציג סימני גדול-מ (>) או קטן-מ (<), המר אותם ל-&gt; ו-&lt;.\n"
        f"9. אימות קיום מוצרים ודגמים: לפני שאתה עונה על שאלה הקשורה למוצר, דגם, או גרסה ספציפית של חומרה או תוכנה (למשל: 'MacBook Pro 2027', 'Windows 14', 'iPhone 20' וכו'), עליך לבדוק תחילה באמצעות כלי החיפוש של גוגל האם המוצר או הדגם הזה באמת קיים ושוחרר נכון לתאריך הנוכחי ({current_date}). "
        "אם המוצר לא קיים, לא הוכרז, או טרם שוחרר - הודע למשתמש בצורה ברורה ומנומסת שהמוצר אינו קיים נכון להיום, ואל תמציא מידע או מפרטים לגביו. "
        "לדוגמה: אם משתמש שואל על 'MacBook 2027' והשנה היא 2026, עליך לענות שמוצר כזה לא קיים עדיין ולא הוכרז על ידי Apple.\n\n"
        "--- מידע דינמי על המשתמש והמערכת ---\n"
        f"- שעה נוכחית: {current_time}\n"
        f"- תאריך נוכחי: {current_date}\n"
        f"- מיקום גיאוגרפי משוער של המשתמש: {location_info['city']}, {location_info['country']}\n"
        f"- אזור זמן: {location_info['timezone']}\n"
        "---------------------------------------\n\n"
        f"בסיס הידע הפנימי המלא:\n{kb_manager.kb_content}"
    )
    return prompt

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command. Resets chat history and sends welcome message."""
    chat_id = update.effective_chat.id
    chat_histories[chat_id] = []  # Reset history
    
    welcome_text = (
        "<b>שלום! אני FixyBot - בוט התמיכה הטכנית שלך.</b> 🛠️\n\n"
        "אני מבוסס על מאגר ידע מקצועי של אנשי סיסטם ותמיכה טכנית.\n"
        "שאל אותי שאלות בנושאי מחשבים, רשתות, מדפסות, תוכנות אופיס ועוד, ואדריך אותך שלב אחר שלב.\n\n"
        "לרשימת פקודות: /help"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command. Displays available commands."""
    help_text = (
        "<b>פקודות זמינות:</b>\n"
        "/start - איפוס שיחה והצגת הודעת פתיחה\n"
        "/help - הצגת עזרה ורשימת פקודות\n"
        "/reload - טעינה מחדש של מאגר הידע ישירות מ-GitHub"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /reload command. Updates the local KB cache from GitHub."""
    await update.message.reply_text("🔄 טוען מחדש את מאגר הידע מ-GitHub...")
    
    new_content = kb_manager.load_kb()
    if new_content:
        await update.message.reply_text("✅ מאגר הידע עודכן בהצלחה!", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ שגיאה בטעינת מאגר הידע. נשארנו עם הגרסה הקודמת.", parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes user text messages, runs Gemini API, and replies by editing a temporary message."""
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    if not user_text:
        return

    # Instantly reply with a temporary message
    temp_msg = await update.message.reply_text("🔍 <b>בודק במאגר המידע...</b>", parse_mode="HTML")

    # Trigger typing action in Telegram
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Initialize history for this chat if it doesn't exist
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
        
    # Append user turn to history
    chat_histories[chat_id].append(
        types.Content(
            role="user",
            parts=[types.Part(text=user_text)]
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
            
        # Try editing temporary message with HTML parsing
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=temp_msg.message_id,
                text=bot_response,
                parse_mode="HTML"
            )
        except Exception as telegram_html_error:
            logger.warning(f"Telegram HTML editing failed, falling back to plain text: {telegram_html_error}")
            # Strip HTML tags and send as plain text
            clean_text = re.sub(r'<[^>]+>', '', bot_response)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=temp_msg.message_id,
                text=clean_text
            )
            
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
    
    # Instantly reply with a temporary message
    temp_msg = await update.message.reply_text("🔍 <b>מנתח את התמונה ומחפש פתרון...</b>", parse_mode="HTML")

    # Trigger typing action in Telegram
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        # Get the photo file from Telegram (highest resolution)
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        image_bytearray = await photo_file.download_as_bytearray()
        image_bytes = bytes(image_bytearray)
        
        # Initialize history for this chat if it doesn't exist
        if chat_id not in chat_histories:
            chat_histories[chat_id] = []
            
        # Prepare parts: image part + user prompt
        user_prompt = caption.strip() if caption.strip() else "אנא נתח את תמונת התקלה המצורפת וספק פתרון מפורט."
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
            
        # Try editing temporary message with HTML parsing
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=temp_msg.message_id,
                text=bot_response,
                parse_mode="HTML"
            )
        except Exception as telegram_html_error:
            logger.warning(f"Telegram HTML rendering failed for photo analysis, falling back to plain text: {telegram_html_error}")
            clean_text = re.sub(r'<[^>]+>', '', bot_response)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=temp_msg.message_id,
                text=clean_text
            )
            
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
    
    # Process photos
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
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
