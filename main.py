import asyncio
import os
import logging
import time
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
# مقادیر پیش‌فرض زیر فقط برای نمایش هستند و باید توسط کاربر تغییر داده شوند.
# =======================================================
API_ID = os.environ.get("API_ID", "28190856") 
API_HASH = os.environ.get("API_HASH", "6b9b5309c2a211b526c6ddad6eabb521") 
# تغییر مقادیر پیش‌فرض به نمونه‌های عمومی
DEFAULT_PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "+989123456789") # شماره تلفن تستی
DEFAULT_FIRST_NAME = os.environ.get("FIRST_NAME", "ساعت تلگرام") # نام نمایشی تستی

# --- تعریف فونت‌های ساعت (حالا به عنوان رشته‌های خام ذخیره می‌شوند) ---
# We store 'from' and 'to' strings instead of the maketrans object to avoid TypeError in Jinja
CLOCK_FONTS = {
    "1": {"name": "Style 1 (Fullwidth)", "from": '0123456789:', "to": '𝟬𝟭𝟮𝟯𝟺𝟻𝟼𝟳𝟾𝟵:'},
    "2": {"name": "Style 2 (Circled)", "from": '0123456789:', "to": '⓪①②③④⑤⑥⑦⑧⑨:'},
    "3": {"name": "Style 3 (Double Struck)", "from": '0123456789:', "to": '𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡:'}, 
    "4": {"name": "Style 4 (Monospace)", "from": '0123456789:', "to": '０１２３４５６７８９:'},
}

# --- متغیرهای برنامه ---
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
app_flask = Flask(__name__)

# --- مدیریت وضعیت برنامه ---
APP_STATE = {
    "client": None,
    "phone_number": DEFAULT_PHONE_NUMBER,
    "first_name": DEFAULT_FIRST_NAME,
    "selected_font_key": "1", # Key for CLOCK_FONTS
    "phone_code_hash": None,
    "is_logged_in": False,
    "loop": None,
    "login_step": "START",  
    "error_message": None,
    "show_session_message": False,
}

# --- Pyrogram Client Initialization ---
SESSION_STRING = os.environ.get("SESSION_STRING")

if not API_ID or not API_HASH:
    logging.critical("CRITICAL ERROR: API_ID or API_HASH is not set. Assuming defaults.")

