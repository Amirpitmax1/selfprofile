# -*- coding: utf-8 -*-

import os
import sqlite3
import logging
import asyncio
from threading import Thread
from datetime import datetime, timedelta
import random
import math

# کتابخانه‌های وب برای زنده نگه داشتن ربات در Render
from flask import Flask

# کتابخانه‌های ربات تلگرام
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    User
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
API_HASH = os.environ.get("API_HASH", "4e52f6f12c47a0da918009260b6e3d44")
OWNER_ID = int(os.environ.get("OWNER_ID", "7423552124"))

DB_PATH = os.path.join(os.environ.get("RENDER_DISK_PATH", "data"), "bot_database.db")
SESSION_PATH = os.path.join(os.environ.get("RENDER_DISK_PATH", "data"))

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# --- مراحل ConversationHandler ---
# مراحل خرید
(
    ASK_DIAMOND_AMOUNT,
    AWAIT_RECEIPT
) = range(2)

# مراحل Self Pro
(
    ASK_PHONE,
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
            phone_number TEXT,
            font_style TEXT DEFAULT 'normal',
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
        cur.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, username, initial_balance))
        con.commit()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
    elif username and user['username'] != username:
        # Update username if it has changed
        cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        con.commit()
    con.close()
    return user


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
async def main_menu_keyboard(user_id):
    user = get_user(user_id)
    self_status = "✅ فعال" if user['self_active'] else "❌ غیرفعال"
    keyboard = [
        [InlineKeyboardButton(f"💎 موجودی", callback_data="check_balance")],
        [InlineKeyboardButton(f"🚀 Self Pro ({self_status})", callback_data="self_pro_menu")],
        [InlineKeyboardButton("💰 افزایش موجودی", callback_data="buy_diamond")],
        [InlineKeyboardButton("🎁 کسب جم رایگان", callback_data="referral_menu")],
        [InlineKeyboardButton("🤝 انتقال الماس", callback_data="transfer_diamond_info")],
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 پنل ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

async def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("💎 تنظیم قیمت الماس", callback_data="admin_set_price")],
        [InlineKeyboardButton("💰 تنظیم موجودی اولیه", callback_data="admin_set_initial_balance")],
        [InlineKeyboardButton("🚀 تنظیم هزینه سلف", callback_data="admin_set_self_cost")],
        [InlineKeyboardButton("🎁 تنظیم پاداش دعوت", callback_data="admin_set_referral_reward")],
        [InlineKeyboardButton("💳 تنظیم شماره کارت", callback_data="admin_set_payment_card")],
        [InlineKeyboardButton("📢 تنظیم کانال اجباری", callback_data="admin_set_channel")],
        [InlineKeyboardButton("💳 تراکنش‌های در انتظار", callback_data="admin_pending_transactions")],
        [InlineKeyboardButton("↩️ بازگشت به منوی اصلی", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def self_pro_menu_keyboard(user_id):
    user = get_user(user_id)
    keyboard = []
    if not user['self_active']:
        keyboard.append([InlineKeyboardButton("🚀 فعال‌سازی", callback_data="activate_self_pro")])
    else:
        keyboard.append([InlineKeyboardButton("✏️ تغییر فونت", callback_data="change_font")])
        keyboard.append([InlineKeyboardButton("❌ غیرفعال‌سازی", callback_data="deactivate_self_pro")])
        keyboard.append([InlineKeyboardButton("🗑 حذف کامل", callback_data="delete_self_pro")])
    keyboard.append([InlineKeyboardButton("↩️ بازگشت", callback_data="main_menu")])
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
        f"سلام {user.first_name}! به ربات Self Pro خوش آمدید.",
        reply_markup=await main_menu_keyboard(user.id),
    )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(
            "منوی اصلی:",
            reply_markup=await main_menu_keyboard(query.from_user.id)
        )
    except Exception: # If message is the same
        pass

# --- منطق خرید الماس ---
async def buy_diamond_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تعداد الماسی که قصد خرید دارید را وارد کنید:")
    return ASK_DIAMOND_AMOUNT

async def ask_diamond_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: amount = int(update.message.text)
    except ValueError:
        await update.message.reply_text("لطفا یک عدد صحیح و مثبت وارد کنید.")
        return ASK_DIAMOND_AMOUNT
    if amount <= 0:
        await update.message.reply_text("لطفا یک عدد بزرگتر از صفر وارد کنید.")
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
async def activate_self_pro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id
    user, cost = get_user(user_id), int(get_setting("self_hourly_cost"))
    if user['balance'] < cost * 24:
        await query.edit_message_text("موجودی شما برای فعال‌سازی سلف (حداقل یک روز) کافی نیست.")
        return ConversationHandler.END
    await query.edit_message_text("لطفا شماره تلفن خود را با فرمت +989123456789 ارسال کنید.")
    return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text; user_id = update.effective_user.id
    context.user_data['phone'] = phone
    client = Client(f"user_{user_id}", api_id=API_ID, api_hash=API_HASH, workdir=SESSION_PATH)
    try:
        await client.connect()
        sent_code = await client.send_code(phone)
        context.user_data.update({'phone_code_hash': sent_code.phone_code_hash, 'client': client})
        await update.message.reply_text("کد تایید ارسال شده به تلگرام خود را وارد کنید:"); return ASK_CODE
    except PhoneNumberInvalid: await update.message.reply_text("شماره تلفن نامعتبر است. دوباره تلاش کنید."); await client.disconnect(); return ASK_PHONE
    except Exception as e:
        logger.error(f"Error sending code for {phone}: {e}")
        await update.message.reply_text("خطا در اتصال به تلگرام."); await client.disconnect(); return ConversationHandler.END

async def ask_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    client = context.user_data['client']
    try:
        await client.sign_in(context.user_data['phone'], context.user_data['phone_code_hash'], code)
        await process_self_activation(update, context, client)
        return ConversationHandler.END
    except SessionPasswordNeeded: await update.message.reply_text("رمز تایید دو مرحله‌ای را وارد کنید:"); return ASK_PASSWORD
    except PhoneCodeInvalid: await update.message.reply_text("کد اشتباه است. مجددا تلاش کنید."); return ASK_CODE
    except Exception as e:
        logger.error(f"Error on sign in: {e}"); await update.message.reply_text("خطا!"); await client.disconnect()
        return ConversationHandler.END

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    client = context.user_data['client']
    try:
        await client.check_password(password)
        await process_self_activation(update, context, client)
    except Exception: await update.message.reply_text("رمز عبور اشتباه است."); await client.disconnect()
    return ConversationHandler.END

async def process_self_activation(update: Update, context: ContextTypes.DEFAULT_TYPE, client: Client):
    user_id, phone = update.effective_user.id, context.user_data['phone']
    con, cur = db_connect()
    cur.execute("UPDATE users SET self_active = TRUE, phone_number = ? WHERE user_id = ?", (phone, user_id))
    con.commit(); con.close()
    user_sessions[user_id] = client
    asyncio.create_task(self_pro_background_task(user_id, client))
    await update.message.reply_text("✅ Self Pro با موفقیت فعال شد!", reply_markup=await main_menu_keyboard(user_id))

async def self_pro_background_task(user_id: int, client: Client):
    if not client.is_connected:
        try: await client.start()
        except Exception as e: logger.error(f"Could not start client for {user_id}: {e}"); return
    while user_id in user_sessions:
        user = get_user(user_id)
        if not user or not user['self_active']: break
        hourly_cost = int(get_setting("self_hourly_cost"))
        if user['balance'] < hourly_cost:
            con, cur = db_connect(); cur.execute("UPDATE users SET self_active = FALSE WHERE user_id = ?", (user_id,))
            con.commit(); con.close()
            await client.stop(); del user_sessions[user_id]
            try: await application.bot.send_message(user_id, "موجودی الماس شما تمام شد و Self Pro غیرفعال گردید.")
            except Exception as e: logger.warning(f"Could not notify user {user_id}: {e}")
            break
        update_user_balance(user_id, hourly_cost, add=False)
        try:
            me = await client.get_me()
            now = datetime.now().strftime("%H:%M")
            base_name = me.first_name.split('|')[0].strip()
            await client.update_profile(first_name=f"{base_name} | {now}")
        except Exception as e: logger.error(f"Failed to update profile for {user_id}: {e}")
        await asyncio.sleep(3600)
    logger.info(f"Background task for user {user_id} stopped.")

# --- بخش‌های دیگر ---
async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_data = get_user(query.from_user.id)
    diamond_price = int(get_setting("diamond_price"))
    toman_equivalent = user_data['balance'] * diamond_price
    
    text = (
        f"💎 **موجودی شما**\n\n"
        f"الماس: {user_data['balance']}\n"
        f"💳 معادل: {toman_equivalent:,} تومان"
    )
    await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={query.from_user.id}"
    reward = get_setting("referral_reward")
    text = (f"🔗 لینک دعوت شما:\n`{referral_link}`\n\nبا هر دعوت موفق {reward} الماس هدیه بگیرید.")
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ بازگشت", callback_data="main_menu")]]))

async def transfer_diamond_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    text = "برای انتقال الماس، روی پیام شخص مورد نظر ریپلای کرده و مقدار را به صورت عددی بنویسید."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ بازگشت", callback_data="main_menu")]]))

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message: return
    try: amount = int(update.message.text)
    except (ValueError, TypeError): return
    if amount <= 0: return
    sender, receiver = update.effective_user, update.message.reply_to_message.from_user
    if sender.id == receiver.id: await update.message.reply_text("انتقال به خود امکان‌پذیر نیست."); return
    if get_user(sender.id)['balance'] < amount: await update.message.reply_text("موجودی شما کافی نیست."); return
    
    # اطمینان از وجود کاربر گیرنده در دیتابیس
    get_user(receiver.id, receiver.username)
    
    update_user_balance(sender.id, amount, add=False)
    update_user_balance(receiver.id, amount, add=True)
    
    text = (
        f"👤 فرستنده: {get_user_handle(sender)}\n"
        f"👥 گیرنده: {get_user_handle(receiver)}\n"
        f"💵 مبلغ: {amount}\n"
        f"🧾 مالیات: ۰\n"
        f"✅ واریزی به گیرنده: {amount}"
    )
    await update.message.reply_text(text)


async def self_pro_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("منوی مدیریت Self Pro:", reply_markup=await self_pro_menu_keyboard(query.from_user.id))

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # این تابع می‌تواند برای Enemy Mode یا Offline Mode در آینده استفاده شود
    pass

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد."); return ConversationHandler.END
    
# --- منطق شرط‌بندی ---

async def end_bet(context: ContextTypes.DEFAULT_TYPE):
    """پایان دادن به شرط‌بندی، انتخاب برنده و توزیع جوایز"""
    job = context.job
    chat_id = job.chat_id
    bet_message_id = job.data['message_id']
    bet_info = job.data['bet_info']
    
    # حذف شرط از حافظه
    context.chat_data.pop('active_bet', None)

    participants_data = {
        p_id: get_user(p_id) for p_id in bet_info['participants']
    }
    
    if len(participants_data) < 2:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=bet_message_id,
            text="شرط‌بندی به دلیل عدم حضور شرکت‌کننده کافی لغو شد.",
            reply_markup=None
        )
        return

    winner_id = random.choice(list(participants_data.keys()))
    losers_data = {uid: udata for uid, udata in participants_data.items() if uid != winner_id}
    
    bet_amount = bet_info['amount']
    total_pot = bet_amount * len(participants_data)
    tax = math.ceil(total_pot * 0.05)
    prize = total_pot - tax

    # کسر مبلغ از بازندگان
    for loser_id in losers_data.keys():
        update_user_balance(loser_id, bet_amount, add=False)

    # افزودن جایزه به برنده
    update_user_balance(winner_id, prize, add=True)

    winner_info = participants_data[winner_id]
    
    losers_text_list = [f"{udata['username'] or 'کاربر'} ({uid})" for uid, udata in losers_data.items()]
    losers_text = "\n".join(losers_text_list)
    
    result_text = (
        f"<b>◈ ━━━ Self Pro ━━━ ◈</b>\n"
        f"<b>نتیجه شرط‌بندی:</b>\n\n"
        f"🏆 <b>برنده:</b> {winner_info['username'] or 'کاربر'} ({winner_id})\n"
        f"💔 <b>بازندگان:</b>\n{losers_text}\n\n"
        f"💰 <b>جایزه:</b> {prize} الماس\n"
        f"🧾 <b>مالیات:</b> {tax} الماس\n"
        f"<b>◈ ━━━ Self Pro ━━━ ◈</b>"
    )

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=bet_message_id,
        text=result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=None
    )


