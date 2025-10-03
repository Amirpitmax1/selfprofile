import asyncio
import os
import logging
from pyrogram import Client
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PasswordHashInvalid, PhoneNumberInvalid, PhoneCodeExpired, ApiIdInvalid, UserDeactivated, AuthKeyUnregistered
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
ALL_DIGITS = "".join(set(char for font in FONT_STYLES.values() for char in font.values()))

EVENT_LOOP = asyncio.new_event_loop()
ACTIVE_CLIENTS = {} # برای مدیریت کلاینت‌ها در حین ورود
ACTIVE_BOTS = {} # برای نگهداری ربات‌های فعال

# --- توابع اصلی ربات ---
def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

async def update_profile_clock(client: Client, phone: str, font_style: str):
    """حلقه اصلی که نام پروفایل را با ساعت تهران آپدیت می‌کند."""
    logging.info(f"Starting clock bot for {phone} with font '{font_style}'...")
    while phone in ACTIVE_BOTS:
        try:
            me = await client.get_me()
            current_name = me.first_name
            base_name = current_name

            parts = current_name.rsplit(' ', 1)
            if len(parts) > 1 and ':' in parts[-1] and any(char in ALL_DIGITS for char in parts[-1]):
                base_name = parts[0].strip()

            tehran_time = datetime.now(TEHRAN_TIMEZONE)
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time = stylize_time(current_time_str, font_style)
            new_name = f"{base_name} {stylized_time}"
            
            if new_name != current_name:
                await client.update_profile(first_name=new_name)
            
            now = datetime.now(TEHRAN_TIMEZONE)
            sleep_duration = 60 - now.second + 0.1
            await asyncio.sleep(sleep_duration)
        except (UserDeactivated, AuthKeyUnregistered):
            logging.error(f"Session for {phone} is invalid. Stopping bot.")
            break
        except FloodWait as e:
            logging.warning(f"Flood wait of {e.value}s for {phone}.")
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            logging.error(f"An error occurred for {phone}: {e}", exc_info=True)
            await asyncio.sleep(60)
    
    # پاکسازی نهایی
    if client.is_connected:
        await client.stop()
    ACTIVE_BOTS.pop(phone, None)
    logging.info(f"Clock bot for {phone} has been stopped and cleaned up.")


