# -*- coding: utf-8 -*-

import os
import sqlite3
import logging
import asyncio
from threading import Thread
from datetime import datetime, timedelta
import random
import math
import re
import sys
import atexit

# کتابخانه‌های وب برای زنده نگه داشتن ربات در Render
from flask import Flask

# کتابخانه‌های ربات تلگرام
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    User,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

# کتابخانه برای بخش Self Pro (Userbot)
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    PasswordHashInvalid
)

# تنظیمات لاگ‌گیری برای دیباگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- بخش وب سرور برای Ping ---
web_app = Flask(__name__)

@web_app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- تنظیمات اولیه و متغیرها ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "7998966950:AAGEaASYQ8S16ADyl0x5-ucSe2oWPpJHMbg")
API_ID = int(os.environ.get("API_ID", "9536480"))
API_HASH = os.environ.get("API_HASH", "4e52f6f12c4Tena918009260b6e3d44")
OWNER_ID = int(os.environ.get("OWNER_ID", "7423552124"))

# مسیر دیتابیس و فایل قفل در دیسک پایدار Render
DATA_PATH = os.environ.get("RENDER_DISK_PATH", "data")
DB_PATH = os.path.join(DATA_PATH, "bot_database.db")
SESSION_PATH = DATA_PATH
LOCK_FILE_PATH = os.path.join(DATA_PATH, "bot.lock")


os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# --- مراحل ConversationHandler ---
# مراحل خرید
(
    ASK_DIAMOND_AMOUNT,
    AWAIT_RECEIPT
) = range(2)

# مراحل Self Pro
(
    ASK_PHONE_CONTACT,
    ASK_CODE,
    ASK_PASSWORD
) = range(2, 5)

# مراحل پنل ادمین
(
    ADMIN_PANEL_MAIN,
    SETTING_PRICE,
    SETTING_INITIAL_BALANCE,
    SETTING_SELF_COST,
    SETTING_CHANNEL_LINK,
    SETTING_REFERRAL_REWARD,
    SETTING_PAYMENT_CARD,
    ADMIN_ADD,
    ADMIN_REMOVE
) = range(5, 14)

# --- استایل‌های فونت ---
FONT_STYLES = {
    'normal': "0123456789",
    'monospace': "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿",
    'doublestruck': "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡",
    'stylized': "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫",
    'cursive': "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
}

def stylize_time(time_str: str, style: str) -> str:
    """تبدیل رشته زمان به استایل مورد نظر"""
    if style not in FONT_STYLES:
        style = 'normal'
    
    original_digits = "0123456789"
    styled_digits = FONT_STYLES[style]
    
    translation_table = str.maketrans(original_digits, styled_digits)
    return time_str.translate(translation_table)

# --- مدیریت دیتابیس (SQLite) ---
def db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con, con.cursor()

