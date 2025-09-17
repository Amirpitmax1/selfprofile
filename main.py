# Telegram Userbot with Interactive Login and Ping Server
import asyncio
from telethon import TelegramClient, events, Button, ReplyKeyboardRemove
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.auth import SignInRequest, SignUpRequest, SendCodeRequest
from telethon.tl.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    MessageMediaContact
)
import datetime
import pytz
import logging
import json
import redis
import time
import uuid
import os
from aiohttp import web

# --- General Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
API_ID = int(os.environ.get('API_ID', 28190856))
API_HASH = os.environ.get('API_HASH', '6b9b5309c2a211b526c6ddad6eabb521')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8495719978:AAGeIZtJFRkSaYqn3LwhVMUtyxozKNAGj9g')

# Admin User ID for permanent access
ADMIN_ID = int(os.environ.get('ADMIN_ID', 7423552124))

# Redis connection for Key-Value database
# This should be your Redis server address in Render env variables
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
redis_client = redis.from_url(REDIS_URL)

# --- Clients ---
# This is the main bot client that users interact with
main_bot = TelegramClient('main_bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- User and Access Management ---
def get_user_data(user_id):
    """Retrieves user data from Redis."""
    data = redis_client.get(f'user:{user_id}')
    return json.loads(data) if data else None

def save_user_data(user_id, data):
    """Saves user data to Redis."""
    redis_client.set(f'user:{user_id}', json.dumps(data))

def is_user_active(user_id):
    """Checks if a user is active (free trial or permanent access)."""
    user_data = get_user_data(user_id)
    if not user_data:
        return False
    
    # Check for permanent access
    if user_data.get('access_type') == 'permanent':
        return True
        
    # Check for free trial validity
    end_time = user_data.get('trial_end_time')
    if end_time and time.time() < end_time:
        return True
        
    return False

def generate_invite_link(user_id):
    """Generates a unique invite link for a user."""
    user_data = get_user_data(user_id)
    if not user_data:
        # Create new user data if it doesn't exist
        user_data = {
            'invite_code': str(uuid.uuid4()),
            'trial_end_time': time.time() + 30 * 24 * 60 * 60, # 30 days trial
            'invited_count': 0
        }
        save_user_data(user_id, user_data)
    
    return f"https://t.me/YourBotUsername?start={user_data['invite_code']}"

# --- Userbot Management ---
async def start_userbot_session(user_id, phone, code_hash, code, password=None):
    """
    Starts a new userbot session for a given user.
    """
    session_name = f'sessions/user_{user_id}'
    user_client = TelegramClient(session_name, API_ID, API_HASH)
    
    try:
        await user_client.connect()
        
        # Check if already authorized
        if await user_client.is_user_authorized():
            logging.info(f"User {user_id} already logged in.")
            return True
            
        # Try to sign in with phone, code, and optional password
        if password:
            await user_client.sign_in(phone=phone, code=code, password=password)
        else:
            await user_client.sign_in(phone=phone, code=code)
            
        logging.info(f"User {user_id} logged in successfully!")
        
        # Start the clock update task in the background
        asyncio.create_task(update_profile_name(user_client, user_id))
        
        return True
    except Exception as e:
        logging.error(f"Failed to log in user {user_id}: {e}")
        return False

# --- Profile Update Logic ---
async def update_profile_name(user_client, user_id):
    """
    Updates the profile name with live clock.
    """
    try:
        user = await user_client(GetFullUserRequest('me'))
        base_name = user.full_user.first_name
        if user.full_user.last_name:
            base_name += " " + user.full_user.last_name
        
        tz = pytz.timezone('Asia/Tehran')
        
        while True:
            if not is_user_active(user_id):
                logging.info(f"User {user_id} is no longer active. Stopping clock update.")
                break
                
            now = datetime.datetime.now(tz)
            time_str = now.strftime('%H:%M')
            
            # Add different styles here (emojis, etc.)
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
async def start(event):
    chat_id = event.chat_id
    
    # Check if user is already logged in
    user_data = get_user_data(chat_id)
    if user_data and user_data.get('phone_number'):
        # If user is logged in, show the main menu
        await send_main_menu(chat_id, 'به منوی اصلی خوش آمدید.', event)
    else:
        # If not logged in, ask for phone number
        await event.reply(
            'برای فعال‌سازی ساعت، لطفاً با کلیک بر روی دکمه زیر وارد حساب خود شوید.',
            buttons=[Button.request_phone('ورود با شماره تلفن')])

@main_bot.on(events.NewMessage)
async def message_handler(event):
    chat_id = event.chat_id
    user_data = get_user_data(chat_id)
    
    if event.media and isinstance(event.media, MessageMediaContact):
        # Step 1: User shares phone number
        phone_number = event.media.phone_number
        user_data['phone_number'] = phone_number
        save_user_data(chat_id, user_data)
        
        try:
            client = TelegramClient(f'sessions/user_{chat_id}', API_ID, API_HASH)
            await client.connect()
            send_code_request = await client(SendCodeRequest(phone=phone_number))
            user_data['code_hash'] = send_code_request.phone_code_hash
            save_user_data(chat_id, user_data)
            
            await event.reply('کد تأیید به تلگرام شما ارسال شد. لطفاً آن را اینجا وارد کنید.',
                              buttons=ReplyKeyboardRemove())
        except Exception as e:
            logging.error(f"Failed to send auth code: {e}")
            await event.reply('خطا در ارسال کد تأیید. لطفاً مجدداً تلاش کنید.')
            
    elif user_data and 'code_hash' in user_data:
        # Step 2: User provides auth code
        code = event.text
        phone_number = user_data.get('phone_number')
        code_hash = user_data.get('code_hash')
        
        try:
            user_client = TelegramClient(f'sessions/user_{chat_id}', API_ID, API_HASH)
            await user_client.connect()
            
            await user_client(SignInRequest(phone=phone_number, phone_code_hash=code_hash, phone_code=code))
            
            del user_data['code_hash']
            save_user_data(chat_id, user_data)
            
            await event.reply('ورود موفقیت‌آمیز بود! ساعت پروفایل شما هر دقیقه به‌روزرسانی خواهد شد.',
                              buttons=ReplyKeyboardRemove())
            asyncio.create_task(update_profile_name(user_client, chat_id))
            
        except Exception as e:
            if 'auth.signin.PasswordRequiredError' in str(e):
                user_data['auth_flow'] = 'password'
                save_user_data(chat_id, user_data)
                await event.reply('حساب شما دارای رمز دو مرحله‌ای است. لطفاً رمز عبور خود را وارد کنید.')
            else:
                logging.error(f"Failed to sign in: {e}")
                await event.reply('کد تأیید اشتباه است. لطفاً مجدداً تلاش کنید.')
                
    elif user_data and user_data.get('auth_flow') == 'password':
        # Step 3: User provides 2FA password
        password = event.text
        phone_number = user_data.get('phone_number')
        
        try:
            user_client = TelegramClient(f'sessions/user_{chat_id}', API_ID, API_HASH)
            await user_client.connect()
            
            await user_client.sign_in(password=password, phone=phone_number)
            
            del user_data['auth_flow']
            save_user_data(chat_id, user_data)
            
            await event.reply('رمز عبور صحیح است. ساعت پروفایل شما فعال شد!',
                              buttons=ReplyKeyboardRemove())
            asyncio.create_task(update_profile_name(user_client, chat_id))
            
        except Exception as e:
            logging.error(f"Failed to sign in with password: {e}")
            await event.reply('رمز عبور اشتباه است. لطفاً دوباره تلاش کنید.')

# --- Utility Functions ---
async def send_main_menu(chat_id, text, event=None):
    # This is a placeholder for your bot's main menu
    # You can add buttons for invite link, check status, etc. here
    buttons = [
        [Button.inline('دریافت لینک دعوت', b'get_invite')],
        [Button.inline('وضعیت حساب', b'check_status')]
    ]
    if event:
        await event.reply(text, buttons=buttons)
    else:
        await main_bot.send_message(chat_id, text, buttons=buttons)

# --- Ping Server ---
async def ping_handler(request):
    """Handles incoming HTTP requests for the ping service."""
    return web.Response(text="I'm alive!")

async def run_ping_server():
    """Runs a simple HTTP server to keep the service awake."""
    app = web.Application()
    app.router.add_get('/', ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', os.environ.get('PORT', 8080))
    await site.start()
    logging.info("Ping server started successfully!")

# --- Main Bot Running ---
async def main():
    """Main function to run the bot and the ping server."""
    # Start the ping server and the bot concurrently
    await asyncio.gather(
        run_ping_server(),
        main_bot.run_until_disconnected()
    )

if __name__ == '__main__':
    asyncio.run(main())
