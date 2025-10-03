import asyncio
import os
import logging
from pyrogram import Client
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PasswordHashInvalid,
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
# برای استفاده از session در فلاسک، یک کلید امنیتی لازم است
app_flask.secret_key = os.urandom(24)

# --- دیکشنری فونت‌ها برای ساعت ---
FONT_STYLES = {
    "normal": {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "stylized": {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':' : '},
    "bold": {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "monospace": {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
}

# --- مدیریت وضعیت برنامه ---
# دیگر از APP_STATE سراسری استفاده نمی‌کنیم و به جای آن از session فلاسک بهره می‌بریم
# این کار باعث می‌شود هر کاربر وضعیت لاگین خودش را داشته باشد
EVENT_LOOP = asyncio.new_event_loop()

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
        strong { color: #0056b3; }
        form { display: flex; flex-direction: column; gap: 15px; margin-top: 20px; }
        input, select { padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; text-align: left; direction: ltr; font-family: 'Vazirmatn', sans-serif; }
        select { text-align: right; direction: rtl; }
        button { padding: 12px; background-color: #007bff; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; font-family: 'Vazirmatn', sans-serif; }
        button:hover { background-color: #0056b3; }
        .error { color: #d93025; margin-top: 15px; font-weight: bold; }
        .success { color: #1e8e3e; font-size: 1.2em; font-weight: bold; }
        .info { color: #555; font-style: italic; }
        .session-box { margin-top: 25px; padding: 15px; background-color: #e9f5ff; border: 1px solid #b3d7ff; border-radius: 8px; text-align: left; direction: ltr; }
        .session-box strong { color: #d93025; }
        .session-box textarea { width: 100%; min-height: 100px; margin-top: 10px; font-family: monospace; background: #f4f4f4; border: 1px solid #ddd; padding: 10px; box-sizing: border-box; border-radius: 6px; }
        label { font-weight: bold; color: #555; display: block; margin-bottom: 5px; text-align: right; }
    </style>
</head>
<body>
    <div class="container">
        {% if step == 'GET_PHONE' %}
            <h1>ورود به سلف بات</h1>
            <p>شماره تلگرام خود را به همراه کد کشور وارد کرده و استایل فونت ساعت را انتخاب کنید.</p>
            <form action="{{ url_for('login') }}" method="post">
                <input type="hidden" name="action" value="phone">
                <div>
                    <label for="phone">شماره تلفن</label>
                    <input type="tel" id="phone" name="phone_number" placeholder="+989123456789" required autofocus>
                </div>
                <div>
                    <label for="font">استایل فونت ساعت</label>
                    <select id="font" name="font_style">
                        <option value="stylized">فانتزی (پیش‌فرض)</option>
                        <option value="normal">معمولی</option>
                        <option value="bold">ضخیم</option>
                        <option value="monospace">ماشین تحریر</option>
                    </select>
                </div>
                <button type="submit">ارسال کد تایید</button>
            </form>
        {% elif step == 'GET_CODE' %}
            <h1>کد تایید</h1>
            <p>کدی به حساب تلگرام با شماره <strong>{{ phone_number }}</strong> ارسال شد. لطفاً آن را وارد کنید.</p>
            <form action="{{ url_for('login') }}" method="post">
                <input type="hidden" name="action" value="code">
                <input type="text" name="code" placeholder="Verification Code" required>
                <button type="submit">تایید کد</button>
            </form>
        {% elif step == 'GET_PASSWORD' %}
            <h1>رمز دو مرحله‌ای</h1>
            <p>حساب شما نیاز به رمز تایید دو مرحله‌ای دارد. لطفاً آن را وارد کنید.</p>
            <form action="{{ url_for('login') }}" method="post">
                <input type="hidden" name="action" value="password">
                <input type="password" name="password" placeholder="2FA Password" required>
                <button type="submit">ورود</button>
            </form>
        {% elif step == 'SHOW_SESSION' %}
            <h1 class="success">✅ ورود موفق!</h1>
            <p>ربات برای لحظاتی فعال شد تا عملکرد آن را ببینید. برای فعال‌سازی دائمی، مراحل زیر را دنبال کنید.</p>
            <div class="session-box">
                <p><strong>۱. این Session String را کپی کنید:</strong></p>
                <textarea readonly onclick="this.select()">{{ session_string }}</textarea>
                <p style="margin-top: 15px;"><strong>۲. این رشته را در متغیر محیطی (Environment Variable) به نام <code>SESSION_STRING</code> در هاست خود (مثلا Render) ذخیره کنید و سرویس را ری‌استارت کنید.</strong></p>
            </div>
             <form action="{{ url_for('home') }}" method="get" style="margin-top: 20px;"><button type="submit">ورود با شماره جدید</button></form>
        {% endif %}

        {% if error_message %}
            <p class="error">{{ error_message }}</p>
        {% endif %}
    </div>
</body>
</html>
"""

# --- توابع کمکی ---
def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

async def update_name_once(client: Client, font_style: str):
    """نام کاربر را فقط یک بار برای نمایش عملکرد ربات آپدیت می‌کند."""
    try:
        me = await client.get_me()
        original_name = me.first_name
        
        # حذف ساعت قبلی اگر وجود داشته باشد
        parts = original_name.rsplit(' ', 1)
        if len(parts) > 1:
            last_part = parts[-1]
            # یک بررسی ساده برای اینکه آیا بخش آخر شبیه ساعت است یا نه
            if ':' in last_part and any(char.isdigit() for char in last_part):
                 original_name = parts[0]
        
        tehran_time = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M")
        stylized_time = stylize_time(tehran_time, font_style)
        
        new_name = f"{original_name} {stylized_time}"
        await client.update_profile(first_name=new_name)
        logging.info(f"نام کاربر '{original_name}' به صورت موقت آپدیت شد.")
        return original_name
    except Exception as e:
        logging.error(f"خطا در آپدیت موقت نام: {e}")
        return "کاربر"


# --- مسیرهای وب (Routes) ---
@app_flask.route('/')
def home():
    session.clear() # با هر بار باز کردن صفحه اصلی، اطلاعات قبلی پاک می‌شود
    return render_template_string(HTML_TEMPLATE, step='GET_PHONE')

@app_flask.route('/login', methods=['POST'])
def login():
    action = request.form.get('action')
    
    try:
        if action == 'phone':
            phone = request.form.get('phone_number')
            font = request.form.get('font_style')
            session['phone_number'] = phone
            session['font_style'] = font
            
            async def send_code_task():
                # برای هر کاربر یک کلاینت جدید در حافظه ساخته می‌شود
                client = Client(f"user_{phone}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
                await client.connect()
                sent_code = await client.send_code(phone)
                session['phone_code_hash'] = sent_code.phone_code_hash
                await client.disconnect()

            future = asyncio.run_coroutine_threadsafe(send_code_task(), EVENT_LOOP)
            future.result(timeout=30)
            return render_template_string(HTML_TEMPLATE, step='GET_CODE', phone_number=phone)

        elif action == 'code':
            code = request.form.get('code')
            phone = session.get('phone_number')
            p_hash = session.get('phone_code_hash')

            async def sign_in_task():
                client = Client(f"user_{phone}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
                await client.connect()
                try:
                    await client.sign_in(phone, p_hash, code)
                    session_str = await client.export_session_string()
                    await update_name_once(client, session.get('font_style'))
                    await client.disconnect()
                    return session_str, None
                except SessionPasswordNeeded:
                    await client.disconnect()
                    return None, 'GET_PASSWORD'
            
            future = asyncio.run_coroutine_threadsafe(sign_in_task(), EVENT_LOOP)
            session_string, next_step = future.result(timeout=30)

            if next_step:
                return render_template_string(HTML_TEMPLATE, step=next_step)
            else:
                return render_template_string(HTML_TEMPLATE, step='SHOW_SESSION', session_string=session_string)

        elif action == 'password':
            password = request.form.get('password')
            phone = session.get('phone_number')

            async def check_password_task():
                client = Client(f"user_{phone}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
                await client.connect()
                await client.check_password(password)
                session_str = await client.export_session_string()
                await update_name_once(client, session.get('font_style'))
                await client.disconnect()
                return session_str

            future = asyncio.run_coroutine_threadsafe(check_password_task(), EVENT_LOOP)
            session_string = future.result(timeout=30)
            return render_template_string(HTML_TEMPLATE, step='SHOW_SESSION', session_string=session_string)
            
    except Exception as e:
        logging.error(f"خطا در مرحله '{action}': {e}", exc_info=True)
        error_msg = "یک خطای پیش‌بینی نشده رخ داد. لطفا دوباره تلاش کنید."
        if isinstance(e, PhoneCodeInvalid): error_msg = "کد وارد شده اشتباه است."
        elif isinstance(e, PasswordHashInvalid): error_msg = "رمز عبور دو مرحله‌ای اشتباه است."
        
        session.clear()
        return render_template_string(HTML_TEMPLATE, step='GET_PHONE', error_message=error_msg)
    
    return redirect(url_for('home'))

# --- اجرای برنامه ---
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    logging.info("در حال اجرای برنامه...")
    
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info("✅ وب سرور برای تولید Session String اجرا شد.")
    
    # حلقه رویداد اصلی را برای کارهای پس‌زمینه اجرا می‌کنیم
    try:
        EVENT_LOOP.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logging.info("در حال متوقف کردن برنامه...")
    finally:
        EVENT_LOOP.close()