async def start_bot_instance(session_string: str, phone: str, font_style: str):
    """یک نمونه جدید از ربات را با سشن استرینگ داده شده فعال می‌کند."""
    try:
        if phone in ACTIVE_BOTS:
            task = ACTIVE_BOTS.pop(phone, None)
            if task:
                task.cancel()
            await asyncio.sleep(1) 

        client = Client(f"bot_{phone}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
        await client.start()
        
        task = asyncio.create_task(update_profile_clock(client, phone, font_style))
        ACTIVE_BOTS[phone] = task
        logging.info(f"Successfully started bot instance for {phone}.")
    except Exception as e:
        logging.error(f"FAILED to start bot instance for {phone}: {e}", exc_info=True)


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
        button { padding: 12px; background-color: #007bff; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }
        .error { color: #d93025; margin-top: 15px; font-weight: bold; background-color: #fce8e6; padding: 10px; border-radius: 8px; border: 1px solid #f8a9a0; }
        label { font-weight: bold; color: #555; display: block; margin-bottom: 5px; text-align: right; }
        .font-options { border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }
        .font-option { display: flex; align-items: center; padding: 12px; border-bottom: 1px solid #ddd; cursor: pointer; }
        .font-option:last-child { border-bottom: none; }
        .font-option input[type="radio"] { margin-left: 15px; }
        .font-option label { display: flex; justify-content: space-between; align-items: center; width: 100%; font-weight: normal; cursor: pointer; }
        .font-option .preview { font-size: 1.3em; font-weight: bold; direction: ltr; color: #0056b3; }
        .success { color: #1e8e3e; }
    </style>
</head>
<body>
    <div class="container">
        {% if step == 'GET_PHONE' %}
            <h1>ورود به سلف بات</h1>
            <p>شماره و استایل فونت خود را انتخاب کنید تا ربات فعال شود.</p>
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
            <p>کدی به تلگرام شما با شماره <strong>{{ phone_number }}</strong> ارسال شد.</p>
            {% if error_message %} <p class="error">{{ error_message }}</p> {% endif %}
            <form action="{{ url_for('login') }}" method="post"> <input type="hidden" name="action" value="code"> <input type="text" name="code" placeholder="Verification Code" required> <button type="submit">تایید کد</button> </form>
        {% elif step == 'GET_PASSWORD' %}
            <h1>رمز دو مرحله‌ای</h1>
            <p>حساب شما نیاز به رمز تایید دو مرحله‌ای دارد.</p>
            {% if error_message %} <p class="error">{{ error_message }}</p> {% endif %}
            <form action="{{ url_for('login') }}" method="post"> <input type="hidden" name="action" value="password"> <input type="password" name="password" placeholder="2FA Password" required> <button type="submit">ورود</button> </form>
        {% elif step == 'SHOW_SUCCESS' %}
            <h1 class="success">✅ ربات فعال شد!</h1>
            <p>ساعت کنار نام شما قرار گرفت. تا زمانی که این سایت فعال باشد، ربات شما نیز کار خواهد کرد.</p>
            <form action="{{ url_for('home') }}" method="get" style="margin-top: 20px;"><button type="submit">ورود با شماره جدید</button></form>
        {% endif %}
    </div>
</body>
</html>
"""

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
            if not client: raise Exception("Session expired.")

            async def sign_in_task():
                try:
                    await client.sign_in(phone, p_hash, code)
                    session_str = await client.export_session_string()
                    asyncio.run_coroutine_threadsafe(start_bot_instance(session_str, phone, session.get('font_style')), EVENT_LOOP)
                    return None
                except SessionPasswordNeeded:
                    return 'GET_PASSWORD'
                finally:
                    await cleanup_client(phone)

            future = asyncio.run_coroutine_threadsafe(sign_in_task(), EVENT_LOOP)
            next_step = future.result(timeout=45)

            if next_step:
                return render_template_string(HTML_TEMPLATE, step=next_step)
            else:
                return render_template_string(HTML_TEMPLATE, step='SHOW_SUCCESS')

        elif action == 'password':
            password = request.form.get('password')
            client = ACTIVE_CLIENTS.get(phone)
            if not client: raise Exception("Session expired.")

            async def check_password_task():
                try:
                    await client.check_password(password)
                    session_str = await client.export_session_string()
                    asyncio.run_coroutine_threadsafe(start_bot_instance(session_str, phone, session.get('font_style')), EVENT_LOOP)
                finally:
                    await cleanup_client(phone)

            future = asyncio.run_coroutine_threadsafe(check_password_task(), EVENT_LOOP)
            future.result(timeout=45)
            return render_template_string(HTML_TEMPLATE, step='SHOW_SUCCESS')
            
    except Exception as e:
        if phone:
            asyncio.run_coroutine_threadsafe(cleanup_client(phone), EVENT_LOOP)
        logging.error(f"Error during '{action}': {e}", exc_info=True)
        error_msg, current_step = "An unexpected error occurred.", 'GET_PHONE'
        
        if isinstance(e, PhoneCodeInvalid):
            error_msg, current_step = "کد تایید اشتباه است.", 'GET_CODE'
        elif isinstance(e, PasswordHashInvalid):
            error_msg, current_step = "رمز دو مرحله‌ای اشتباه است.", 'GET_PASSWORD'
        elif isinstance(e, PhoneNumberInvalid):
            error_msg = "شماره تلفن نامعتبر است."
        elif isinstance(e, PhoneCodeExpired):
            error_msg = "کد تایید منقضی شده، دوباره تلاش کنید."
        elif isinstance(e, FloodWait):
            error_msg = f"محدودیت تلگرام. لطفا {e.value} ثانیه دیگر تلاش کنید."
        
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
    logging.info("Starting Telegram Clock Bot Service...")
    loop_thread = Thread(target=run_asyncio_loop, daemon=True)
    loop_thread.start()
    run_flask()

