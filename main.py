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
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, render_template_string, redirect, session, url_for
from threading import Thread

# --- تنظیمات لاگ‌نویسی ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

# =======================================================
# ⚠️ تنظیمات اصلی از متغیرهای محیطی خوانده می‌شود
# =======================================================
API_ID = os.environ.get("28190856")
API_HASH = os.environ.get("6b9b5309c2a211b526c6ddad6eabb52")

# بررسی متغیرهای حیاتی
if not API_ID or not API_HASH:
    logging.critical("CRITICAL ERROR: API_ID or API_HASH environment variables are not set!")
    # برای تست محلی، می‌توان مقادیر پیش‌فرض قرار داد
    API_ID = os.environ.get("API_ID", "28190856")
    API_HASH = os.environ.get("API_HASH", "6b9b5309c2a211b526c6ddad6eabb521")


# --- تعریف فونت‌های ساعت ---
CLOCK_FONTS = {
    "1": {"name": "Style 1 (Fullwidth)", "from": '0123456789:', "to": '𝟬𝟭𝟮𝟯𝟺𝟻𝟼𝟳𝟾𝟵:'},
    "2": {"name": "Style 2 (Circled)", "from": '0123456789:', "to": '⓪①②③④⑤⑥⑦⑧⑨:'},
    # 🌟 اصلاح شد: کاراکترهای Double Struck صحیح برای نمایش بهتر
    "3": {"name": "Style 3 (Double Struck)", "from": '0123456789:', "to": '𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡:'}, 
    "4": {"name": "Style 4 (Monospace)", "from": '0123456789:', "to": '０１２３４５６７８９:'},
}

# --- متغیرهای برنامه ---
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
app_flask = Flask(__name__)
# ⚠️ کلید امنیتی
app_flask.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_very_secret_and_random_key_for_flask_sessions')


# --- فیلتر Jinja2 برای پیش‌نمایش فونت ---
def jinja_stylize_preview(time_str: str, to_chars: str) -> str:
    """فیلتر Jinja برای نمایش پیش‌نمایش فونت در قالب."""
    from_chars = '0123456789:'
    # این خط قبلاً به دلیل طول نامساوی در Style 3 خطا می‌داد که اکنون برطرف شد.
    translation_map = str.maketrans(from_chars, to_chars)
    return time_str.translate(translation_map)

app_flask.jinja_env.filters['stylize_preview'] = jinja_stylize_preview


