# -*- coding: utf-8 -*-

import os
import sqlite3
import logging
import asyncio
from threading import Thread
from datetime import datetime, timedelta
import random

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
# توجه: برای استفاده از Pyrogram، باید Tgcrypto هم نصب باشد
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
# این بخش یک وب سرور ساده راه‌اندازی می‌کند تا Render سرویس را خاموش نکند
web_app = Flask(__name__)

@web_app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    web_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# --- تنظیمات اولیه و متغیرها ---
# این مقادیر باید در بخش Environment Variables در Render تنظیم شوند
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "7998966950:AAGEaASYQ8S16ADyl0x5-ucSe2oWPpJHMbg")
API_ID = int(os.environ.get("API_ID", "9536480"))
API_HASH = os.environ.get("API_HASH", "4e52f6f12c47a0da918009260b6e3d44")
OWNER_ID = int(os.environ.get("OWNER_ID", "7423552124")) # ادمین اصلی

# مسیر دیتابیس در دیسک پایدار Render
DB_PATH = os.path.join(os.environ.get("RENDER_DISK_PATH", "."), "bot_database.db")
SESSION_PATH = os.environ.get("RENDER_DISK_PATH", ".")

# مراحل ConversationHandler برای فرآیندهای چندمرحله‌ای
(
    ASK_DIAMOND_AMOUNT,
    AWAIT_RECEIPT,
    ADMIN_CONTROLS,
    SETTING_PRICE,
    SETTING_INITIAL_BALANCE,
    SETTING_SELF_COST,
    SETTING_CHANNEL_LINK,
    ASK_PHONE,
    ASK_CODE,
    ASK_PASSWORD,
    TRANSFER_AMOUNT
) = range(11)

# --- مدیریت دیتابیس (SQLite) ---
def db_connect():
    """اتصال به دیتابیس و برگرداندن کانکشن و کرسر"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con, con.cursor()

def setup_database():
    """ایجاد جداول اولیه در دیتابیس در صورتی که وجود نداشته باشند"""
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount_diamonds INTEGER,
            amount_toman INTEGER,
            receipt_file_id TEXT,
            status TEXT DEFAULT 'pending', -- pending, approved, rejected
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_by INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER,
            reward_granted BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (referrer_id, referred_id)
        )
    """)

    # تنظیمات پیش‌فرض
    default_settings = {
        "diamond_price": "500",  # قیمت هر الماس به تومان
        "initial_balance": "10", # موجودی اولیه
        "self_hourly_cost": "5",   # هزینه ساعتی سلف
        "referral_reward": "20", # پاداش دعوت
        "payment_card": "6037-xxxx-xxxx-xxxx",
        "mandatory_channel": "@YourChannel"
    }
    for key, value in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    # افزودن ادمین اصلی
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

def get_user(user_id):
    con, cur = db_connect()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        # ایجاد کاربر جدید
        initial_balance = int(get_setting("initial_balance"))
        cur.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, initial_balance))
        con.commit()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
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

# --- کیبوردهای ربات ---

