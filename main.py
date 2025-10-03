import asyncio
import os
import logging
from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PasswordHashInvalid,
    PhoneNumberInvalid,
    PhoneCodeExpired, 
)
from flask import Flask, request, render_template_string, redirect, session, url_for
from threading import Thread

# --- Configuration & Setup ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

# --- ENVIRONMENT VARIABLES (Mandatory for Pyrogram Client) ---
# NOTE: These must be set on your hosting platform (Render/etc.)
# You need to set these in your hosting environment:
API_ID = os.environ.get("API_ID", "1234567") 
API_HASH = os.environ.get("API_HASH", "abcdef1234567890abcdef1234567890") 

if not API_ID or not API_HASH:
    logging.critical("CRITICAL ERROR: API_ID or API_HASH environment variables are not set! Using default placeholders.")


# --- Clock Fonts Definitions (Same as before) ---
CLOCK_FONTS = {
    "1": {"name": "Style 1 (Fullwidth)", "from": '0123456789:', "to": '𝟬𝟭𝟮𝟯𝟺𝟻𝟼𝟳𝟾𝟵:'},
    "2": {"name": "Style 2 (Circled)", "from": '0123456789:', "to": '⓪①②③④⑤⑥⑦⑧⑨:'},
    "3": {"name": "Style 3 (Double Struck)", "from": '0123456789:', "to": '𝟘𝟙𝚠𝟛𝟜𝟝𝟞𝟟𝟠𝟡:'}, 
}

# --- Flask App Initialization and Session Configuration ---
app_flask = Flask(__name__)
# ⚠️ This is crucial for session security. Use a long, random key.
app_flask.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_secure_default_key_for_telegram_clock')


# --- Jinja2 Filter for Font Preview ---
def jinja_stylize_preview(time_str: str, to_chars: str) -> str:
    """Jinja filter to show font preview."""
    from_chars = '0123456789:'
    translation_map = str.maketrans(from_chars, to_chars)
    return time_str.translate(translation_map)

app_flask.jinja_env.filters['stylize_preview'] = jinja_stylize_preview


