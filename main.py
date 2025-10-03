import asyncio
import os
import logging
from pyrogram import Client
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PasswordHashInvalid, PhoneNumberInvalid, PhoneCodeExpired, ApiIdInvalid
)
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, render_template_string, redirect, session, url_for
from threading import Thread

# --- تنظیمات لاگ‌نویسی ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

# =======================================================
# ⚠️ تنظیمات اصلی (API_ID و API_HASH خود را اینجا وارد کنید)
# =======================================================
API_ID = 28190856  # ❗️ این قسمت را با API_ID عددی خودتان جایگزین کنید
API_HASH = "6b9b5309c2a211b526c6ddad6eabb521"  # ❗️ این قسمت را با API_HASH خودتان جایگزین کنید

# --- متغیرهای برنامه ---
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
app_flask = Flask(__name__)
app_flask.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

# --- دیکشنری فونت‌ها برای ساعت ---
FONT_STYLES = {
    "cursive":  {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "stylized": {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "doublestruck": {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "monospace":{'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "normal":   {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
}

EVENT_LOOP = asyncio.new_event_loop()
ACTIVE_CLIENTS = {}

# --- توابع کمکی ---
def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

def get_font_previews():
    """یک دیکشنری از نمونه‌های رندر شده فونت‌ها ایجاد می‌کند."""
    sample_time = "12:34"
    previews = {
        "کشیده": {"style": "cursive", "preview": stylize_time(sample_time, "cursive")},
        "فانتزی": {"style": "stylized", "preview": stylize_time(sample_time, "stylized")},
        "توخالی": {"style": "doublestruck", "preview": stylize_time(sample_time, "doublestruck")},
        "کامپیوتری": {"style": "monospace", "preview": stylize_time(sample_time, "monospace")},
        "ساده": {"style": "normal", "preview": stylize_time(sample_time, "normal")},
    }
    return previews

# --- قالب‌های HTML ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>سلف بات ساعت تلگرام</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');
        body { font-family: 'Vazirmatn', sans-serif; background-color: #f0f2f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .container { background: white; padding: 30px 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; width: 100%; max-width: 480px; }
        h1 { color: #333; margin-bottom: 20px; font-size: 1.5em; }
        p { color: #666; line-height: 1.6; }
        form { display: flex; flex-direction: column; gap: 15px; margin-top: 20px; }
        input[type="tel"], input[type="text"], input[type="password"] { padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; text-align: left; direction: ltr; }
        button { padding: 12px; background-color: #007bff; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; }
        button:hover { background-color: #0056b3; }
        .error { color: #d93025; margin-top: 15px; font-weight: bold; background-color: #fce8e6; padding: 10px; border-radius: 8px; border: 1px solid #f8a9a0; }
        .session-box { margin-top: 15px; }
        .session-box textarea { width: 100%; min-height: 100px; font-family: monospace; background: #f4f4f4; border: 1px solid #ddd; padding: 10px; box-sizing: border-box; border-radius: 6px; }
        label { font-weight: bold; color: #555; display: block; margin-bottom: 5px; text-align: right; }
        .font-options { border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }
        .font-option { display: flex; align-items: center; padding: 12px; border-bottom: 1px solid #ddd; cursor: pointer; transition: background-color 0.2s; }
        .font-option:hover { background-color: #f7f7f7; }
        .font-option:last-child { border-bottom: none; }
        .font-option input[type="radio"] { margin-left: 15px; transform: scale(1.2); }
        .font-option label { display: flex; justify-content: space-between; align-items: center; width: 100%; font-weight: normal; cursor: pointer; }
        .font-option .preview { font-size: 1.3em; font-weight: bold; direction: ltr; color: #0056b3; }
        .success { color: #1e8e3e; }
    </style>
</head>
<body>
    <div class="container">
        {% if step == 'GET_PHONE' %}
            <h1>ورود به سلف بات</h1>
            <p>شماره و استایل فونت مورد نظر خود را انتخاب کنید.</p>
            {% if error_message %} <p class="error">{{ error_message }}</p> {% endif %}
            <form action="{{ url_for('login') }}" method="post">
                <input type="hidden" name="action" value="phone">
                <div>
                    <label for="phone">شماره تلفن (با کد کشور)</label>
                    <input type="tel" id="phone" name="phone_number" placeholder="+989123456789" required autofocus>
                </div>
                <div>
                    <label>استایل فونت ساعت</label>
                    <div class="font-options">
                        {% for name, data in font_previews.items() %}
                        <div class="font-option" onclick="document.getElementById('font-{{ data.style }}').checked = true;">
                            <input type="radio" name="font_style" value="{{ data.style }}" id="font-{{ data.style }}" {% if loop.first %}checked{% endif %}>
                            <label for="font-{{ data.style }}">
                                <span>{{ name }}</span>
                                <span class="preview">{{ data.preview }}</span>
                            </label>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                <button type="submit">ارسال کد تایید</button>
            </form>
        {% elif step == 'GET_CODE' %}
            <h1>کد تایید</h1>
            <p>کدی به حساب تلگرام شما با شماره <strong>{{ phone_number }}</strong> ارسال شد.</p>
            {% if error_message %} <p class="error">{{ error_message }}</p> {% endif %}
            <form action="{{ url_for('login') }}" method="post">
                <input type="hidden" name="action" value="code">
                <input type="text" name="code" placeholder="Verification Code" required>
                <button type="submit">تایید کد</button>
            </form>
        {% elif step == 'GET_PASSWORD' %}
            <h1>رمز دو مرحله‌ای</h1>
            <p>حساب شما نیاز به رمز تایید دو مرحله‌ای دارد.</p>
            {% if error_message %} <p class="error">{{ error_message }}</p> {% endif %}
            <form action="{{ url_for('login') }}" method="post">
                <input type="hidden" name="action" value="password">
                <input type="password" name="password" placeholder="2FA Password" required>
                <button type="submit">ورود</button>
            </form>
        {% elif step == 'SHOW_SESSION' %}
            <h1 class="success">✅ فعال شد!</h1>
            <p>برای دائمی کردن ربات، این کد را در متغیر <code>SESSION_STRING</code> هاست خود ذخیره کنید:</p>
            <div class="session-box">
                <textarea readonly onclick="this.select()">{{ session_string }}</textarea>
            </div>
            <p style="margin-top: 10px;">همچنین متغیر <code>FONT_STYLE</code> را با مقدار <strong>{{ font_style }}</strong> در هاست خود تنظیم کنید.</p>
            <form action="{{ url_for('home') }}" method="get" style="margin-top: 20px;"><button type="submit">ورود با شماره جدید</button></form>
        {% endif %}
    </div>
</body>
</html>
"""

async def cleanup_client(phone):
    client = ACTIVE_CLIENTS.pop(phone, None)
    if client and client.is_connected:
        await client.disconnect()

@app_flask.route('/')
def home():
    session.clear()
    font_previews = get_font_previews()
    return render_template_string(HTML_TEMPLATE, step='GET_PHONE', font_previews=font_previews)

@app_flask.route('/login', methods=['POST'])
def login():
    action = request.form.get('action')
    phone = session.get('phone_number')
    
    try:
        if action == 'phone':
            phone = request.form.get('phone_number')
            font = request.form.get('font_style')
            session['phone_number'] = phone
            session['font_style'] = font
            
            async def send_code_task():
                await cleanup_client(phone)
                client = Client(f"user_{phone}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
                ACTIVE_CLIENTS[phone] = client
                await client.connect()
                sent_code = await client.send_code(phone)
                session['phone_code_hash'] = sent_code.phone_code_hash

            future = asyncio.run_coroutine_threadsafe(send_code_task(), EVENT_LOOP)
            future.result(timeout=45)
            return render_template_string(HTML_TEMPLATE, step='GET_CODE', phone_number=phone)

        elif action == 'code':
            code = request.form.get('code')
            p_hash = session.get('phone_code_hash')
            client = ACTIVE_CLIENTS.get(phone)
            if not client: raise Exception("Session expired, please start over.")

            async def sign_in_task():
                try:
                    await client.sign_in(phone, p_hash, code)
                    return await client.export_session_string(), None
                except SessionPasswordNeeded:
                    return None, 'GET_PASSWORD'
                finally:
                    if 'GET_PASSWORD' not in locals():
                        await cleanup_client(phone)

            future = asyncio.run_coroutine_threadsafe(sign_in_task(), EVENT_LOOP)
            session_string, next_step = future.result(timeout=45)

            if next_step:
                return render_template_string(HTML_TEMPLATE, step=next_step)
            else:
                return render_template_string(HTML_TEMPLATE, step='SHOW_SESSION', session_string=session_string, font_style=session.get('font_style'))

        elif action == 'password':
            password = request.form.get('password')
            client = ACTIVE_CLIENTS.get(phone)
            if not client: raise Exception("Session expired, please start over.")

            async def check_password_task():
                try:
                    await client.check_password(password)
                    return await client.export_session_string()
                finally:
                    await cleanup_client(phone)

            future = asyncio.run_coroutine_threadsafe(check_password_task(), EVENT_LOOP)
            session_string = future.result(timeout=45)
            return render_template_string(HTML_TEMPLATE, step='SHOW_SESSION', session_string=session_string, font_style=session.get('font_style'))
            
    except Exception as e:
        if phone:
            asyncio.run_coroutine_threadsafe(cleanup_client(phone), EVENT_LOOP)
        logging.error(f"Error during '{action}': {e}", exc_info=True)
        error_msg, current_step = "An unexpected error occurred. Please try again.", 'GET_PHONE'
        
        if isinstance(e, PhoneCodeInvalid):
            error_msg, current_step = "The confirmation code is invalid.", 'GET_CODE'
        elif isinstance(e, PasswordHashInvalid):
            error_msg, current_step = "The 2FA password is incorrect.", 'GET_PASSWORD'
        elif isinstance(e, PhoneNumberInvalid):
            error_msg = "The phone number is invalid. Check the format (+...)."
        elif isinstance(e, PhoneCodeExpired):
            error_msg = "The confirmation code has expired. Please start over."
        elif isinstance(e, FloodWait):
            error_msg = f"Too many attempts. Please wait for {e.value} seconds."
        
        font_previews = get_font_previews()
        if current_step == 'GET_PHONE': session.clear()
        
        return render_template_string(HTML_TEMPLATE, step=current_step, error_message=error_msg, phone_number=phone, font_previews=font_previews)
    
    return redirect(url_for('home'))

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

def run_asyncio_loop():
    try:
        EVENT_LOOP.run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        EVENT_LOOP.close()

if __name__ == "__main__":
    logging.info("در حال اجرای برنامه...")
    loop_thread = Thread(target=run_asyncio_loop, daemon=True)
    loop_thread.start()
    run_flask()

