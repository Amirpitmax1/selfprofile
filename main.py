import asyncio
import os
import logging
from pyrogram import Client, filters
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PasswordHashInvalid
)
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, render_template_string, redirect
from threading import Thread 

# --- تنظیمات لاگ‌نویسی ---
# Logging setup
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

# =======================================================
# ⚠️ تنظیمات اصلی از متغیرهای محیطی خوانده می‌شود
# =======================================================
API_ID = os.environ.get("API_ID", "28190856") 
API_HASH = os.environ.get("API_HASH", "6b9b5309c2a211b526c6ddad6eabb521") 
# PHONE_NUMBER و FIRST_NAME اکنون فقط به عنوان مقادیر پیش‌فرض استفاده می‌شوند.
# کاربر می‌تواند در صفحه وب، این مقادیر را تغییر دهد.
DEFAULT_PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "+989011243659")
DEFAULT_FIRST_NAME = os.environ.get("FIRST_NAME", "ye amir") 

# --- تعریف فونت‌های ساعت ---
CLOCK_FONTS = {
    "1": {"name": "Style 1 (Fullwidth)", "map": str.maketrans('0123456789:', '𝟬𝟭𝟮𝟯𝟺𝟻𝟼𝟳𝟾𝟿:')}, # Default
    "2": {"name": "Style 2 (Circled)", "map": str.maketrans('0123456789:', '⓪①②③④⑤⑥⑦⑧⑨:')},
    "3": {"name": "Style 3 (Double Struck)", "map": str.maketrans('0123456789:', '𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡:')}, # FIX: Changed '𝚠' to '𝟚' and '𝠙' to '𝟠𝟡' to match the length of the source string (11 chars)
    "4": {"name": "Style 4 (Monospace)", "map": str.maketrans('0123456789:', '０１２３４５６７８９:')},
}
# --- متغیرهای برنامه ---
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
app_flask = Flask(__name__)

# --- مدیریت وضعیت برنامه (اکنون دینامیک‌تر است) ---
APP_STATE = {
    "client": None,
    "phone_number": DEFAULT_PHONE_NUMBER,
    "first_name": DEFAULT_FIRST_NAME,
    "selected_font_key": "1", # Key for CLOCK_FONTS
    "phone_code_hash": None,
    "is_logged_in": False,
    "loop": None,
    # New Stages: START -> PHONE -> CODE -> PASSWORD -> RUNNING/FAILED
    "login_step": "START",  
    "error_message": None,
    "show_session_message": False,
}