if SESSION_STRING:
    logging.info("SESSION_STRING found. Initializing client for direct run...")
    client = Client(name="clock_self_bot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
else:
    logging.warning("SESSION_STRING variable not found. Initializing client for web login flow...")
    client = Client(name="clock_self_bot", api_id=API_ID, api_hash=API_HASH, in_memory=True)

APP_STATE["client"] = client

# --- Async Loop Management ---

def start_asyncio_loop():
    """Sets up and runs the Pyrogram client/tasks in a separate thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    APP_STATE["loop"] = loop
    
    try:
        if SESSION_STRING:
            loop.run_until_complete(main_bot_runner())
        else:
            logging.info("Starting Pyrogram client connection in background...")
            client = APP_STATE["client"] # Get client reference
            
            # FIX for TypeError: An asyncio.Future, a coroutine or an awaitable is required
            # Ensure we only call connect() if the client is not already connected.
            if not client.is_connected:
                # We connect here but don't start the client yet
                loop.run_until_complete(client.connect()) 
            
            loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logging.info("Asyncio loop stopping...")
    finally:
        # Cleanup
        if APP_STATE["client"].is_connected:
            # Check if the loop is running before trying to stop the client
            if loop.is_running():
                # run_coroutine_threadsafe needed if called from Gunicorn thread, but here we are in the loop thread
                # We can use run_until_complete safely here as we are in the same thread and the loop is about to close
                loop.run_until_complete(APP_STATE["client"].stop()) 
        loop.close()

if not APP_STATE.get("loop"): 
    try:
        async_thread = Thread(target=start_asyncio_loop, daemon=True)
        async_thread.start()
        # Give the thread a moment to initialize the loop and connect
        time.sleep(1) 
        logging.info("Background Pyrogram asyncio loop started successfully.")
    except Exception as e:
        logging.error(f"Failed to start background asyncio thread: {e}")


# --- قالب‌های HTML ---
# ⚠️ فیلتر Jinja2 برای پیش‌نمایش فونت را حذف می‌کنیم.
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
                            {{ key }}. {{ font.name }} ({{ '12:34' | stylize_preview(font.to) }})
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

# فیلتر جدید Jinja2 که فقط برای نمایش استایل استفاده می‌شود و نیازی به maketrans ندارد
def jinja_stylize_preview(time_str: str, to_chars: str) -> str:
    """Jinja filter to simply map characters for preview using raw strings."""
    from_chars = '0123456789:'
    if len(from_chars) != len(to_chars):
        # Should not happen if CLOCK_FONTS is correct, but safe check
        return time_str 
    
    # Create the maketrans map locally for the preview string
    translation_map = str.maketrans(from_chars, to_chars)
    return time_str.translate(translation_map)

app_flask.jinja_env.filters['stylize_preview'] = jinja_stylize_preview


@app_flask.route('/')
def home():
    # If SESSION_STRING exists and bot is running, show running page immediately
    if APP_STATE["is_logged_in"] and os.environ.get("SESSION_STRING"):
        APP_STATE["login_step"] = "RUNNING"
    
    # If the app is in PHONE state (waiting for code to be sent), attempt to send it
    if APP_STATE["login_step"] == "PHONE" and not APP_STATE["phone_code_hash"] and APP_STATE['loop'] and APP_STATE['loop'].is_running():
        # NOTE: We must ensure the loop is running before calling run_coroutine_threadsafe
        future = asyncio.run_coroutine_threadsafe(handle_phone_submit(APP_STATE["phone_number"]), APP_STATE['loop'])
        try:
            future.result(timeout=30)
        except asyncio.TimeoutError:
            logging.error("Timeout waiting for phone code submission result.", exc_info=True)
            APP_STATE["login_step"] = "FAILED"
            APP_STATE["error_message"] = "زمان ارسال کد تایید به پایان رسید (Timeout). احتمالاً به دلیل سرعت پایین اینترنت یا محدودیت تلگرام است. لطفاً چند دقیقه صبر کنید و دوباره تلاش کنید."
        except Exception as e:
            # Pyrogram errors like FloodWait or PhoneCodeInvalid will be raised here
            logging.error(f"Error sending code automatically: {e}", exc_info=True)
            APP_STATE["login_step"] = "FAILED"
            
            error_message = "ارسال کد تایید ناموفق بود. لطفاً مطمئن شوید:"
            error_details = []
            
            error_text = str(e).lower()
            
            if "phone number is invalid" in error_text or "not registered" in error_text:
                error_details.append("شماره تلفن (با کد کشور) را صحیح وارد کرده‌اید.")
            elif "flood" in error_text:
                error_details.append("محدودیت تلگرام (FloodWait) فعال شده است. لطفاً حداقل یک ساعت دیگر امتحان کنید.")
            elif "session" in error_text:
                 error_details.append("مشکلی در اتصال Pyrogram رخ داده است. لطفاً بعداً دوباره تلاش کنید.")
            else:
                error_details.append("مشکل اتصال به سرور تلگرام وجود نداشته باشد.")
                
            APP_STATE["error_message"] = error_message + "\n- " + "\n- ".join(error_details) + " \n[جزئیات فنی: " + type(e).__name__ + "]"
            
    template_vars = {
        "step": APP_STATE["login_step"],
        "phone_number": APP_STATE["phone_number"],
        "first_name": APP_STATE["first_name"],
        "selected_font_key": APP_STATE["selected_font_key"],
        "phone_code_hash": APP_STATE["phone_code_hash"],
        "error_message": APP_STATE["error_message"],
        "show_session_message": APP_STATE["show_session_message"],
        # Pass the raw font data for Jinja preview
        "clock_fonts": CLOCK_FONTS, 
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
        # We use run_coroutine_threadsafe because Flask/Gunicorn runs in a different thread than the Asyncio loop
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
    # Client is already connected in the background thread if SESSION_STRING is missing
    sent_code = await client.send_code(phone_number) 
    APP_STATE["phone_code_hash"] = sent_code.phone_code_hash
    APP_STATE["login_step"] = "CODE"
    logging.info("Verification code sent successfully.")

async def handle_code_submit(code, phone_code_hash):
    client = APP_STATE["client"]
    try:
        # client must be started before signing in
        if not SESSION_STRING: await client.start()
        await client.sign_in(APP_STATE["phone_number"], phone_code_hash, code) 
        await activate_bot_features(client)
    except SessionPasswordNeeded:
        logging.info("Two-factor authentication required.")
        APP_STATE["login_step"] = "PASSWORD"
    except Exception as e:
        # If sign_in fails, client remains connected if started, or can be disconnected.
        # We rely on the thread loop closing it if the app shuts down.
        raise e

async def handle_password_submit(password):
    client = APP_STATE["client"]
    try:
        await client.check_password(password)
        await activate_bot_features(client)
    except Exception as e:
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

def get_font_map(font_key):
    """Creates the maketrans object on demand."""
    font_data = CLOCK_FONTS.get(font_key, CLOCK_FONTS["1"])
    return str.maketrans(font_data["from"], font_data["to"])

def stylize_time(time_str: str, font_map) -> str:
    """Uses the selected font map to style the time."""
    return time_str.translate(font_map)

async def update_name():
    client = APP_STATE["client"]
    # Create the maketrans object once for the running task
    font_map = get_font_map(APP_STATE["selected_font_key"])
    
    while APP_STATE["is_logged_in"]: 
        try:
            tehran_time = datetime.now(TEHRAN_TIMEZONE)
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time_str = stylize_time(current_time_str, font_map)
            
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
            # If the client is connected but fails repeatedly, we should not exit the whole app.
            if client.is_connected: 
                await asyncio.sleep(60) 
            else:
                logging.error("Client permanently disconnected. Stopping update_name task.")
                break 


async def main_bot_runner():
    """Main runner for the bot when a SESSION_STRING is available."""
    client = APP_STATE["client"]
    logging.info("Attempting to start the bot via SESSION_STRING...")
    try:
        await client.start()
        
        # Load user info and settings
        user = await client.get_me()
        APP_STATE["first_name"] = user.first_name.split()[0] if user.first_name else DEFAULT_FIRST_NAME
        APP_STATE["phone_number"] = user.phone_number or APP_STATE["phone_number"]
        APP_STATE["selected_font_key"] = os.environ.get("FONT_KEY", "1")
        
        await activate_bot_features(client)
        # Keep running until external shutdown
        await client.wait_for_disconnection()
        logging.info("Client disconnected. Shutting down runner.")
    except Exception as e:
        logging.error(f"Automatic start failed: {e}. Session string might be invalid or client terminated.")
        if not SESSION_STRING:
             # Only transition to FAILED if we are in the web login flow and the first attempt failed
             # If using SESSION_STRING, the main loop will just stop.
             APP_STATE["login_step"] = "FAILED"
             APP_STATE["error_message"] = "Session string نامعتبر است. لطفاً برای دریافت رشته جدید، دوباره وارد شوید."


if __name__ == "__main__":
    # If running locally via 'python main.py', we run the Flask server here.
    # On Render/Gunicorn, this block is skipped, and Gunicorn calls app_flask directly.
    logging.info("Running Flask in development mode for local testing.")
    port = int(os.environ.get('PORT', 5000))
    app_flask.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
