# -*- coding: utf-8 -*-

import asyncio
import datetime
import logging
import os
import pytz
import redis
import json
import uuid
import time # Import the time module

from telethon import TelegramClient, events, Button
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import MessageMediaContact
from telethon.sessions import StringSession

# --- Workaround for ReplyKeyboardRemove ImportError ---
# This class acts as a placeholder to prevent the bot from crashing.
class ReplyKeyboardRemove:
    def __init__(self):
        self.remove_keyboard = True
        self.selective = False

# --- General Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
API_ID = int(os.environ.get('API_ID', '28190856')) # Replace with your API_ID
API_HASH = os.environ.get('API_HASH', '6b9b5309c2a211b526c6ddad6eabb521') # Replace with your API_HASH
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8495719978:AAGeIZtJFRkSaYqn3LwhVMUtyh2KNAGj9g') # Replace with your Bot Token

# Admin User ID
ADMIN_ID = int(os.environ.get('ADMIN_ID', '7423552124')) # Replace with your Admin ID

# Redis connection for Key-Value database
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# --- Clients ---
# This is the main bot client that users interact with
main_bot = TelegramClient('main_bot_session', API_ID, API_HASH)

# --- User and Access Management with Redis ---
def get_user_data(user_id):
    """Retrieves user data from Redis."""
    data = redis_client.get(f'user_data:{user_id}')
    return json.loads(data) if data else {}

def save_user_data(user_id, data):
    """Saves user data to Redis."""
    redis_client.set(f'user_data:{user_id}', json.dumps(data))

def is_user_logged_in(user_id):
    """Checks if a user is logged in to their userbot session."""
    return redis_client.exists(f'session:{user_id}')

def is_user_active(user_id):
    """Checks if a user is active (free trial or permanent access)."""
    user_data = get_user_data(user_id)
    if not user_data:
        return False
        
    if user_data.get('is_permanent', False):
        return True
    
    trial_end_time = user_data.get('trial_end_time')
    if trial_end_time and time.time() < trial_end_time:
        return True
        
    return False

# --- Userbot Management ---
async def start_userbot_session(user_id, phone, code, password=None):
    """
    Starts a new userbot session for a given user.
    """
    session_string = redis_client.get(f'session:{user_id}')
    if session_string:
        user_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    else:
        user_client = TelegramClient(StringSession(), API_ID, API_HASH)

    try:
        await user_client.connect()
        if not await user_client.is_user_authorized():
            # Check for 2FA password
            if password:
                await user_client.sign_in(phone=phone, code=code, password=password)
            else:
                await user_client.sign_in(phone=phone, code=code)
        
        logging.info(f"User {user_id} logged in successfully!")
        
        # Save the new session string
        redis_client.set(f'session:{user_id}', user_client.session.save())

        # Start the clock update task in the background
        asyncio.create_task(update_profile_name(user_client, user_id))
        
        return True, "ورود موفقیت‌آمیز بود! ساعت پروفایل شما هر دقیقه به‌روزرسانی خواهد شد."
    except FloodWaitError as e:
        logging.error(f"Flood wait for user {user_id}: {e.seconds} seconds.")
        return False, f"تلگرام به دلیل تلاش‌های زیاد، شما را برای {e.seconds} ثانیه محدود کرده است."
    except SessionPasswordNeededError:
        logging.warning(f"User {user_id} requires 2FA password.")
        return False, "two_factor"
    except Exception as e:
        logging.error(f"Failed to log in user {user_id}: {e}")
        return False, "خطا در ورود. لطفاً اطلاعات را بررسی کنید."

# --- Profile Update Logic ---
async def update_profile_name(user_client, user_id):
    """
    Updates the profile name with a live clock.
    """
    try:
        user = await user_client(GetFullUserRequest('me'))
        base_name = user.full_user.first_name
        
        tz = pytz.timezone('Asia/Tehran')
        
        while True:
            # Check if the user is still active
            if not is_user_active(user_id):
                logging.info(f"User {user_id} is no longer active. Stopping clock update.")
                break
                
            now = datetime.datetime.now(tz)
            time_str = now.strftime('%H:%M')
            
            new_name = f"{base_name} | {time_str}"
            
            try:
                await user_client(UpdateProfileRequest(first_name=new_name))
                logging.info(f"Updated profile name for {user_id} to {new_name}")
            except Exception as e:
                logging.warning(f"Failed to update profile for {user_id}: {e}")
                
            await asyncio.sleep(60)
            
    except Exception as e:
        logging.error(f"Error in profile update loop for {user_id}: {e}")

# --- Bot Event Handlers ---
@main_bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    chat_id = event.chat_id
    
    if is_user_logged_in(chat_id):
        await send_main_menu(chat_id, 'به منوی اصلی خوش آمدید.', event)
    else:
        await event.reply(
            'برای فعال‌سازی ساعت، لطفاً با کلیک بر روی دکمه زیر وارد حساب خود شوید.',
            buttons=[Button.request_phone('ورود با شماره تلفن')]
        )