def setup_database():
    con, cur = db_connect()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            self_active BOOLEAN DEFAULT FALSE,
            self_paused BOOLEAN DEFAULT FALSE,
            phone_number TEXT,
            font_style TEXT DEFAULT 'normal',
            base_first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount_diamonds INTEGER,
            amount_toman INTEGER, receipt_file_id TEXT, status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, approved_by INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER, referred_id INTEGER, reward_granted BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (referrer_id, referred_id)
        )
    """)

    default_settings = {
        "diamond_price": "500", "initial_balance": "10", "self_hourly_cost": "5",
        "referral_reward": "20", "payment_card": "شماره کارت خود را اینجا وارد کنید",
        "mandatory_channel": "@YourChannel"
    }
    for key, value in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
    
    # اطمینان از وجود ادمین اصلی در جدول کاربران و تنظیم موجودی پنج میلیون
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (OWNER_ID,))
    cur.execute("UPDATE users SET balance = 5000000 WHERE user_id = ?", (OWNER_ID,))

    con.commit()
    con.close()
    logger.info("Database setup complete.")

# --- توابع کمکی دیتابیس ---
def get_setting(key):
    con, cur = db_connect()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cur.fetchone()
    con.close()
    return result['value'] if result else None

def update_setting(key, value):
    con, cur = db_connect()
    cur.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    con.commit()
    con.close()

def get_user(user_id, username=None):
    con, cur = db_connect()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        initial_balance = int(get_setting("initial_balance"))
        # ادمین‌ها موجودی اولیه متفاوت دارند
        balance = 5000000 if user_id == OWNER_ID else initial_balance
        cur.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, username, balance))
        con.commit()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
    elif username and user['username'] != username:
        cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        con.commit()
    con.close()
    return user

def update_user_db(user_id, column, value):
    con, cur = db_connect()
    cur.execute(f"UPDATE users SET {column} = ? WHERE user_id = ?", (value, user_id))
    con.commit()
    con.close()

def update_user_balance(user_id, amount, add=True):
    con, cur = db_connect()
    operator = '+' if add else '-'
    cur.execute(f"UPDATE users SET balance = balance {operator} ? WHERE user_id = ?", (amount, user_id))
    con.commit()
    con.close()

def get_admins():
    con, cur = db_connect()
    cur.execute("SELECT user_id FROM admins")
    admins = [row['user_id'] for row in cur.fetchall()]
    con.close()
    return admins

def is_admin(user_id):
    return user_id in get_admins()
    
def get_user_handle(user: User):
    if user.username:
        return f"@{user.username}"
    return user.full_name


# --- کیبوردهای ربات ---
async def main_reply_keyboard(user_id):
    keyboard = [
        [KeyboardButton("💎 موجودی"), KeyboardButton("🚀 Self Pro")],
    ]
    
    row_two = []
    if not is_admin(user_id):
        row_two.append(KeyboardButton("💰 افزایش موجودی"))
    row_two.append(KeyboardButton("🎁 کسب جم رایگان"))
    keyboard.append(row_two)

    if is_admin(user_id):
        keyboard.append([KeyboardButton("👑 پنل ادمین")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("💎 تنظیم قیمت الماس", callback_data="admin_set_price")],
        [InlineKeyboardButton("💰 تنظیم موجودی اولیه", callback_data="admin_set_initial_balance")],
        [InlineKeyboardButton("🚀 تنظیم هزینه سلف", callback_data="admin_set_self_cost")],
        [InlineKeyboardButton("🎁 تنظیم پاداش دعوت", callback_data="admin_set_referral_reward")],
        [InlineKeyboardButton("💳 تنظیم شماره کارت", callback_data="admin_set_payment_card")],
        [InlineKeyboardButton("📢 تنظیم کانال اجباری", callback_data="admin_set_channel")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def self_pro_management_keyboard(user_id):
    user = get_user(user_id)
    
    pause_text = "▶️ فعالسازی ساعت" if user['self_paused'] else "⏸️ توقف ساعت"
    pause_callback = "self_resume" if user['self_paused'] else "self_pause"

    keyboard = [
        [InlineKeyboardButton(pause_text, callback_data=pause_callback)],
        [InlineKeyboardButton("✏️ تغییر فونت", callback_data="change_font_menu")],
        [InlineKeyboardButton("🗑 حذف کامل سلف", callback_data="delete_self_confirm")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def font_selection_keyboard(user_id):
    user_font = get_user(user_id)['font_style']
    keyboard = []
    for style, name in [('normal', 'Normal'), ('monospace', 'Monospace'), ('doublestruck', 'Doublestruck'), ('stylized', 'Stylized'), ('cursive', 'Cursive')]:
        text = f"✅ {name}" if user_font == style else name
        keyboard.append([InlineKeyboardButton(text, callback_data=f"set_font_{style}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_self_menu")])
    return InlineKeyboardMarkup(keyboard)

# --- دستورات اصلی ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_user(user.id, user.username)
    if context.args and len(context.args) > 0:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user.id: logger.info(f"User {user.id} was referred by {referrer_id}")
        except (ValueError, IndexError): pass
    await update.message.reply_text(
        f"سلام {user.first_name}! به ربات Self Pro خوش آمدید. لطفا یک گزینه را انتخاب کنید:",
        reply_markup=await main_reply_keyboard(user.id),
    )

# --- منطق خرید الماس ---
async def buy_diamond_start_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تعداد الماسی که قصد خرید دارید را وارد کنید:")
    return ASK_DIAMOND_AMOUNT

async def ask_diamond_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text)
    except ValueError:
        await update.message.reply_text("لطفا یک عدد صحیح و مثبت وارد کنید.")
        return ASK_DIAMOND_AMOUNT
        
    if amount <= 0:
        await update.message.reply_text("لطفا یک عدد بزرگتر از صفر وارد کنید.")
        return ASK_DIAMOND_AMOUNT
        
    if amount > 10000:
        await update.message.reply_text("مقدار خرید جم باید کمتر یا مساوی ۱۰,۰۰۰ باشد. لطفا مقدار کمتری وارد کنید.")
        return ASK_DIAMOND_AMOUNT

    diamond_price = int(get_setting("diamond_price"))
    total_cost = amount * diamond_price
    payment_card = get_setting("payment_card")
    context.user_data['purchase_amount'] = amount
    context.user_data['purchase_cost'] = total_cost
    text = (f"🧾 **پیش‌فاکتور خرید**\n\n💎 تعداد: {amount}\n💳 مبلغ: {total_cost:,} تومان\n\n"
            f"لطفاً مبلغ را به شماره کارت زیر واریز و سپس عکس رسید را ارسال کنید:\n`{payment_card}`")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return AWAIT_RECEIPT

async def await_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفا فقط عکس رسید را ارسال کنید.")
        return AWAIT_RECEIPT
    user = update.effective_user
    receipt_file_id = update.message.photo[-1].file_id
    amount = context.user_data.get('purchase_amount', 0)
    cost = context.user_data.get('purchase_cost', 0)
    if amount == 0:
        await update.message.reply_text("خطا! فرآیند خرید را مجددا شروع کنید.")
        return ConversationHandler.END

    con, cur = db_connect()
    cur.execute("INSERT INTO transactions (user_id, amount_diamonds, amount_toman, receipt_file_id) VALUES (?, ?, ?, ?)",
                (user.id, amount, cost, receipt_file_id))
    transaction_id = cur.lastrowid
    con.commit()
    con.close()
    await update.message.reply_text("رسید شما دریافت شد. لطفاً تا زمان تایید ادمین صبور باشید.")

    caption = (f" رسید جدید برای تایید\n\nکاربر: @{user.username} ({user.id})\n"
               f"تعداد الماس: {amount}\nمبلغ: {cost:,} تومان")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data=f"approve_{transaction_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"reject_{transaction_id}")]])
    for admin_id in get_admins():
        try: await context.bot.send_photo(chat_id=admin_id, photo=receipt_file_id, caption=caption, reply_markup=keyboard)
        except Exception as e: logger.error(f"Failed to send receipt to admin {admin_id}: {e}")
    return ConversationHandler.END

async def handle_transaction_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    action, transaction_id = query.data.split("_"); transaction_id = int(transaction_id)
    admin_id = query.from_user.id
    con, cur = db_connect()
    cur.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)); tx = cur.fetchone()
    if not tx: await query.edit_message_caption(caption="این تراکنش یافت نشد."); con.close(); return
    if tx['status'] != 'pending':
        await query.edit_message_caption(caption=f"این تراکنش قبلاً به وضعیت «{tx['status']}» تغییر یافته است."); con.close(); return

    user_id, amount = tx['user_id'], tx['amount_diamonds']
    if action == "approve":
        update_user_balance(user_id, amount, add=True)
        cur.execute("UPDATE transactions SET status = 'approved', approved_by = ? WHERE id = ?", (admin_id, transaction_id))
        await query.edit_message_caption(caption=f"✅ تراکنش تایید شد.\n {amount} الماس به کاربر اضافه شد.")
        try: await context.bot.send_message(user_id, f"خرید شما به تعداد {amount} الماس تایید شد.")
        except Exception as e: logger.warning(f"Could not notify user {user_id}: {e}")
    elif action == "reject":
        cur.execute("UPDATE transactions SET status = 'rejected', approved_by = ? WHERE id = ?", (admin_id, transaction_id))
        await query.edit_message_caption(caption="❌ تراکنش رد شد.")
        try: await context.bot.send_message(user_id, "متاسفانه خرید شما رد شد.")
        except Exception as e: logger.warning(f"Could not notify user {user_id}: {e}")
    con.commit(); con.close()

# --- منطق Self Pro ---
user_sessions = {}
async def start_self_activation_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cost = int(get_setting("self_hourly_cost"))
    if get_user(user_id)['balance'] < cost * 24:
        await update.message.reply_text("موجودی شما برای فعال‌سازی سلف (حداقل یک روز) کافی نیست.")
        return ConversationHandler.END
    
    keyboard = [[KeyboardButton("📱 اشتراک‌گذاری شماره تلفن", request_contact=True)]]
    await update.message.reply_text(
        "لطفا برای فعال‌سازی، شماره تلفن خود را از طریق دکمه زیر به اشتراک بگذارید.",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return ASK_PHONE_CONTACT

async def ask_phone_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    phone = f"+{contact.phone_number.lstrip('+')}"
    user_id = update.effective_user.id
    
    await update.message.reply_text("شماره شما دریافت شد. در حال ارسال کد...", reply_markup=ReplyKeyboardRemove())
    
    context.user_data['phone'] = phone
    client = Client(f"user_{user_id}", api_id=API_ID, api_hash=API_HASH, workdir=SESSION_PATH)
    try:
        await client.connect()
        sent_code = await client.send_code(phone)
        context.user_data.update({'phone_code_hash': sent_code.phone_code_hash, 'client': client})
        await update.message.reply_text("کد تایید ارسال شده به تلگرام خود را وارد کنید:"); return ASK_CODE
    except PhoneNumberInvalid:
        await update.message.reply_text("شماره تلفن نامعتبر است. دوباره تلاش کنید.", reply_markup=await main_reply_keyboard(user_id))
        await client.disconnect(); return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error sending code for {phone}: {e}")
        await update.message.reply_text("خطا در اتصال به تلگرام.", reply_markup=await main_reply_keyboard(user_id))
        await client.disconnect(); return ConversationHandler.END

async def ask_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    client = context.user_data.get('client')
    if not client: return ConversationHandler.END

    try:
        await client.sign_in(context.user_data['phone'], context.user_data['phone_code_hash'], code)
        await process_self_activation(update, context, client)
        return ConversationHandler.END
    except SessionPasswordNeeded: await update.message.reply_text("رمز تایید دو مرحله‌ای را وارد کنید:"); return ASK_PASSWORD
    except PhoneCodeInvalid: await update.message.reply_text("کد اشتباه است. مجددا تلاش کنید."); return ASK_CODE
    except Exception as e:
        logger.error(f"Error on sign in: {e}"); await update.message.reply_text("خطا!", reply_markup=await main_reply_keyboard(update.effective_user.id)); await client.disconnect()
        return ConversationHandler.END

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    client = context.user_data.get('client')
    if not client: return ConversationHandler.END
    try:
        await client.check_password(password)
        await process_self_activation(update, context, client)
    except Exception: await update.message.reply_text("رمز عبور اشتباه است.", reply_markup=await main_reply_keyboard(update.effective_user.id)); await client.disconnect()
    return ConversationHandler.END

async def process_self_activation(update: Update, context: ContextTypes.DEFAULT_TYPE, client: Client):
    user_id = update.effective_user.id
    phone = context.user_data['phone']
    
    me = await client.get_me()
    update_user_db(user_id, "base_first_name", me.first_name)
    update_user_db(user_id, "self_active", True)
    update_user_db(user_id, "phone_number", phone)

    user_sessions[user_id] = client
    asyncio.create_task(self_pro_background_task(user_id, client))
    await update.message.reply_text("✅ Self Pro با موفقیت فعال شد!", reply_markup=await main_reply_keyboard(user_id))

async def self_pro_background_task(user_id: int, client: Client):
    if not client.is_connected:
        try: await client.start()
        except Exception as e: logger.error(f"Could not start client for {user_id}: {e}"); return
        
    while user_id in user_sessions:
        user = get_user(user_id)
        if not user or not user['self_active']: break
        
        if not user['self_paused']:
            hourly_cost = int(get_setting("self_hourly_cost"))
            if user['balance'] < hourly_cost:
                update_user_db(user_id, "self_active", False)
                update_user_db(user_id, "self_paused", False)
                await client.stop(); del user_sessions[user_id]
                try: await application.bot.send_message(user_id, "موجودی الماس شما تمام شد و Self Pro غیرفعال گردید.")
                except Exception: pass
                break
            
            update_user_balance(user_id, hourly_cost, add=False)
            try:
                base_name = user['base_first_name'] or (await client.get_me()).first_name
                now_str = datetime.now().strftime("%H:%M")
                styled_time = stylize_time(now_str, user['font_style'])
                await client.update_profile(first_name=f"{base_name} | {styled_time}")
            except Exception as e: logger.error(f"Failed to update profile for {user_id}: {e}")
        
        await asyncio.sleep(3600)
    logger.info(f"Background task for user {user_id} stopped.")

# --- مدیریت Self Pro ---
async def self_pro_menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user['self_active']:
        await update.message.reply_text(
            "⚙️ منوی مدیریت Self Pro:",
            reply_markup=await self_pro_management_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END
    else:
        await start_self_activation_flow(update, context)
        return ASK_PHONE_CONTACT

async def toggle_self_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    new_state = not user['self_paused']
    update_user_db(user_id, 'self_paused', new_state)
    
    status_text = "متوقف" if new_state else "فعال"
    await query.answer(f"ساعت با موفقیت {status_text} شد.")
    await query.edit_message_reply_markup(reply_markup=await self_pro_management_keyboard(user_id))

async def change_font_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text(
        "لطفا یک فونت برای نمایش زمان انتخاب کنید:",
        reply_markup=await font_selection_keyboard(query.from_user.id)
    )

async def set_font(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    font_style = query.data.replace("set_font_", "")
    user_id = query.from_user.id
    update_user_db(user_id, 'font_style', font_style)
    await query.answer(f"فونت با موفقیت به {font_style} تغییر یافت.")
    await query.edit_message_reply_markup(reply_markup=await font_selection_keyboard(user_id))

async def back_to_self_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚙️ منوی مدیریت Self Pro:",
        reply_markup=await self_pro_management_keyboard(query.from_user.id)
    )
    
async def delete_self_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [[
        InlineKeyboardButton(" بله، حذف کن", callback_data="delete_self_final"),
        InlineKeyboardButton(" خیر", callback_data="back_to_self_menu")
    ]]
    await query.answer()
    await query.edit_message_text(
        "آیا از حذف کامل سلف خود مطمئن هستید؟ تمام اطلاعات نشست شما پاک خواهد شد.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def delete_self_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in user_sessions:
        client = user_sessions.pop(user_id)
        if client.is_connected:
            await client.stop()
    
    session_file = os.path.join(SESSION_PATH, f"user_{user_id}.session")
    if os.path.exists(session_file):
        os.remove(session_file)
        
    update_user_db(user_id, 'self_active', False)
    update_user_db(user_id, 'self_paused', False)
    
    await query.answer("سلف شما با موفقیت حذف شد.")
    await query.edit_message_text("سلف شما حذف شد. برای فعال‌سازی مجدد، از منوی اصلی اقدام کنید.")

# ... (بقیه توابع بدون تغییر زیاد) ...
async def check_balance_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user(user.id)
    diamond_price = int(get_setting("diamond_price"))
    toman_equivalent = user_data['balance'] * diamond_price
    
    text = (
        f"👤 کاربر: <b>{get_user_handle(user)}</b>\n\n"
        f"💎 موجودی الماس: <b>{user_data['balance']}</b>\n"
        f"💳 معادل تخمینی: <b>{toman_equivalent:,} تومان</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def referral_menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={update.effective_user.id}"
    reward = get_setting("referral_reward")
    text = (f"🔗 لینک دعوت شما:\n`{referral_link}`\n\nبا هر دعوت موفق {reward} الماس هدیه بگیرید.")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message: return
    
    match = re.search(r'(\d+)', update.message.text)
    if not match: return
        
    try: amount = int(match.group(1))
    except (ValueError, TypeError): return

    if amount <= 0: return
    sender, receiver = update.effective_user, update.message.reply_to_message.from_user
    if sender.id == receiver.id: await update.message.reply_text("انتقال به خود امکان‌پذیر نیست."); return
    if get_user(sender.id)['balance'] < amount: await update.message.reply_text("موجودی شما کافی نیست."); return
    
    get_user(receiver.id, receiver.username)
    
    update_user_balance(sender.id, amount, add=False)
    update_user_balance(receiver.id, amount, add=True)
    
    text = (
        f"✅ <b>انتقال موفق</b> ✅\n\n"
        f"👤 <b>از:</b> {get_user_handle(sender)}\n"
        f"👥 <b>به:</b> {get_user_handle(receiver)}\n"
        f"💎 <b>مبلغ:</b> {amount} الماس"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def group_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    if update.effective_chat.type not in ['group', 'supergroup']: return
    text = update.message.text.strip()
    
    if text == 'موجودی':
        user = update.effective_user
        user_data = get_user(user.id, user.username)
        diamond_price = int(get_setting("diamond_price"))
        toman_equivalent = user_data['balance'] * diamond_price
        reply_text = (
            f"👤 کاربر: <b>{get_user_handle(user)}</b>\n\n"
            f"💎 موجودی الماس: <b>{user_data['balance']}</b>\n"
            f"💳 معادل تخمینی: <b>{toman_equivalent:,} تومان</b>"
        )
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML); return

    if text.startswith('شرطبندی '):
        parts = text.split()
        if len(parts) == 2 and parts[1].isdigit():
            context.args = [parts[1]]
            await start_bet(update, context)
        else: await update.message.reply_text("فرمت صحیح: شرطبندی <مبلغ>"); return

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=await main_reply_keyboard(update.effective_user.id)); return ConversationHandler.END
    
# --- منطق شرط‌بندی ---
async def resolve_bet_logic(chat_id: int, message_id: int, bet_info: dict, context: ContextTypes.DEFAULT_TYPE):
    # نمایش پیام "در حال..." و حذف دکمه‌ها
    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="🎲 در حال مشخص شدن برنده...", reply_markup=None)
    await asyncio.sleep(3) # تاخیر برای هیجان

    participants_data = { p_id: get_user(p_id) for p_id in bet_info['participants'] }
    
    # آزاد کردن کاربران از حالت شرط‌بندی
    if 'users_in_bet' in context.chat_data:
        for p_id in bet_info['participants']:
            context.chat_data['users_in_bet'].discard(p_id)

    winner_id = random.choice(list(participants_data.keys()))
    losers_data = {uid: udata for uid, udata in participants_data.items() if uid != winner_id}
    
    bet_amount = bet_info['amount']
    total_pot = bet_amount * len(participants_data)
    tax = math.ceil(total_pot * 0.05)
    prize = total_pot - tax

    for loser_id in losers_data.keys(): update_user_balance(loser_id, bet_amount, add=False)
    update_user_balance(winner_id, prize, add=True)

    losers_text_list = [f"{get_user_handle(await context.bot.get_chat(uid))}" for uid in losers_data.keys()]
    losers_text = ", ".join(losers_text_list)
    
    result_text = (
        f"<b>◈ ━━━ 🎲 نتیجه شرط‌بندی 🎲 ━━━ ◈</b>\n<b>مبلغ شرط:</b> {bet_amount} الماس\n\n"
        f"🏆 <b>برنده:</b> {get_user_handle(await context.bot.get_chat(winner_id))}\n"
        f"💔 <b>بازنده:</b> {losers_text}\n\n💰 <b>جایزه:</b> {prize} الماس\n🧾 <b>مالیات:</b> {tax} الماس\n"
        f"<b>◈ ━━━ Self Pro ━━━ ◈</b>"
    )
    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=result_text, parse_mode=ParseMode.HTML)

async def end_bet_on_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    bet_info = job.data['bet_info']
    
    # آزاد کردن کاربران
    if 'users_in_bet' in context.chat_data:
        for p_id in bet_info['participants']:
            context.chat_data['users_in_bet'].discard(p_id)

    await context.bot.edit_message_text(
        chat_id=job.chat_id, message_id=job.data['message_id'],
        text="⌛️ زمان شرط‌بندی تمام شد و به دلیل عدم حضور شرکت‌کننده کافی لغو شد.", reply_markup=None)

async def start_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Initialize sets if they don't exist
    if 'users_in_bet' not in context.chat_data:
        context.chat_data['users_in_bet'] = set()

    creator = update.effective_user
    if creator.id in context.chat_data['users_in_bet']:
        await update.message.reply_text("شما در حال حاضر در یک شرط‌بندی دیگر فعال هستید.")
        return

    try:
        amount_str = context.args[0] if context.args else None
        if not amount_str: raise IndexError
        amount = int(amount_str)
        if amount <= 0: await update.message.reply_text("مبلغ شرط باید بیشتر از صفر باشد."); return
    except (IndexError, ValueError):
        await update.message.reply_text("لطفا مبلغ شرط را مشخص کنید. مثال: /bet 100 یا شرطبندی 100"); return

    if get_user(creator.id, creator.username)['balance'] < amount:
        await update.message.reply_text("موجودی شما برای شروع این شرط‌بندی کافی نیست."); return

    bet_info = { 'amount': amount, 'creator_id': creator.id, 'participants': {creator.id} }
    
    bet_message = await update.message.reply_text("در حال ایجاد شرط...")
    
    keyboard = InlineKeyboardMarkup([[ 
        InlineKeyboardButton("✅ پیوستن", callback_data=f"join_bet_{bet_message.message_id}"), 
        InlineKeyboardButton("❌ لغو شرط", callback_data=f"cancel_bet_{bet_message.message_id}")
    ]])

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id, message_id=bet_message.message_id,
        text=f"🎲 شرط‌بندی جدید به مبلغ <b>{amount}</b> الماس توسط {get_user_handle(creator)} شروع شد!\n\n"
             f"نفر دوم که به شرط بپیوندد، برنده مشخص خواهد شد.\n\n"
             f"<b>شرکت کنندگان:</b>\n- {get_user_handle(creator)}",
        reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
    
    job = context.job_queue.run_once(
        end_bet_on_timeout, 60, chat_id=update.effective_chat.id, name=f"bet_{bet_message.message_id}",
        data={'message_id': bet_message.message_id, 'bet_info': bet_info}
    )
    
    bet_info['job'] = job
    # Store bet info using message_id as key
    if 'bets' not in context.chat_data:
        context.chat_data['bets'] = {}
    context.chat_data['bets'][bet_message.message_id] = bet_info
    context.chat_data['users_in_bet'].add(creator.id)

async def join_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user
    message_id = int(query.data.split("_")[-1])

    bets = context.chat_data.get('bets', {})
    if message_id not in bets:
        await query.answer("این شرط‌بندی دیگر فعال نیست.", show_alert=True); return
        
    if user.id in context.chat_data.get('users_in_bet', set()):
        await query.answer("شما در حال حاضر در یک شرط‌بندی دیگر فعال هستید.", show_alert=True); return

    bet_info = bets[message_id]
    if get_user(user.id, user.username)['balance'] < bet_info['amount']:
        await query.answer("موجودی شما برای شرکت در این شرط‌بندی کافی نیست.", show_alert=True); return
        
    bet_info['participants'].add(user.id)
    context.chat_data['users_in_bet'].add(user.id)
    
    await query.answer("شما به شرط پیوستید! نتیجه بلافاصله اعلام می‌شود...", show_alert=False)

    bet_info['job'].schedule_removal()
    # Remove the bet from the active list immediately
    context.chat_data['bets'].pop(message_id, None)
    await resolve_bet_logic(chat_id=update.effective_chat.id, message_id=message_id, bet_info=bet_info, context=context)

async def cancel_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message_id = int(query.data.split("_")[-1])

    bets = context.chat_data.get('bets', {})
    if message_id not in bets:
        await query.answer("این شرط‌بندی دیگر فعال نیست.", show_alert=True); return
    
    bet_info = bets[message_id]
    if query.from_user.id != bet_info['creator_id']:
        await query.answer("فقط شروع‌کننده می‌تواند شرط را لغو کند.", show_alert=True); return

    bet_info['job'].schedule_removal()
    
    # Free up participants
    if 'users_in_bet' in context.chat_data:
        for p_id in bet_info['participants']:
            context.chat_data['users_in_bet'].discard(p_id)
            
    # Remove bet
    context.chat_data['bets'].pop(message_id, None)

    await query.message.edit_text(f"🎲 شرط‌بندی توسط {get_user_handle(query.from_user)} لغو شد.")
    await query.answer("شرط با موفقیت لغو شد.")

# --- پنل ادمین (مکالمه) ---
async def admin_panel_entry_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("شما دسترسی به این بخش را ندارید."); return ConversationHandler.END
    await update.message.reply_text("👑 به پنل ادمین خوش آمدید:", reply_markup=await admin_panel_keyboard())
    return ADMIN_PANEL_MAIN

async def ask_for_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    setting_map = {
        "admin_set_price": ("diamond_price", "💎 قیمت جدید هر الماس به تومان را وارد کنید:", SETTING_PRICE),
        "admin_set_initial_balance": ("initial_balance", "💰 موجودی اولیه کاربران جدید را وارد کنید:", SETTING_INITIAL_BALANCE),
        "admin_set_self_cost": ("self_hourly_cost", "🚀 هزینه ساعتی سلف را وارد کنید:", SETTING_SELF_COST),
        "admin_set_referral_reward": ("referral_reward", "🎁 پاداش دعوت را وارد کنید:", SETTING_REFERRAL_REWARD),
        "admin_set_payment_card": ("payment_card", "💳 شماره کارت جدید را وارد کنید:", SETTING_PAYMENT_CARD),
        "admin_set_channel": ("mandatory_channel", "📢 آیدی کانال اجباری (با @) را وارد کنید:", SETTING_CHANNEL_LINK),
    }
    setting_key, prompt, next_state = setting_map[query.data]
    context.user_data["setting_key"] = setting_key
    await query.edit_message_text(prompt); return next_state

async def receive_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_value = update.message.text
    setting_key = context.user_data.pop("setting_key", None)
    if not setting_key:
        await update.message.reply_text("خطا! لطفا دوباره از پنل ادمین تلاش کنید."); return ADMIN_PANEL_MAIN
    update_setting(setting_key, new_value)
    await update.message.reply_text("✅ تنظیمات با موفقیت ذخیره شد.")
    await update.message.reply_text("👑 پنل ادمین:", reply_markup=await admin_panel_keyboard())
    return ADMIN_PANEL_MAIN

def cleanup_lock_file():
    if os.path.exists(LOCK_FILE_PATH):
        os.remove(LOCK_FILE_PATH); logger.info("Lock file removed.")

def main() -> None:
    global application
    setup_database()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    buy_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💰 افزایش موجودی$'), buy_diamond_start_text)],
        states={ASK_DIAMOND_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_diamond_amount)], AWAIT_RECEIPT: [MessageHandler(filters.PHOTO, await_receipt)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False)
    
    self_pro_activation_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🚀 Self Pro$'), self_pro_menu_text_handler)],
        states={ASK_PHONE_CONTACT: [MessageHandler(filters.CONTACT, ask_phone_contact)], ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_code)], ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False)
    
    admin_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^👑 پنل ادمین$'), admin_panel_entry_text)],
        states={
            ADMIN_PANEL_MAIN: [CallbackQueryHandler(ask_for_setting, pattern=r"admin_set_")],
            SETTING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_INITIAL_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_SELF_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_REFERRAL_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_PAYMENT_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
        }, fallbacks=[CommandHandler("cancel", cancel)], per_message=False)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(buy_conv); application.add_handler(self_pro_activation_conv); application.add_handler(admin_conv)
    
    application.add_handler(CommandHandler("bet", start_bet, filters=filters.ChatType.GROUPS))
    application.add_handler(CallbackQueryHandler(join_bet, pattern=r"^join_bet_"))
    application.add_handler(CallbackQueryHandler(cancel_bet, pattern=r"^cancel_bet_"))
    application.add_handler(CallbackQueryHandler(handle_transaction_approval, pattern=r"^(approve|reject)_\d+$"))

    application.add_handler(CallbackQueryHandler(toggle_self_pause, pattern=r"^self_(pause|resume)$"))
    application.add_handler(CallbackQueryHandler(change_font_menu, pattern="^change_font_menu$"))
    application.add_handler(CallbackQueryHandler(set_font, pattern=r"^set_font_"))
    application.add_handler(CallbackQueryHandler(back_to_self_menu, pattern="^back_to_self_menu$"))
    application.add_handler(CallbackQueryHandler(delete_self_confirm, pattern="^delete_self_confirm$"))
    application.add_handler(CallbackQueryHandler(delete_self_final, pattern="^delete_self_final$"))

    application.add_handler(MessageHandler(filters.Regex('^💎 موجودی$'), check_balance_text_handler))
    application.add_handler(MessageHandler(filters.Regex('^🎁 کسب جم رایگان$'), referral_menu_text_handler))
    
    application.add_handler(MessageHandler(filters.REPLY & filters.Regex(r'^(انتقال الماس\s*\d+|\d+)$'), handle_transfer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, group_text_handler))
    
    logger.info("Bot is starting...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    if os.path.exists(LOCK_FILE_PATH):
        logger.critical("Lock file exists. Another instance might be running. Shutting down.")
        sys.exit(1)
    
    with open(LOCK_FILE_PATH, "w") as f: f.write(str(os.getpid()))
    atexit.register(cleanup_lock_file)
    logger.info(f"Lock file created at {LOCK_FILE_PATH}")
    flask_thread = Thread(target=run_flask); flask_thread.daemon = True; flask_thread.start()
    main()