# --- قالب‌های HTML ---
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
        .info { color: #555; }
        .session-info { margin-top: 25px; padding: 15px; background-color: #e6f7ff; border: 1px solid #91d5ff; border-radius: 8px; text-align: right; }
        .session-info strong { color: #d93025; }
        textarea { width: 100%; height: 120px; direction: ltr; text-align: left; margin-top: 10px; font-family: monospace; border-radius: 8px; border-color: #ccc; padding: 10px; resize: vertical; }
    </style>
</head>
<body>
    <div class="container">
        {% if step == 'START' %}
            <h1>تنظیم سلف بات ساعت</h1>
            <p>برای نمایش ساعت کنار نام تلگرام خود، وارد شوید.</p>
            <form action="{{ url_for('start_login') }}" method="post">
                <label for="phone">شماره تلفن (با کد کشور)</label>
                <input type="tel" id="phone" name="phone_number" placeholder="+989123456789" required autofocus value="{{ phone_number or '' }}">
                                
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
            <a href="{{ url_for('reset') }}" style="font-size: 0.9em; color: #666; margin-top: 15px; display: block;">تغییر شماره یا تلاش مجدد</a>

        {% elif step == 'PASSWORD' %}
            <h1>مرحله ۲: رمز دو مرحله‌ای</h1>
            <p>حساب شما دارای تایید دو مرحله‌ای است. لطفاً رمز خود را وارد کنید.</p>
            <form action="{{ url_for('submit_password') }}" method="post">
                <input type="password" name="password" placeholder="رمز عبور دو مرحله‌ای" required autofocus>
                <button type="submit">ورود</button>
            </form>

        {% elif step == 'DONE' %}
            <h1 class="success">✅ موفقیت آمیز بود!</h1>
            <p>کلید نشست (Session String) شما با موفقیت ساخته شد. این کلید برای اجرای ربات ضروری است.</p>
            <div class="session-info">
                <strong>اقدام نهایی و مهم:</strong>
                <ol style="padding-right: 20px;">
                    <li>متن زیر را به طور کامل کپی کنید.</li>
                    <li>در تنظیمات هاست یا سرور خود (مثلاً Render)، یک متغیر محیطی (Environment Variable) با نام <code>SESSION_STRING</code> بسازید و متن کپی شده را در مقدار آن قرار دهید.</li>
                    <li>یک متغیر محیطی دیگر با نام <code>FIRST_NAME</code> بسازید و نامی که میخواهید نمایش داده شود را در آن قرار دهید (مثلا <code>FIRST_NAME=Amir</code>).</li>
                    <li>یک متغیر دیگر با نام <code>FONT_KEY</code> بسازید و مقدار آن را <code>{{ font_key }}</code> قرار دهید تا فونت انتخابی شما اعمال شود.</li>
                    <li>در نهایت، سرویس خود را ری‌استارت (Restart) کنید.</li>
                </ol>
            </div>
            <textarea readonly onclick="this.select()">{{ session_string }}</textarea>

        {% endif %}

        {% if error_message %}
            <p class="error">{{ error_message }}</p>
        {% endif %}
    </div>
</body>
</html>
"""

# --- توابع ناهمگام برای کار با Pyrogram ---
async def send_verification_code(phone_number):
    """
    یک کلاینت موقت برای ارسال کد تایید ایجاد می‌کند. Pyrogram خودکار بهترین DC را پیدا می‌کند.
    """
    client = Client(
        name=str(phone_number), 
        api_id=API_ID, 
        api_hash=API_HASH, 
        in_memory=True, 
        phone_number=phone_number, 
        # phone_code_hash="",  # ❌ این پارامتر حذف شد، زیرا باعث خطای TypeError در Pyrogram میشد
    )

    try:
        await client.connect()
        sent_code = await client.send_code(phone_number)
        await client.disconnect()
        return {"success": True, "phone_code_hash": sent_code.phone_code_hash}
    except (PhoneNumberInvalid, TypeError) as e:
        logging.error(f"Invalid phone number provided: {e}")
        await client.disconnect()
        return {"success": False, "error": "شماره تلفن وارد شده نامعتبر است. لطفاً با کد کشور (مثال: +98...) وارد کنید."}
    except FloodWait as e:
        logging.warning(f"Flood wait for {e.value} seconds.")
        await client.disconnect()
        return {"success": False, "error": f"تلگرام شما را به دلیل درخواست‌های زیاد موقتاً محدود کرده است. لطفاً {e.value} ثانیه دیگر دوباره تلاش کنید."}
    except Exception as e:
        error_type = type(e).__name__
        logging.error(f"An unexpected error occurred during send_code: {error_type} - {e}", exc_info=True)
        await client.disconnect()
        detailed_error = f"خطای پیش‌بینی نشده‌ای هنگام ارسال کد رخ داد. (نوع خطا: {error_type})"
        if error_type in ["ApiIdInvalid", "ApiKeyInvalid"]:
            detailed_error += " لطفاً مطمئن شوید که API_ID و API_HASH به درستی به عنوان متغیرهای محیطی تنظیم شده‌اند."
        return {"success": False, "error": detailed_error}


async def sign_in_and_get_session(phone_number, phone_code_hash, code, password=None):
    """
    با استفاده از اطلاعات کاربر، وارد حساب شده و Session String را برمی‌گرداند.
    """
    client = Client(name=str(phone_number), api_id=API_ID, api_hash=API_HASH, in_memory=True)
    try:
        await client.connect()
        
        # تلاش برای ورود با کد
        try:
            await client.sign_in(phone_number, phone_code_hash, code)
        except SessionPasswordNeeded:
            if not password:
                await client.disconnect()
                return {"success": False, "needs_password": True}
            # اگر رمز عبور ارائه شده بود، آن را چک می‌کنیم
            await client.check_password(password)

        session_string = await client.export_session_string()
        await client.disconnect()
        return {"success": True, "session_string": session_string}

    except PhoneCodeInvalid:
        await client.disconnect()
        return {"success": False, "error": "کد تایید وارد شده اشتباه است."}
    
    # مدیریت خطای منقضی شدن کد 
    except PhoneCodeExpired: 
        await client.disconnect()
        logging.error("PhoneCodeExpired: The user took too long to enter the code.")
        return {"success": False, "error": "کد تایید منقضی شده است. کدهای تلگرام سریعاً منقضی می‌شوند. لطفاً برگردید و دوباره تلاش کنید."}
        
    except PasswordHashInvalid:
        await client.disconnect()
        return {"success": False, "error": "رمز عبور دو مرحله‌ای اشتباه است.", "needs_password": True}
    except Exception as e:
        error_type = type(e).__name__
        logging.error(f"An unexpected error occurred during sign_in: {error_type} - {e}", exc_info=True)
        await client.disconnect()
        
        detailed_error = f"خطای پیش‌بینی نشده‌ای در هنگام ورود رخ داد. (نوع خطا: {error_type})"
        
        if error_type in ["ApiIdInvalid", "ApiKeyInvalid"]:
            detailed_error += " لطفاً مطمئن شوید که API_ID و API_HASH به درستی به عنوان متغیرهای محیطی تنظیم شده‌اند."
        elif "Telegram is having internal issues" in str(e):
            detailed_error = "تلگرام در حال حاضر با مشکلات داخلی مواجه است. لطفاً چند دقیقه دیگر دوباره تلاش کنید."

        return {"success": False, "error": detailed_error}

# =======================================================
# تابع کمکی برای اجرای کدهای ناهمگام (Async) در توابع همگام (Sync)
# =======================================================
def run_async_in_sync(coroutine):
    """
    اجرای یک Coroutine در یک حلقه رویداد جدید برای جلوگیری از خطای RuntimeError
    هنگام استفاده از asyncio.run در محیط‌های چندرشته‌ای.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)
    except Exception as e:
        # تغییر: ثبت کامل traceback برای تشخیص خطای سیستمی واقعی
        logging.error(f"Async execution failed: {e}", exc_info=True) 
        return {"success": False, "error": "خطای سیستمی در اجرای فرآیند تلگرام رخ داد. لطفاً لاگ‌های سرور (Render) را برای جزئیات بررسی کنید."}


# --- مسیرهای Flask ---
@app_flask.route('/')
def home():
    """صفحه اصلی را بر اساس وضعیت جلسه کاربر نمایش می‌دهد."""
    step = session.get('login_step', 'START')
    return render_template_string(
        HTML_TEMPLATE,
        step=step,
        phone_number=session.get('phone_number'),
        error_message=session.pop('error_message', None), # خطا را فقط یک بار نمایش بده
        session_string=session.get('session_string'),
        clock_fonts=CLOCK_FONTS,
        selected_font_key=session.get('font_key', '1'),
        font_key=session.get('font_key')
    )

@app_flask.route('/start-login', methods=['POST'])
def start_login():
    """شماره تلفن و فونت را از کاربر دریافت کرده و کد تایید ارسال می‌کند."""
    phone = request.form.get('phone_number')
    font_key = request.form.get('font_key', '1')

    if not phone:
        session['error_message'] = "وارد کردن شماره تلفن الزامی است."
        return redirect(url_for('home'))

    session['phone_number'] = phone
    session['font_key'] = font_key
    
    # اجرای تابع ناهمگام برای ارسال کد (با استفاده از تابع کمکی جدید)
    result = run_async_in_sync(send_verification_code(phone))

    if result["success"]:
        session['phone_code_hash'] = result['phone_code_hash']
        session['login_step'] = 'CODE'
    else:
        # اگر خطای سیستمی رخ داده باشد، آن را نمایش می‌دهیم
        session['error_message'] = result.get('error', 'خطای نامشخص.')
        session['login_step'] = 'START'
        
    return redirect(url_for('home'))

@app_flask.route('/submit-code', methods=['POST'])
def submit_code():
    """کد تایید را دریافت و بررسی می‌کند."""
    code = request.form.get('code')
    phone = session.get('phone_number')
    p_hash = session.get('phone_code_hash')

    if not all([code, phone, p_hash]):
        session['error_message'] = "اطلاعات جلسه ناقص است. لطفاً از ابتدا شروع کنید."
        return redirect(url_for('reset'))

    session['verification_code'] = code # کد را برای مرحله رمز عبور ذخیره می‌کنیم

    result = run_async_in_sync(sign_in_and_get_session(phone, p_hash, code))

    if result.get("success"):
        session['session_string'] = result['session_string']
        session['login_step'] = 'DONE'
    elif result.get("needs_password"):
        session['login_step'] = 'PASSWORD'
    else:
        session['error_message'] = result.get('error')
        session['login_step'] = 'CODE' # اجازه تلاش مجدد برای وارد کردن کد

    return redirect(url_for('home'))


@app_flask.route('/submit-password', methods=['POST'])
def submit_password():
    """رمز دو مرحله‌ای را دریافت و لاگین را تکمیل می‌کند."""
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
        # اگر رمز اشتباه بود، به همان مرحله رمز برمی‌گردیم
        if result.get("needs_password"):
            session['login_step'] = 'PASSWORD'
        else: # اگر خطای دیگری بود به مرحله کد برمی‌گردیم
            session['login_step'] = 'CODE'

    return redirect(url_for('home'))


@app_flask.route('/reset')
def reset():
    """جلسه کاربر را پاک کرده و به صفحه شروع برمی‌گرداند."""
    session.clear()
    return redirect(url_for('home'))


# =======================================================
# بخش اجرای ربات اصلی (وقتی Session String تنظیم شده باشد)
# =======================================================
async def update_name_task(client: Client, first_name: str, font_key: str):
    """تسک اصلی که نام را در تلگرام به‌روزرسانی می‌کند."""
    font_data = CLOCK_FONTS.get(font_key, CLOCK_FONTS["1"])
    font_map = str.maketrans(font_data["from"], font_data["to"])
    logging.info(f"Update name task started. Display name: '{first_name}', Font: '{font_data['name']}'")
    
    while True:
        try:
            tehran_time = datetime.now(TEHRAN_TIMEZONE)
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time = current_time_str.translate(font_map)
            
            name_with_clock = f"{first_name} {stylized_time}"
            
            await client.update_profile(first_name=name_with_clock)
            
            # محاسبه زمان خواب تا ابتدای دقیقه بعدی
            now = datetime.now(TEHRAN_TIMEZONE)
            sleep_duration = 60 - now.second
            await asyncio.sleep(sleep_duration)

        except FloodWait as e:
            logging.warning(f"Telegram flood limit. Waiting for {e.value + 5} seconds.")
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            logging.error(f"Error updating name: {e}", exc_info=True)
            # در صورت بروز خطا، ۶۰ ثانیه صبر می‌کنیم تا از خطاهای مکرر جلوگیری شود
            await asyncio.sleep(60)

async def run_bot():
    """ربات را با استفاده از SESSION_STRING اجرا می‌کند."""
    SESSION_STRING = os.environ.get("SESSION_STRING")
    FIRST_NAME = os.environ.get("FIRST_NAME", "Telegram Clock")
    FONT_KEY = os.environ.get("FONT_KEY", "1")

    if not SESSION_STRING:
        logging.warning("SESSION_STRING not found. Bot will not run. Web interface is active.")
        return

    logging.info("SESSION_STRING found. Starting the main bot...")
    client = Client(name="clock_self_bot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)

    try:
        await client.start()
        user = await client.get_me()
        logging.info(f"Successfully logged in as {user.first_name} (@{user.username}).")
        
        # اجرای تسک آپدیت نام با فونت انتخابی
        await update_name_task(client, FIRST_NAME, FONT_KEY)
        
    except Exception as e:
        logging.critical(f"Failed to start bot with session string: {e}")
        logging.critical("The session string might be invalid or expired. Please generate a new one using the web interface.")
    finally:
        if client.is_connected:
            await client.stop()
        logging.info("Bot stopped.")


def run_flask_app():
    """برنامه Flask را در یک ترد جداگانه اجرا می‌کند."""
    port = int(os.environ.get('PORT', 8080))
    # در محیط پروداکشن باید از یک وب سرور مثل Gunicorn استفاده کرد.
    app_flask.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    # اگر SESSION_STRING وجود داشته باشد، ربات اصلی را اجرا کن
    if os.environ.get("SESSION_STRING"):
        asyncio.run(run_bot())
    else:
        # در غیر این صورت، وب سرور را برای لاگین و تولید SESSION_STRING اجرا کن
        logging.info("No SESSION_STRING found. Starting Flask server for login...")
        run_flask_app()