@main_bot.on(events.NewMessage(func=lambda e: isinstance(e.media, MessageMediaContact)))
async def contact_handler(event):
    chat_id = event.chat_id
    phone_number = event.media.phone_number
    
    # Save phone number to Redis to be used later
    user_data = get_user_data(chat_id)
    user_data['phone_number'] = phone_number
    save_user_data(chat_id, user_data)
    
    try:
        user_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await user_client.connect()
        send_code_request = await user_client.send_code_request(phone_number)
        user_data['phone_code_hash'] = send_code_request.phone_code_hash
        save_user_data(chat_id, user_data)
        
        await event.reply('کد تأیید به تلگرام شما ارسال شد. لطفاً آن را اینجا وارد کنید.', buttons=ReplyKeyboardRemove())
    except Exception as e:
        logging.error(f"Failed to send auth code: {e}")
        await event.reply('خطا در ارسال کد تأیید. لطفاً مجدداً تلاش کنید.')

@main_bot.on(events.NewMessage)
async def message_handler(event):
    chat_id = event.chat_id
    text = event.raw_text
    user_data = get_user_data(chat_id)
    
    if 'phone_code_hash' in user_data:
        # User provides auth code
        code = text
        phone_number = user_data.get('phone_number')
        code_hash = user_data.get('phone_code_hash')
        
        success, message = await start_userbot_session(chat_id, phone_number, code)
        
        if success:
            del user_data['phone_code_hash']
            save_user_data(chat_id, user_data)
            await event.reply(message, buttons=ReplyKeyboardRemove())
            await send_main_menu(chat_id, 'به منوی اصلی خوش آمدید.', event)
        else:
            if message == "two_factor":
                user_data['auth_flow'] = 'password'
                del user_data['phone_code_hash']
                save_user_data(chat_id, user_data)
                await event.reply('حساب شما دارای رمز دو مرحله‌ای است. لطفاً رمز عبور خود را وارد کنید.')
            else:
                await event.reply(message)
    
    elif user_data.get('auth_flow') == 'password':
        # User provides 2FA password
        password = text
        phone_number = user_data.get('phone_number')
        
        success, message = await start_userbot_session(chat_id, phone_number, None, password)
        
        if success:
            del user_data['auth_flow']
            save_user_data(chat_id, user_data)
            await event.reply(message, buttons=ReplyKeyboardRemove())
            await send_main_menu(chat_id, 'به منوی اصلی خوش آمدید.', event)
        else:
            await event.reply(message)

# --- Utility Functions ---
async def send_main_menu(chat_id, text, event=None):
    buttons = [
        [Button.inline('دریافت لینک دعوت', b'get_invite')],
        [Button.inline('وضعیت حساب', b'check_status')],
        [Button.inline('توقف ساعت', b'stop_clock')]
    ]
    if event:
        await event.reply(text, buttons=buttons)
    else:
        await main_bot.send_message(chat_id, text, buttons=buttons)

@main_bot.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode('utf-8')
    chat_id = event.chat_id
    
    if data == 'get_invite':
        invite_code = str(uuid.uuid4())
        user_data = get_user_data(chat_id)
        user_data['invite_code'] = invite_code
        save_user_data(chat_id, user_data)
        
        invite_link = f"https://t.me/YourBotUsername?start={invite_code}"
        await event.edit(f'این لینک دعوت اختصاصی شماست:\n`{invite_link}`',
                         buttons=[Button.inline('بازگشت', b'main_menu')])
    
    elif data == 'check_status':
        user_data = get_user_data(chat_id)
        status_text = "حساب شما فعال است." if is_user_active(chat_id) else "حساب شما غیرفعال است."
        if user_data.get('is_permanent'):
            status_text = "دسترسی شما دائمی است."
        else:
            end_time = user_data.get('trial_end_time')
            if end_time:
                remaining_time = end_time - time.time()
                days = int(remaining_time // (24 * 3600))
                hours = int((remaining_time % (24 * 3600)) // 3600)
                status_text += f"\nزمان باقی‌مانده: {days} روز و {hours} ساعت"
        
        await event.edit(f'وضعیت حساب شما:\n{status_text}',
                         buttons=[Button.inline('بازگشت', b'main_menu')])
    
    elif data == 'stop_clock':
        user_data = get_user_data(chat_id)
        user_data['is_permanent'] = False # This is a simple way to stop the loop
        user_data['trial_end_time'] = time.time() # This will immediately stop the clock
        save_user_data(chat_id, user_data)
        await event.edit("ساعت پروفایل شما متوقف شد.", buttons=[Button.inline('بازگشت', b'main_menu')])

    elif data == 'main_menu':
        await event.edit('به منوی اصلی خوش آمدید.', buttons=[
            [Button.inline('دریافت لینک دعوت', b'get_invite')],
            [Button.inline('وضعیت حساب', b'check_status')],
            [Button.inline('توقف ساعت', b'stop_clock')]
        ])

# --- Main function to run the bot ---
async def main():
    # A check to ensure the user has updated the BOT_TOKEN
    if BOT_TOKEN == '8495719978:AAGeIZtJFRkSaYqn3LwhVMUtyh2KNAGj9g':
        logging.error("BOT_TOKEN is the default placeholder. Please replace it with your actual bot token.")
        # We exit here so Render doesn't loop forever trying to start with an invalid token
        return

    await main_bot.start(bot_token=BOT_TOKEN)
    logging.info("Main bot started successfully!")
    await main_bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