async def start_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع یک شرط‌بندی جدید در گروه"""
    if 'active_bet' in context.chat_data:
        await update.message.reply_text("یک شرط‌بندی دیگر در این گروه فعال است. لطفا صبر کنید.")
        return
        
    try:
        amount = int(context.args[0])
        if amount <= 0:
            await update.message.reply_text("مبلغ شرط باید بیشتر از صفر باشد.")
            return
    except (IndexError, ValueError):
        await update.message.reply_text("فرمت صحیح: /bet <مبلغ>")
        return

    creator = update.effective_user
    creator_data = get_user(creator.id, creator.username)

    if creator_data['balance'] < amount:
        await update.message.reply_text("موجودی شما برای شروع این شرط‌بندی کافی نیست.")
        return

    # ذخیره اطلاعات شرط‌بندی
    bet_info = {
        'amount': amount,
        'creator_id': creator.id,
        'participants': {creator.id} # set for unique users
    }
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"شرکت در شرط ({amount} الماس)", callback_data="join_bet")]])
    bet_message = await update.message.reply_text(
        f"🎲 شرط‌بندی جدید به مبلغ {amount} الماس توسط {get_user_handle(creator)} شروع شد!\n\n"
        f"این شرط تا 60 ثانیه دیگر بسته می‌شود.\n\n"
        f"شرکت کنندگان:\n- {get_user_handle(creator)}",
        reply_markup=keyboard
    )
    
    # زمان‌بندی برای پایان شرط
    job = context.job_queue.run_once(
        end_bet, 
        60, 
        chat_id=update.effective_chat.id, 
        name=f"bet_{update.effective_chat.id}",
        data={'message_id': bet_message.message_id, 'bet_info': bet_info}
    )
    
    context.chat_data['active_bet'] = {'job': job, 'info': bet_info, 'msg_id': bet_message.message_id}


async def join_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پیوستن یک کاربر به شرط‌بندی فعال"""
    query = update.callback_query
    user = query.from_user

    if 'active_bet' not in context.chat_data:
        await query.answer("این شرط‌بندی دیگر فعال نیست.", show_alert=True)
        return
        
    bet_info = context.chat_data['active_bet']['info']
    
    if user.id in bet_info['participants']:
        await query.answer("شما قبلا در این شرط‌بندی شرکت کرده‌اید.", show_alert=True)
        return

    user_data = get_user(user.id, user.username)
    bet_amount = bet_info['amount']

    if user_data['balance'] < bet_amount:
        await query.answer("موجودی شما برای شرکت در این شرط‌بندی کافی نیست.", show_alert=True)
        return
        
    bet_info['participants'].add(user.id)
    await query.answer("شما با موفقیت در شرط‌بندی شرکت کردید!", show_alert=False)

    # آپدیت لیست شرکت‌کنندگان در پیام اصلی
    participants_handles = [get_user_handle(await context.bot.get_chat(uid)) for uid in bet_info['participants']]
    
    text = (
        f"🎲 شرط‌بندی جدید به مبلغ {bet_amount} الماس!\n\n"
        f"این شرط تا لحظاتی دیگر بسته می‌شود.\n\n"
        f"شرکت کنندگان:\n- {'\n- '.join(participants_handles)}"
    )

    await query.edit_message_text(text, reply_markup=query.message.reply_markup)