# --- HTML Template (Login Interface) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ورود به سلف بات ساعت تلگرام</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');
        body { font-family: 'Vazirmatn', sans-serif; background-color: #f0f2f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .container { background: white; padding: 30px 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; width: 100%; max-width: 450px; }
        h1 { color: #333; margin-bottom: 20px; font-size: 1.5em; }
        p { color: #666; line-height: 1.6; }
        strong { color: #0056b3; }
        form { display: flex; flex-direction: column; gap: 15px; margin-top: 20px; }
        input, select { padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; text-align: left; direction: ltr; width: 100%; box-sizing: border-box; font-family: 'Vazirmatn', sans-serif; }
        label { margin-bottom: -10px; text-align: right; font-weight: bold; color: #333; }
        button { padding: 12px; background-color: #007bff; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; font-family: 'Vazirmatn', sans-serif; }
        button:hover { background-color: #0056b3; }
        .error { color: #d93025; margin-top: 15px; font-weight: bold; background-color: #fbeae5; padding: 10px; border-radius: 8px; border: 1px solid #f5c6cb; }
        .success { color: #1e8e3e; font-size: 1.2em; font-weight: bold; }
        .session-info { margin-top: 25px; padding: 15px; background-color: #e6f7ff; border: 1px solid #91d5ff; border-radius: 8px; text-align: right; }
        .session-info strong { color: #d93025; }
        textarea { width: 100%; height: 120px; direction: ltr; text-align: left; margin-top: 10px; font-family: monospace; border-radius: 8px; border-color: #ccc; padding: 10px; resize: vertical; }
        .reset-link { font-size: 0.9em; color: #666; margin-top: 15px; display: block; }
    </style>
</head>
<body>
    <div class="container">
        {% if step == 'START' %}
            <h1>تنظیم سلف بات ساعت</h1>
            <p>برای نمایش ساعت کنار نام تلگرام خود، وارد شوید.</p>
            <form action="{{ url_for('start_login') }}" method="post">
                <label for="phone">شماره تلفن (با کد کشور)</label>
                <input type="tel" id="phone" name="phone_number" placeholder="+98..." required autofocus value="{{ phone_number or '' }}">
                                
                <label for="font">انتخاب فونت ساعت</label>
                <select id="font" name="font_key">
                    {% for key, font in clock_fonts.items() %}
                        <option value="{{ key }}" {% if key == selected_font_key %}selected{% endif %}>
                            {{ font.name }} ({{ '12:34' | stylize_preview(font.to) }})
                        </option>
                    {% endfor %}
                </select>
                
                <button type="submit">ارسال کد تایید</button>
            </form>

        {% elif step == 'CODE' %}
            <h1>مرحله ۱: کد تایید</h1>
            <p>کدی به حساب تلگرام شما با شماره <strong>{{ phone_number }}</strong> ارسال شد. لطفاً آن را وارد کنید.</p>
            <form action="{{ url_for('submit_code') }}" method="post">
                <input type="text" name="code" placeholder="کد ارسال شده" required autofocus inputmode="numeric">
                <button type="submit">تایید کد</button>
            </form>
            <a href="{{ url_for('reset') }}" class="reset-link">تغییر شماره یا شروع مجدد</a>

        {% elif step == 'PASSWORD' %}
            <h1>مرحله ۲: رمز دو مرحله‌ای</h1>
            <p>حساب شما دارای تایید دو مرحله‌ای است. لطفاً رمز خود را وارد کنید.</p>
            <form action="{{ url_for('submit_password') }}" method="post">
                <input type="password" name="password" placeholder="رمز عبور دو مرحله‌ای" required autofocus>
                <button type="submit">ورود</button>
            </form>
            <a href="{{ url_for('reset') }}" class="reset-link">شروع مجدد لاگین</a>

        {% elif step == 'DONE' %}
            <h1 class="success">✅ ورود موفقیت آمیز بود!</h1>
            <p>کلید نشست (Session String) شما ساخته شد. این کلید برای اجرای ربات نهایی ضروری است.</p>
            <div class="session-info">
                <strong>اقدام نهایی و مهم:</strong>
                <ol style="padding-right: 20px; text-align: right;">
                    <li>متن زیر را به طور کامل کپی کنید (Session String).</li>
                    <li>این کلید و سایر تنظیمات را در هاست خود به عنوان متغیر محیطی برای **فایل `bot_worker.py`** تنظیم کنید:
                        <ul>
                            <li>`SESSION_STRING`: (مقدار کپی شده)</li>
                            <li>`FIRST_NAME`: (نامی که می‌خواهید نمایش داده شود، مثال: `Amir`)</li>
                            <li>`FONT_KEY`: (مقدار فونت انتخابی شما: `{{ font_key }}`)</li>
                        </ul>
                    </li>
                    <li>سپس، فایل `bot_worker.py` را اجرا کنید.</li>
                </ol>
            </div>
            <textarea readonly onclick="this.select()">{{ session_string }}</textarea>

        {% endif %}

        {% if error_message %}
            <p class="error">**خطا:** {{ error_message }}</p>
        {% endif %}
    </div>
</body>
</html>
"""

# =======================================================
# UTILITY FUNCTION: Running Async Pyrogram code in Flask's Sync threads
# =======================================================
def run_async_in_sync(coroutine):
    """Run a Pyrogram async function in a separate event loop."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)
    except Exception as e:
        logging.error(f"Async execution failed: {type(e).__name__} - {e}", exc_info=True) 
        return {"success": False, "error": f"Internal System Error: {type(e).__name__}."}


# =======================================================
# PYROGRAM ASYNC CORE FUNCTIONS
# =======================================================

async def send_verification_code(phone_number: str):
    """Creates a temporary client and sends the verification code."""
    client = Client(name=str(phone_number), api_id=API_ID, api_hash=API_HASH, in_memory=True)
    try:
        await client.connect()
        sent_code = await client.send_code(phone_number)
        await client.disconnect()
        return {"success": True, "phone_code_hash": sent_code.phone_code_hash}
    except PhoneNumberInvalid as e:
        await client.disconnect()
        return {"success": False, "error": "شماره تلفن وارد شده نامعتبر است. لطفاً با کد کشور (مثال: +98...) وارد کنید."}
    except FloodWait as e:
        await client.disconnect()
        return {"success": False, "error": f"تلگرام شما را موقتاً محدود کرده است. لطفاً {e.value} ثانیه دیگر تلاش کنید."}
    except Exception as e:
        await client.disconnect()
        return {"success": False, "error": f"خطای ارسال کد: {type(e).__name__}."}


async def sign_in_and_get_session(phone_number: str, phone_code_hash: str, code: str, password: str = None):
    """Logs in with code and/or password and returns the Session String."""
    client = Client(name=str(phone_number), api_id=API_ID, api_hash=API_HASH, in_memory=True)
    try:
        await client.connect()
        
        # 1. Attempt Sign In
        try:
            if not password:
                await client.sign_in(phone_number, phone_code_hash, code)
        except SessionPasswordNeeded:
            if not password:
                await client.disconnect()
                return {"success": False, "needs_password": True}
            
            # If 2FA is needed and password is provided, check it
            await client.check_password(password)

        # 2. Login Successful
        session_string = await client.export_session_string()
        await client.disconnect()
        return {"success": True, "session_string": session_string}

    except PhoneCodeInvalid:
        await client.disconnect()
        return {"success": False, "error": "کد تایید وارد شده اشتباه است."}
    except PasswordHashInvalid:
        await client.disconnect()
        return {"success": False, "error": "رمز عبور دو مرحله‌ای اشتباه است.", "needs_password": True}
    except PhoneCodeExpired:
        await client.disconnect()
        # This error triggers a full reset in the Flask route
        return {"success": False, "error": "کد تایید منقضی شده است. باید از ابتدا شروع کنید."}
    except Exception as e:
        await client.disconnect()
        return {"success": False, "error": f"خطای نامشخص در ورود: {type(e).__name__}"}

# =======================================================
# FLASK ROUTES (Synchronous)
# =======================================================

@app_flask.route('/')
def home():
    """Displays the main page based on the user's session state."""
    step = session.get('login_step', 'START')
    return render_template_string(
        HTML_TEMPLATE,
        step=step,
        phone_number=session.get('phone_number'),
        error_message=session.pop('error_message', None),
        session_string=session.get('session_string'),
        clock_fonts=CLOCK_FONTS,
        selected_font_key=session.get('font_key', '1'),
        font_key=session.get('font_key')
    )

@app_flask.route('/start-login', methods=['POST'])
def start_login():
    """Receives phone number and font, sends the verification code."""
    phone = request.form.get('phone_number')
    font_key = request.form.get('font_key', '1')

    if not phone or not phone.startswith('+'):
        session['error_message'] = "شماره تلفن باید وارد شود و شامل کد کشور (مثال: +98) باشد."
        session['login_step'] = 'START'
        return redirect(url_for('home'))

    session['phone_number'] = phone
    session['font_key'] = font_key
    
    result = run_async_in_sync(send_verification_code(phone))

    if result["success"]:
        session['phone_code_hash'] = result['phone_code_hash']
        session['login_step'] = 'CODE'
    else:
        session['error_message'] = result.get('error', 'خطای نامشخص در ارسال کد.')
        session['login_step'] = 'START'
        
    return redirect(url_for('home'))

@app_flask.route('/submit-code', methods=['POST'])
def submit_code():
    """Receives and validates the verification code."""
    code = request.form.get('code')
    phone = session.get('phone_number')
    p_hash = session.get('phone_code_hash')

    if not all([code, phone, p_hash]):
        session['error_message'] = "اطلاعات جلسه ناقص است یا کد تایید منقضی شده. لطفاً از ابتدا شروع کنید."
        return redirect(url_for('reset'))

    session['verification_code'] = code 

    result = run_async_in_sync(sign_in_and_get_session(phone, p_hash, code))

    if result.get("success"):
        session['session_string'] = result['session_string']
        session['login_step'] = 'DONE'
    elif result.get("needs_password"):
        session['login_step'] = 'PASSWORD'
    else:
        error_message = result.get('error', 'خطای نامشخص.')
        session['error_message'] = error_message

        # If it's a simple wrong code error, stay on CODE step
        if "کد تایید وارد شده اشتباه است" in error_message:
             session['login_step'] = 'CODE' 
        else:
             # For expired code or fatal errors, reset completely
             logging.warning(f"Fatal error during sign-in: {error_message}. Resetting session.")
             return redirect(url_for('reset'))

    return redirect(url_for('home'))


@app_flask.route('/submit-password', methods=['POST'])
def submit_password():
    """Receives the 2FA password and completes the login."""
    password = request.form.get('password')
    phone = session.get('phone_number')
    p_hash = session.get('phone_code_hash')
    code = session.get('verification_code')

    if not all([password, phone, p_hash, code]):
        session['error_message'] = "اطلاعات جلسه ناقص است. لطفاً از ابتدا شروع کنید."
        return redirect(url_for('reset'))

    result = run_async_in_sync(sign_in_and_get_session(phone, p_hash, code, password))

    if result.get("success"):
        session['session_string'] = result['session_string']
        session['login_step'] = 'DONE'
    else:
        session['error_message'] = result.get('error')
        
        # If password was wrong, stay on PASSWORD step
        if result.get("needs_password"):
            session['login_step'] = 'PASSWORD'
        else:
            # Fatal error, reset completely
            logging.warning(f"Fatal error during 2FA: {session['error_message']}. Resetting session.")
            return redirect(url_for('reset'))

    return redirect(url_for('home'))


@app_flask.route('/reset')
def reset():
    """Clears the user session and returns to the start page."""
    session.clear()
    session['error_message'] = "فرآیند ورود ریست شد. لطفاً دوباره تلاش کنید."
    return redirect(url_for('home'))


if __name__ == "__main__":
    logging.info("Starting Flask server for login interface...")
    port = int(os.environ.get('PORT', 8080))
    app_flask.run(host='0.0.0.0', port=port, debug=False)