async def main_menu_keyboard(user_id):
    """ساخت کیبورد منوی اصلی"""
    user = get_user(user_id)
    self_status = "✅ فعال" if user['self_active'] else "❌ غیرفعال"
    
    keyboard = [
        [InlineKeyboardButton(f"💎 موجودی: {user['balance']} الماس", callback_data="check_balance")],
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
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin_stats")],
        [InlineKeyboardButton("💎 تنظیم قیمت الماس", callback_data="admin_set_price")],
        [InlineKeyboardButton("💰 تنظیم موجودی اولیه", callback_data="admin_set_initial_balance")],
        [InlineKeyboardButton("🚀 تنظیم هزینه سلف", callback_data="admin_set_self_cost")],
        [InlineKeyboardButton("📢 تنظیم کانال اجباری", callback_data="admin_set_channel")],
        [InlineKeyboardButton("💳 مشاهده تراکنش‌های در انتظار", callback_data="admin_pending_transactions")],
        [InlineKeyboardButton("↩️ بازگشت به منوی اصلی", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)
    
async def self_pro_menu_keyboard(user_id):
    user = get_user(user_id)
    keyboard = []
    if not user['self_active']:
        keyboard.append([InlineKeyboardButton("🚀 فعال‌سازی Self Pro", callback_data="activate_self_pro")])
    else:
        keyboard.append([InlineKeyboardButton("✏️ تغییر فونت", callback_data="change_font")])
        keyboard.append([InlineKeyboardButton("❌ غیرفعال‌سازی موقت", callback_data="deactivate_self_pro")])
        keyboard.append([InlineKeyboardButton("🗑 حذف کامل سلف", callback_data="delete_self_pro")])

    keyboard.append([InlineKeyboardButton("↩️ بازگشت", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


# --- دستورات اصلی و شروع ربات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /start"""
    user = update.effective_user
    user_data = get_user(user.id) # این تابع کاربر را در صورت عدم وجود ایجاد می‌کند
    
    # بررسی دعوت
    if context.args and len(context.args) > 0:
        referrer_id = int(context.args[0])
        if referrer_id != user.id:
            # اینجا منطق بررسی عضویت در کانال و اعطای جایزه پیاده‌سازی شود
            logger.info(f"User {user.id} was referred by {referrer_id}")
            # ...
    
    await update.message.reply_text(
        f"سلام {user.first_name}!\nبه ربات Self Pro خوش آمدید.",
        reply_markup=await main_menu_keyboard(user.id),
    )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی اصلی (معمولا بعد از بازگشت از منوهای دیگر)"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "منوی اصلی:",
        reply_markup=await main_menu_keyboard(query.from_user.id)
    )

# --- منطق خرید الماس ---

async def buy_diamond_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند خرید الماس"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تعداد الماسی که قصد خرید دارید را وارد کنید:")
    return ASK_DIAMOND_AMOUNT

async def ask_diamond_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد الماس و ساخت پیش‌فاکتور"""
    try:
        amount = int(update.message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("لطفا یک عدد صحیح و مثبت وارد کنید.")
        return ASK_DIAMOND_AMOUNT

    diamond_price = int(get_setting("diamond_price"))
    total_cost = amount * diamond_price
    payment_card = get_setting("payment_card")
    
    context.user_data['purchase_amount'] = amount
    context.user_data['purchase_cost'] = total_cost

    text = (
        f"🧾 **پیش‌فاکتور خرید**\n\n"
        f"💎 تعداد الماس: {amount}\n"
        f"💳 مبلغ قابل پرداخت: {total_cost:,} تومان\n\n"
        f"لطفاً مبلغ را به شماره کارت زیر واریز کرده و سپس عکس رسید را ارسال کنید:\n"
        f"`{payment_card}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return AWAIT_RECEIPT

async def await_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت رسید و ارسال برای ادمین‌ها"""
    if not update.message.photo:
        await update.message.reply_text("لطفا فقط عکس رسید را ارسال کنید.")
        return AWAIT_RECEIPT

    user = update.effective_user
    receipt_file_id = update.message.photo[-1].file_id
    amount = context.user_data['purchase_amount']
    cost = context.user_data['purchase_cost']

    # ذخیره تراکنش در دیتابیس
    con, cur = db_connect()
    cur.execute(
        "INSERT INTO transactions (user_id, amount_diamonds, amount_toman, receipt_file_id) VALUES (?, ?, ?, ?)",
        (user.id, amount, cost, receipt_file_id)
    )
    transaction_id = cur.lastrowid
    con.commit()
    con.close()
    
    await update.message.reply_text("رسید شما دریافت شد و برای ادمین‌ها ارسال گردید. لطفا تا زمان تایید صبور باشید.")

    # ارسال برای ادمین‌ها
    caption = (
        f" رسید جدید برای تایید\n\n"
        f"کاربر: @{user.username} ({user.id})\n"
        f"تعداد الماس: {amount}\n"
        f"مبلغ: {cost:,} تومان"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"approve_{transaction_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{transaction_id}")
        ]
    ])

    for admin_id in get_admins():
        try:
            await context.bot.send_photo(chat_id=admin_id, photo=receipt_file_id, caption=caption, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Failed to send receipt to admin {admin_id}: {e}")

    return ConversationHandler.END
    
async def handle_transaction_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت تایید یا رد تراکنش توسط ادمین"""
    query = update.callback_query
    await query.answer()
    
    action, transaction_id = query.data.split("_")
    transaction_id = int(transaction_id)
    admin_id = query.from_user.id
    
    con, cur = db_connect()
    cur.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,))
    tx = cur.fetchone()
    
    if not tx:
        await query.edit_message_caption(caption="این تراکنش یافت نشد.", reply_markup=None)
        con.close()
        return
        
    if tx['status'] != 'pending':
        await query.edit_message_caption(caption=f"این تراکنش قبلا توسط ادمین دیگری به وضعیت «{tx['status']}» تغییر یافته است.", reply_markup=None)
        con.close()
        return

    user_id = tx['user_id']
    amount = tx['amount_diamonds']

    if action == "approve":
        update_user_balance(user_id, amount, add=True)
        cur.execute("UPDATE transactions SET status = 'approved', approved_by = ? WHERE id = ?", (admin_id, transaction_id))
        con.commit()
        await query.edit_message_caption(caption=f"تراکنش تایید شد.\n {amount} الماس به کاربر اضافه شد.", reply_markup=None)
        try:
            await context.bot.send_message(user_id, f"خرید شما به تعداد {amount} الماس با موفقیت تایید شد.")
        except Exception as e:
            logger.warning(f"Could not notify user {user_id} about approved transaction: {e}")
    
    elif action == "reject":
        cur.execute("UPDATE transactions SET status = 'rejected', approved_by = ? WHERE id = ?", (admin_id, transaction_id))
        con.commit()
        await query.edit_message_caption(caption="تراکنش رد شد.", reply_markup=None)
        try:
            await context.bot.send_message(user_id, f"متاسفانه خرید شما رد شد. برای اطلاعات بیشتر با پشتیبانی تماس بگیرید.")
        except Exception as e:
            logger.warning(f"Could not notify user {user_id} about rejected transaction: {e}")
            
    con.close()


# --- منطق Self Pro ---

user_sessions = {} # برای نگهداری کلاینت‌های Pyrogram

async def activate_self_pro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    cost = int(get_setting("self_hourly_cost")) # اینجا هزینه فعالسازی اولیه را میتوانید جداگانه تعریف کنید

    if user['balance'] < cost * 24: # حداقل برای یک روز
        await query.edit_message_text("موجودی شما برای فعال‌سازی سلف کافی نیست. حداقل باید به اندازه یک روز هزینه، الماس داشته باشید.")
        return ConversationHandler.END
    
    await query.edit_message_text(
        "برای فعال‌سازی سلف، لطفا شماره تلفن خود را با فرمت +989123456789 ارسال کنید."
    )
    return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    user_id = update.effective_user.id
    
    context.user_data['phone'] = phone
    
    # ایجاد کلاینت Pyrogram
    client = Client(f"user_{user_id}", api_id=API_ID, api_hash=API_HASH, workdir=SESSION_PATH)
    
    try:
        await client.connect()
        sent_code = await client.send_code(phone)
        context.user_data['phone_code_hash'] = sent_code.phone_code_hash
        context.user_data['client'] = client
        
        await update.message.reply_text("کد تایید ارسال شده به تلگرام شما را وارد کنید:")
        return ASK_CODE
    except (PhoneNumberInvalid, Exception) as e:
        logger.error(f"Error sending code for {phone}: {e}")
        await update.message.reply_text("شماره تلفن نامعتبر است. لطفا دوباره تلاش کنید.")
        return ASK_PHONE

async def ask_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    phone = context.user_data['phone']
    phone_code_hash = context.user_data['phone_code_hash']
    client = context.user_data['client']
    
    try:
        await client.sign_in(phone, phone_code_hash, code)
        await process_self_activation(update, context, client)
        return ConversationHandler.END

    except SessionPasswordNeeded:
        await update.message.reply_text("حساب شما دارای تایید دو مرحله‌ای است. لطفا رمز خود را وارد کنید:")
        return ASK_PASSWORD
    except (PhoneCodeInvalid, Exception) as e:
        logger.error(f"Error on sign in with code: {e}")
        await update.message.reply_text("کد وارد شده اشتباه است. لطفا مجددا تلاش کنید.")
        await client.disconnect()
        return ConversationHandler.END

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    client = context.user_data['client']
    
    try:
        await client.check_password(password)
        await process_self_activation(update, context, client)
    except (PasswordHashInvalid, Exception) as e:
        logger.error(f"Error on 2FA check: {e}")
        await update.message.reply_text("رمز عبور اشتباه است. فرآیند لغو شد.")
        await client.disconnect()
    
    return ConversationHandler.END

async def process_self_activation(update: Update, context: ContextTypes.DEFAULT_TYPE, client: Client):
    user_id = update.effective_user.id
    phone = context.user_data['phone']
    
    # ذخیره اطلاعات و فعال‌سازی
    con, cur = db_connect()
    cur.execute("UPDATE users SET self_active = TRUE, phone_number = ? WHERE user_id = ?", (phone, user_id))
    con.commit()
    con.close()
    
    user_sessions[user_id] = client
    # شروع تسک پس‌زمینه برای کسر هزینه و آپدیت پروفایل
    asyncio.create_task(self_pro_background_task(user_id, client))
    
    await update.message.reply_text(
        "✅ Self Pro با موفقیت فعال شد!",
        reply_markup=await main_menu_keyboard(user_id)
    )

async def self_pro_background_task(user_id: int, client: Client):
    """تسک پس‌زمینه برای کسر هزینه و آپدیت پروفایل"""
    while user_id in user_sessions:
        user = get_user(user_id)
        if not user or not user['self_active']:
            break # توقف تسک

        hourly_cost = int(get_setting("self_hourly_cost"))
        
        if user['balance'] < hourly_cost:
            # موجودی تمام شد، سلف را خاموش کن
            logger.info(f"User {user_id} ran out of balance. Deactivating Self Pro.")
            con, cur = db_connect()
            cur.execute("UPDATE users SET self_active = FALSE WHERE user_id = ?", (user_id,))
            con.commit()
            con.close()
            
            await client.disconnect()
            del user_sessions[user_id]
            try:
                await application.bot.send_message(user_id, "موجودی الماس شما تمام شد و Self Pro غیرفعال گردید.")
            except Exception as e:
                logger.warning(f"Could not notify user {user_id} about self deactivation: {e}")
            break

        # کسر هزینه
        update_user_balance(user_id, hourly_cost, add=False)
        
        # آپدیت نام پروفایل با زمان
        try:
            me = await client.get_me()
            # این بخش را میتوانید برای حذف زمان قبلی از نام، بهینه کنید
            now = datetime.now().strftime("%H:%M")
            await client.update_profile(first_name=f"{me.first_name} | {now}")
        except Exception as e:
            logger.error(f"Failed to update profile for {user_id}: {e}")

        # انتظار برای ساعت بعد
        await asyncio.sleep(3600) # 1 hour
    logger.info(f"Background task for user {user_id} stopped.")

# --- بخش‌های دیگر ---

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    diamond_price = int(get_setting("diamond_price"))
    toman_equivalent = user['balance'] * diamond_price
    
    await query.edit_message_text(
        f"💎 موجودی شما: {user['balance']} الماس\n"
        f"💳 معادل: {toman_equivalent:,} تومان",
        reply_markup=await main_menu_keyboard(query.from_user.id)
    )

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    reward = get_setting("referral_reward")
    
    text = (
        "🔗 لینک دعوت اختصاصی شما:\n"
        f"`{referral_link}`\n\n"
        f"با هر نفری که از طریق این لینک وارد ربات شود و در کانال اجباری عضو بماند، شما {reward} الماس هدیه می‌گیرید."
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ بازگشت", callback_data="main_menu")]])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def transfer_diamond_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "برای انتقال الماس، روی پیام شخص مورد نظر در هر چتی ریپلای کرده و مقدار الماس را به صورت عددی بنویسید.\n\n"
        "مثال: روی پیام یک کاربر ریپلای کنید و بنویسید `50`"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ بازگشت", callback_data="main_menu")]])
    await query.edit_message_text(text, reply_markup=keyboard)

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت انتقال الماس با ریپلای"""
    if not update.message.reply_to_message:
        return

    try:
        amount = int(update.message.text)
        if amount <= 0: return
    except (ValueError, TypeError):
        return

    sender = update.effective_user
    receiver = update.message.reply_to_message.from_user

    if sender.id == receiver.id:
        await update.message.reply_text("شما نمی‌توانید به خودتان الماس منتقل کنید.")
        return

    sender_data = get_user(sender.id)

    if sender_data['balance'] < amount:
        await update.message.reply_text("موجودی شما برای این انتقال کافی نیست.")
        return
        
    # انجام تراکنش
    update_user_balance(sender.id, amount, add=False)
    update_user_balance(receiver.id, amount, add=True)

    # نمایش رسید
    text = (
        f"✅ انتقال با موفقیت انجام شد!\n\n"
        f"👤 فرستنده: {sender.mention_markdown_v2()}\n"
        f"👥 گیرنده: {receiver.mention_markdown_v2()}\n"
        f"💵 مبلغ: {amount} الماس"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def betting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منطق شرط‌بندی"""
    # این بخش نیاز به پیاده‌سازی کامل‌تری دارد
    # برای مثال، نگهداری وضعیت شرط‌بندی در context.chat_data
    # و مدیریت شرکت‌کنندگان
    await update.message.reply_text("ویژگی شرط‌بندی در حال ساخت است!")
    
async def self_pro_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "منوی مدیریت Self Pro:",
        reply_markup=await self_pro_menu_keyboard(query.from_user.id)
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """لغو کردن و پایان مکالمه"""
    await update.message.reply_text("عملیات لغو شد.")
    return ConversationHandler.END


# --- پنل ادمین ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("شما دسترسی به این بخش را ندارید.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text("👑 به پنل ادمین خوش آمدید:", reply_markup=await admin_panel_keyboard())

# ... سایر توابع پنل ادمین اینجا پیاده‌سازی شوند ...
# (تنظیم قیمت، مشاهده آمار و ...)


def main() -> None:
    """شروع به کار ربات"""
    global application
    
    # راه‌اندازی دیتابیس
    setup_database()
    
    # ساخت اپلیکیشن ربات
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Conversation handler برای خرید الماس
    buy_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(buy_diamond_start, pattern="^buy_diamond$")],
        states={
            ASK_DIAMOND_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_diamond_amount)],
            AWAIT_RECEIPT: [MessageHandler(filters.PHOTO, await_receipt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Conversation handler برای فعالسازی سلف
    self_pro_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(activate_self_pro, pattern="^activate_self_pro$")],
        states={
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_code)],
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # افزودن handler ها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(buy_conv_handler)
    application.add_handler(self_pro_conv_handler)
    
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(check_balance, pattern="^check_balance$"))
    application.add_handler(CallbackQueryHandler(referral_menu, pattern="^referral_menu$"))
    application.add_handler(CallbackQueryHandler(transfer_diamond_info, pattern="^transfer_diamond_info$"))
    application.add_handler(CallbackQueryHandler(self_pro_menu_handler, pattern="^self_pro_menu$"))
    application.t
    
    # هندلرهای ادمین
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(handle_transaction_approval, pattern=r"^(approve|reject)_\d+$"))

    # هندلر انتقال با ریپلای
    application.add_handler(MessageHandler(filters.REPLY & filters.Regex(r'^\d+$'), handle_transfer))
    
    # هندلر شرط‌بندی (مثال)
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.Regex(r'^bet \d+$'), betting_handler))

    # اجرای ربات
    logger.info("Bot is starting...")
    application.run_polling()


if __name__ == "__main__":
    # اجرای وب سرور در یک ترد جداگانه
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    main()