# --- پنل ادمین ---
async def admin_panel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("شما دسترسی ندارید.", show_alert=True); return ConversationHandler.END
    await query.answer()
    await query.edit_message_text("👑 به پنل ادمین خوش آمدید:", reply_markup=await admin_panel_keyboard())
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
    await query.edit_message_text(prompt)
    return next_state

async def receive_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_value = update.message.text
    setting_key = context.user_data.pop("setting_key", None)
    if not setting_key:
        await update.message.reply_text("خطا! لطفا دوباره از پنل ادمین تلاش کنید.")
        return ADMIN_PANEL_MAIN
    update_setting(setting_key, new_value)
    await update.message.reply_text("✅ تنظیمات با موفقیت ذخیره شد.")
    # Show admin panel again
    await update.message.reply_text("👑 پنل ادمین:", reply_markup=await admin_panel_keyboard())
    return ADMIN_PANEL_MAIN

async def admin_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("منوی اصلی:", reply_markup=await main_menu_keyboard(query.from_user.id))
    return ConversationHandler.END


def main() -> None:
    global application
    setup_database()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    buy_conv = ConversationHandler(entry_points=[CallbackQueryHandler(buy_diamond_start, pattern="^buy_diamond$")],
        states={ASK_DIAMOND_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_diamond_amount)],
                AWAIT_RECEIPT: [MessageHandler(filters.PHOTO, await_receipt)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False)

    self_pro_conv = ConversationHandler(entry_points=[CallbackQueryHandler(activate_self_pro, pattern="^activate_self_pro$")],
        states={ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
                ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_code)],
                ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False)
    
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel_entry, pattern="^admin_panel$")],
        states={
            ADMIN_PANEL_MAIN: [
                CallbackQueryHandler(ask_for_setting, pattern=r"admin_set_(price|initial_balance|self_cost|referral_reward|payment_card|channel)"),
                CallbackQueryHandler(admin_exit, pattern="^main_menu$")
            ],
            SETTING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_INITIAL_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_SELF_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_REFERRAL_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_PAYMENT_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
            SETTING_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting)],
        },
        fallbacks=[CallbackQueryHandler(admin_exit, pattern="^main_menu$")], per_message=False)

    # افزودن handler ها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(buy_conv); application.add_handler(self_pro_conv); application.add_handler(admin_conv)
    
    # Handler برای شرط‌بندی
    application.add_handler(CommandHandler("bet", start_bet, filters=filters.ChatType.GROUPS))
    application.add_handler(CallbackQueryHandler(join_bet, pattern="^join_bet$"))

    # Handler های اصلی
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(check_balance, pattern="^check_balance$"))
    application.add_handler(CallbackQueryHandler(referral_menu, pattern="^referral_menu$"))
    application.add_handler(CallbackQueryHandler(transfer_diamond_info, pattern="^transfer_diamond_info$"))
    application.add_handler(CallbackQueryHandler(self_pro_menu_handler, pattern="^self_pro_menu$"))
    application.add_handler(CallbackQueryHandler(handle_transaction_approval, pattern=r"^(approve|reject)_\d+$"))
    application.add_handler(MessageHandler(filters.REPLY & filters.Regex(r'^\d+$'), handle_transfer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask); flask_thread.daemon = True; flask_thread.start()
    main()