# --- قالب‌های HTML ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ورود به سلف بات تلگرام</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');
        body { font-family: 'Vazirmatn', sans-serif; background-color: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; width: 90%; max-width: 450px; }
        h1 { color: #333; margin-bottom: 20px; }
        p { color: #666; }
        strong { color: #0056b3; }
        form { display: flex; flex-direction: column; gap: 15px; text-align: right; }
        input, select { padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; text-align: left; direction: ltr; width: 100%; box-sizing: border-box; }
        label { margin-top: 10px; font-weight: bold; color: #333; }
        button { padding: 12px; background-color: #007bff; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; font-family: 'Vazirmatn', sans-serif; }
        button:hover { background-color: #0056b3; }
        .error { color: #d93025; margin-top: 15px; font-weight: bold; }
        .success { color: #1e8e3e; font-size: 1.2em; font-weight: bold; }
        .info { color: #555; font-style: italic; }
        .session-info { margin-top: 25px; padding: 15px; background-color: #fffbe6; border: 1px solid #ffe58f; border-radius: 8px; text-align: justify; }
        .session-info strong { color: #d93025; }
    </style>
</head>
<body>
    <div class="container">
        {% if step == 'START' %}
            <h1>شروع ورود به سلف بات</h1>
            <p>لطفاً اطلاعات خود را وارد کرده و فونت مورد نظر برای ساعت را انتخاب کنید.</p>
            <form action="/start_login" method="post"> 
                <label for="phone">شماره تلفن (با کد کشور، مثال: +98912...)</label>
                <input type="text" id="phone" name="phone_number" placeholder="+98..." required autofocus value="{{ phone_number }}"> 
                
                <label for="name">نام نمایشی (اختیاری)</label>
                <input type="text" id="name" name="first_name" placeholder="نام دلخواه شما" value="{{ first_name }}"> 
                
                <label for="font">انتخاب فونت ساعت</label>
                <select id="font" name="font_key" required>
                    {% for key, font in clock_fonts.items() %}
                        <option value="{{ key }}" {% if key == selected_font_key %}selected{% endif %}>
                            {{ key }}. {{ font.name }} ({{ '12:34' | stylize_time(font.map) }})
                        </option>
                    {% endfor %}
                </select>
                <button type="submit">ارسال کد تایید</button> 
            </form>
        {% elif step == 'PHONE' %}
            <h1>در حال ارسال کد...</h1>
            <p class="info">در حال ارسال کد تایید به شماره <strong>{{ phone_number }}</strong>. لطفاً منتظر بمانید...</p>
        {% elif step == 'CODE' %}
            <h1>مرحله ۱: کد تایید</h1>
            <p>کدی به حساب تلگرام شما با شماره <strong>{{ phone_number }}</strong> ارسال شد. لطفاً آن را وارد کنید.</p>
            <form action="/login" method="post"> <input type="hidden" name="action" value="code"> <input type="hidden" name="phone_code_hash" value="{{ phone_code_hash }}"> <input type="text" name="code" placeholder="Verification Code" required autofocus> <button type="submit">تایید کد</button> </form>
        {% elif step == 'PASSWORD' %}
            <h1>مرحله ۲: رمز دو مرحله‌ای</h1>
            <p>حساب شما دارای تایید دو مرحله‌ای است. لطفاً رمز خود را وارد کنید.</p>
            <form action="/login" method="post"> <input type="hidden" name="action" value="password"> <input type="password" name="password" placeholder="2FA Password" required autofocus> <button type="submit">ورود</button> </form>
        {% elif step == 'RUNNING' %}
            <h1 class="success">✅ ربات با موفقیت فعال شد!</h1>
            <p>ساعت در کنار نام شما نمایش داده می‌شود.</p>
            {% if show_session_message %}
            <div class="session-info">
                <strong>اقدام مهم:</strong> برای جلوگیری از ورود مجدد، به بخش لاگ‌های برنامه خود در هاست بروید. یک <strong>رشته متنی طولانی (Session String)</strong> در آنجا چاپ شده است. آن را کپی کرده و به عنوان یک متغیر محیطی با نام <code>SESSION_STRING</code> در تنظیمات سرویس خود ذخیره و سپس سرویس را ری‌استارت کنید.
            </div>
            {% endif %}
        {% elif step == 'FAILED' %}
            <h1>❌ ورود ناموفق</h1>
            <p class="error">{{ error_message }}</p>
            <form action="/reset" method="get"><button type="submit">تلاش مجدد</button></form>
        {% endif %}
        {% if error_message and step != 'FAILED' %} <p class="error">{{ error_message }}</p> {% endif %}
    </div>
</body>
</html>
"""

# تعریف فیلتر برای Jinja2 تا بتواند پیش‌نمایش فونت را نمایش دهد
def jinja_stylize_time(time_str, translation_map):
    if isinstance(translation_map, dict):
        # Convert map back to maketrans format for Jinja usage
        map_str = str.maketrans(
            ''.join(translation_map.keys()), 
            ''.join(translation_map.values())
        )
        return time_str.translate(map_str)
    return time_str # Fallback

app_flask.jinja_env.filters['stylize_time'] = jinja_stylize_time


@app_flask.route('/')
def home():
    # If SESSION_STRING exists and bot is running, show running page immediately
    if APP_STATE["is_logged_in"] and os.environ.get("SESSION_STRING"):
        APP_STATE["login_step"] = "RUNNING"
    
    # If the app is in PHONE state (waiting for code to be sent), attempt to send it
    if APP_STATE["login_step"] == "PHONE" and not APP_STATE["phone_code_hash"]:
        future = asyncio.run_coroutine_threadsafe(handle_phone_submit(APP_STATE["phone_number"]), APP_STATE['loop'])
        try:
            future.result(timeout=30)
        except Exception as e:
            logging.error(f"Error sending code automatically: {e}", exc_info=True)
            APP_STATE["login_step"] = "FAILED"
            APP_STATE["error_message"] = "ارسال کد تایید ناموفق بود. لطفاً مطمئن شوید شماره صحیح است و دوباره تلاش کنید."
            
    template_vars = {
        "step": APP_STATE["login_step"],
        "phone_number": APP_STATE["phone_number"],
        "first_name": APP_STATE["first_name"],
        "selected_font_key": APP_STATE["selected_font_key"],
        "phone_code_hash": APP_STATE["phone_code_hash"],
        "error_message": APP_STATE["error_message"],
        "show_session_message": APP_STATE["show_session_message"],
        "clock_fonts": {k: {'name': v['name'], 'map': dict(v['map'])} for k, v in CLOCK_FONTS.items()}, # Pass font info for selection
    }
    return render_template_string(HTML_TEMPLATE, **template_vars)


@app_flask.route('/start_login', methods=['POST'])
def start_login():
    """Handles the initial form submission (phone number, name, font selection)."""
    # 1. Update APP_STATE with user input
    phone_number = request.form.get('phone_number')
    first_name = request.form.get('first_name') or DEFAULT_FIRST_NAME
    font_key = request.form.get('font_key')
    
    APP_STATE["phone_number"] = phone_number
    APP_STATE["first_name"] = first_name
    APP_STATE["selected_font_key"] = font_key
    APP_STATE["login_step"] = "PHONE"
    APP_STATE["error_message"] = None # Clear previous errors
    
    logging.info(f"User started login for phone: {phone_number} with font key: {font_key}")
    
    # 2. Redirect to home, which will trigger handle_phone_submit for 'PHONE' step
    return redirect('/')


@app_flask.route('/reset')
def reset():
    # Resetting the login state
    logging.info("Resetting login state to start over...")
    APP_STATE["login_step"] = "START"
    APP_STATE["error_message"] = None
    APP_STATE["phone_code_hash"] = None
    APP_STATE["is_logged_in"] = False
    return redirect('/')

@app_flask.route('/login', methods=['POST'])
def login():
    action = request.form.get('action')
    future = None
    try:
        if action == 'code':
            future = asyncio.run_coroutine_threadsafe(
                handle_code_submit(request.form.get('code'), request.form.get('phone_code_hash')), APP_STATE["loop"]
            )
        elif action == 'password':
            future = asyncio.run_coroutine_threadsafe(
                handle_password_submit(request.form.get('password')), APP_STATE["loop"]
            )
        if future: future.result(timeout=30) 
    except Exception as e:
        logging.error(f"Error processing form '{action}': {e}", exc_info=True)
        APP_STATE["error_message"] = None 
        
        if isinstance(e, PhoneCodeInvalid): 
            APP_STATE["error_message"] = "کد وارد شده اشتباه است."
            APP_STATE["login_step"] = "CODE" 
        elif isinstance(e, PasswordHashInvalid): 
            APP_STATE["error_message"] = "رمز عبور دو مرحله‌ای اشتباه است."
            APP_STATE["login_step"] = "PASSWORD" 
        else: 
            APP_STATE["error_message"] = "یک خطای پیش‌بینی نشده رخ داد."
            APP_STATE["login_step"] = "FAILED" 

    return redirect('/')

# --- توابع Async برای مدیریت مراحل لاگین ---
async def handle_phone_submit(phone_number):
    client = APP_STATE["client"]
    if not client.is_connected: await client.connect()
    # Use the phone number stored in APP_STATE from the form
    sent_code = await client.send_code(phone_number) 
    APP_STATE["phone_code_hash"] = sent_code.phone_code_hash
    APP_STATE["login_step"] = "CODE"
    logging.info("Verification code sent successfully.")

async def handle_code_submit(code, phone_code_hash):
    client = APP_STATE["client"]
    try:
        if not client.is_connected: await client.connect()
        # Use the phone number stored in APP_STATE
        await client.sign_in(APP_STATE["phone_number"], phone_code_hash, code) 
        await activate_bot_features(client)
    except SessionPasswordNeeded:
        logging.info("Two-factor authentication required.")
        APP_STATE["login_step"] = "PASSWORD"
    except Exception as e:
        if client.is_connected: await client.disconnect()
        raise e

async def handle_password_submit(password):
    client = APP_STATE["client"]
    try:
        if not client.is_connected: await client.connect()
        await client.check_password(password)
        await activate_bot_features(client)
    except Exception as e:
        if client.is_connected: await client.disconnect()
        raise e

# --- توابع اصلی ربات ---
async def activate_bot_features(client: Client):
    """Activates bot features (handlers and name update) after successful login."""
    if APP_STATE["is_logged_in"]: return
    
    user = await client.get_me()
    logging.info(f"✅ Successfully logged in as {user.first_name} (@{user.username}).")
    
    # Start the name update task
    asyncio.create_task(update_name())
        
    APP_STATE["is_logged_in"] = True
    APP_STATE["login_step"] = "RUNNING"

    # Generate and log session string if not using one
    if not os.environ.get("SESSION_STRING"):
        session_string = await client.export_session_string()
        logging.warning("=" * 70)
        logging.warning(" >> SESSION String Generated <<")
        logging.warning(" Copy this string and set it as SESSION_STRING environment variable.")
        logging.warning("-" * 70)
        print(f"\n{session_string}\n")
        logging.warning("-" * 70)
        logging.warning(" After setting the variable, restart the application for permanent login.")
        logging.warning("=" * 70)
        APP_STATE["show_session_message"] = True

def stylize_time(time_str: str, font_map: dict) -> str:
    """Uses the selected font map to style the time."""
    # font_map is an actual str.maketrans object created in __main__ or CLOCK_FONTS
    return time_str.translate(font_map)

async def update_name():
    client = APP_STATE["client"]
    # Get the selected font map
    font_map = CLOCK_FONTS.get(APP_STATE["selected_font_key"], CLOCK_FONTS["1"])["map"]
    
    while APP_STATE["is_logged_in"]: 
        try:
            tehran_time = datetime.now(TEHRAN_TIMEZONE)
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time_str = stylize_time(current_time_str, font_map)
            
            # Use the first_name stored in APP_STATE
            name_with_clock = f"{APP_STATE['first_name']} {stylized_time_str}"
            
            if not client.is_connected:
                logging.warning("Client disconnected. Attempting to reconnect...")
                await client.connect()

            await client.update_profile(first_name=name_with_clock)
            
            now = datetime.now(TEHRAN_TIMEZONE)
            sleep_duration = (60 - now.second) + (1000000 - now.microsecond) / 1000000.0
            
            await asyncio.sleep(sleep_duration)

        except FloodWait as e:
            logging.warning(f"Telegram flood limit. Waiting for {e.value + 5} seconds.")
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            logging.error(f"Error updating name: {e}")
            if not client.is_connected: 
                logging.error("Client permanently disconnected. Stopping update_name task.")
                break 
            await asyncio.sleep(60) 

# تابع run_flask و اجرای آن در Thread حذف شد. Gunicorn باید آن را اجرا کند.

async def main_bot_runner():
    """Main runner for the bot when a SESSION_STRING is available."""
    client = APP_STATE["client"]
    logging.info("Attempting to start the bot via SESSION_STRING...")
    try:
        await client.start()
        # Fetch user info after starting with session string to set FIRST_NAME and start clock
        user = await client.get_me()
        APP_STATE["first_name"] = user.first_name.split()[0] if user.first_name else DEFAULT_FIRST_NAME
        APP_STATE["phone_number"] = user.phone_number or APP_STATE["phone_number"]

        # If SESSION_STRING is used, we assume default font for simplicity
        # or you can add a FONT_KEY environment variable. We stick to default "1" for now.
        APP_STATE["selected_font_key"] = os.environ.get("FONT_KEY", "1")
        
        await activate_bot_features(client)
        await client.wait_for_disconnection()
    except Exception as e:
        logging.error(f"Automatic start failed: {e}. Session string might be invalid.")
        APP_STATE["login_step"] = "FAILED"
        APP_STATE["error_message"] = "Session string نامعتبر است. لطفاً برای دریافت رشته جدید، دوباره وارد شوید."


if __name__ == "__main__":
    logging.info("Starting application...")
    SESSION_STRING = os.environ.get("SESSION_STRING")

    # Finalize font maps (convert str.maketrans to dict for clean storage/use)
    # 🐛 FIX: The explicit conversion logic below caused the TypeError because 
    # the keys of a str.maketrans object are integers (Unicode code points), 
    # not strings, leading to the TypeError when using ''.join().
    # The map objects are already correctly initialized above, so we remove 
    # this redundant and faulty logic.


    if not API_ID or not API_HASH:
        logging.critical("CRITICAL ERROR: API_ID or API_HASH is not set. Exiting.")
        exit()

    # Initialize Pyrogram client
    if SESSION_STRING:
        logging.info("SESSION_STRING found. Initializing client...")
        client = Client(name="clock_self_bot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
    else:
        logging.warning("SESSION_STRING variable not found. Starting web login flow.")
        client = Client(name="clock_self_bot", api_id=API_ID, api_hash=API_HASH, in_memory=True)

    APP_STATE["client"] = client
    
    # Main Asyncio loop setup
    loop = asyncio.get_event_loop()
    APP_STATE["loop"] = loop
    
    try:
        if SESSION_STRING:
            # If session is provided, run the bot continuously
            loop.run_until_complete(main_bot_runner())
        else:
            # If no session, run the loop indefinitely to allow Flask threads to call async methods
            logging.info("Open the website address in your browser to log in.")
            loop.run_forever() 
    except (KeyboardInterrupt, SystemExit):
        logging.info("Stopping application...")
    finally:
        # Cleanup
        if client.is_connected:
            loop.run_until_complete(client.stop()) 
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        logging.info("Application stopped.")
