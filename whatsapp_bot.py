import os
import re
import json
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from google.genai import types

# Import core AI logic and helpers from our main bot (to ensure identical behavior)
from bot import (
    genai_client, 
    get_system_prompt, 
    select_tools, 
    extract_scripts, 
    clean_script_tags,
    VISUAL_MARK_PATTERN
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

# In-memory history for WhatsApp users: dict[phone_number, list[types.Content]]
whatsapp_histories = {}

def process_bot_response(bot_response: str) -> str:
    """Processes the bot response and formats it for WhatsApp text."""
    
    # Check for screenshot marker
    if "[SCREENSHOT_SUCCESS:" in bot_response:
        m = re.search(r'\[SCREENSHOT_SUCCESS:(.+?)\]', bot_response)
        if m:
            screenshot_url = m.group(1).strip()
            bot_response = bot_response.replace(m.group(0), f"\n[מנסה לצלם מסך של {screenshot_url}... לא נתמך כרגע בגרסת ה-Web]\n").strip()

    # Check for generated image
    if "[IMAGE_GEN_SUCCESS:" in bot_response:
        m = re.search(r'\[IMAGE_GEN_SUCCESS:(.+?)\]', bot_response)
        if m:
            image_prompt = m.group(1).strip()
            import urllib.parse
            encoded = urllib.parse.quote(image_prompt)
            image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
            bot_response = bot_response.replace(m.group(0), f"\n🎨 תמונה נוצרה. צפה כאן: {image_url}\n").strip()

    # Remove VISUAL_MARK tags
    display_text = VISUAL_MARK_PATTERN.sub('', bot_response).strip()

    # Extract scripts
    scripts = extract_scripts(display_text)
    if scripts:
        display_text = clean_script_tags(display_text)
        
    # Convert HTML tags to WhatsApp markdown
    display_text = re.sub(r'<b>(.*?)</b>', r'*\1*', display_text)
    display_text = re.sub(r'<i>(.*?)</i>', r'_\1_', display_text)
    display_text = re.sub(r'<code>(.*?)</code>', r'```\1```', display_text)
    display_text = re.sub(r'<pre>(.*?)</pre>', r'```\1```', display_text, flags=re.DOTALL)
    display_text = re.sub(r'<a href=".*?">(.*?)</a>', r'\1', display_text)
    display_text = re.sub(r'<[^>]+>', '', display_text)
        
    # Append scripts directly to text
    if scripts:
        display_text += "\n\n---\n"
        for filename, content in scripts:
            display_text += f"📄 *{filename}*\n```\n{content}\n```\n\n"
            
    return display_text

@app.route('/api/chat', methods=['POST'])
def handle_chat():
    """Endpoint for Node.js bridge to send messages to Gemini."""
    body = request.get_json()
    if not body or "phone" not in body or "text" not in body:
        return jsonify({"error": "Invalid request"}), 400

    phone_number = body["phone"]
    user_text = body["text"]
    
    logger.info(f"Received API message from {phone_number}: {user_text}")

    if phone_number not in whatsapp_histories:
        whatsapp_histories[phone_number] = []
        
    try:
        selected_tools = select_tools(user_text)
        config = types.GenerateContentConfig(
            system_instruction=get_system_prompt(),
            tools=selected_tools,
            temperature=0.3,
        )
        
        chat = genai_client.chats.create(
            model="gemini-2.5-flash",
            history=whatsapp_histories[phone_number],
            config=config
        )
        
        response = chat.send_message(user_text)
        logger.info(f"Response parts: {[type(p) for p in response.candidates[0].content.parts] if response.candidates and response.candidates[0].content.parts else 'No parts'}")
        logger.info(f"Response text before regex: {repr(response.text)}")
        
        bot_response = response.text or "לא הצלחתי למצוא תשובה."
        
        # Clean internal thought process exposed by Gemini Search Grounding
        bot_response = re.sub(r'^(?:tool_code\s*.*?)?thought\s*.*?(?=[\u0590-\u05FF])', '', bot_response, flags=re.DOTALL | re.IGNORECASE).strip()
        bot_response = re.sub(r'^tool_code\s*.*?(?=[\u0590-\u05FF])', '', bot_response, flags=re.DOTALL | re.IGNORECASE).strip()
        
        logger.info(f"Response text after regex: {repr(bot_response)}")
        
        whatsapp_histories[phone_number] = chat.get_history()
        
        if len(whatsapp_histories[phone_number]) > 20:
            whatsapp_histories[phone_number] = whatsapp_histories[phone_number][-20:]
        
        final_text = process_bot_response(bot_response)
        
        return jsonify({"response": final_text}), 200
        
    except Exception as e:
        logger.error(f"Error calling Gemini: {e}")
        return jsonify({"response": "⚠️ שגיאה פנימית. נסה שוב."}), 500

@app.route('/')
def health_check():
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Python AI Backend for WhatsApp on port {port}...")
    app.run(host='0.0.0.0', port=port, use_reloader=False)
