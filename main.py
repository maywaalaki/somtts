import os
import asyncio
import time
import threading
from flask import Flask, request, abort
import telebot
import edge_tts
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardMarkup, InlineKeyboardButton
import requests
from pymongo import MongoClient
import logging

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8508232988:AAETkYzPTnevP3hylhX-I_v0UDrK0h1wD9k")
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE", "https://somtts.onrender.com")
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook/")
WEBHOOK_URL = WEBHOOK_URL_BASE.rstrip('/') + WEBHOOK_PATH if WEBHOOK_URL_BASE else ""
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "./downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
PIN_SOURCE = os.environ.get("PIN_SOURCE", "-1003516493646")

GROQ_KEYS = os.environ.get("GROQ_KEYS", "")
GROQ_TEXT_MODEL = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")

MONGO_URI = "mongodb+srv://lakiup3_db_user:V4Nbt6YcqH0qCBix@cluster0.my3ety2.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client['somtts_bot']
users_col = db['users']

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

ADMIN_ID = 6964068910
BAN_MESSAGE = "🚫Waa luu xanibay sababo la xariira spam la xariir lakiup3@gmail.com"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_user_data(user_id):
    user = users_col.find_one({"user_id": str(user_id)})
    if not user:
        user = {
            "user_id": str(user_id),
            "voice": {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"},
            "rate": 0,
            "pitch": 0,
            "banned": False
        }
        users_col.insert_one(user)
    return user

def update_user_data(user_id, updates):
    users_col.update_one({"user_id": str(user_id)}, {"$set": updates}, upsert=True)

def is_banned(user_id):
    user = users_col.find_one({"user_id": str(user_id)})
    if user and user.get("banned", False):
        return True
    return False

class KeyRotator:
    def __init__(self, keys_str):
        self.keys = [k.strip() for k in keys_str.split(",") if k.strip()] if isinstance(keys_str, str) else list(keys_str or [])
        self.index = 0
        self.lock = threading.Lock()

    def get_key(self):
        with self.lock:
            if not self.keys:
                return None
            key = self.keys[self.index]
            self.index = (self.index + 1) % len(self.keys)
            return key

    def mark_success(self, key):
        with self.lock:
            try:
                i = self.keys.index(key)
                self.index = (i + 1) % len(self.keys)
            except ValueError:
                pass

    def mark_failure(self, key):
        self.mark_success(key)

key_manager = KeyRotator(GROQ_KEYS)

def process_text_with_groq(text):
    instruction = """You are a text normalization assistant specialized ONLY in numbers and money.
YOUR ONLY TASK IS:
1. If the text contains numbers or money symbols ($, USD, 0.5, 100, 2024, etc.), convert ONLY those parts into natural Somali words that are easy to read aloud.
   Examples:
   - 100 -> boqol
   - 25 -> labaatan iyo shan
   - $10 -> toban doolar
   - 0.5$ -> nus doolar
   - 2026 -> laba kun labaatan iyo lix
2. DO NOT change anything else:
   - Do NOT translate words
   - Do NOT fix grammar
   - Do NOT correct spelling
   - Do NOT rephrase sentences
   - Do NOT change punctuation
   - Do NOT change formatting
3. If the text does NOT contain any numbers or money:
   → Return the text EXACTLY as it is, without changing even a single character.
4. Your output must contain ONLY the final processed text. Do NOT add explanations.
IMPORTANT:
If there are no numbers or money in the input, the output MUST be a 100% identical copy of the input"""
    if not key_manager.keys:
        return text
    last_exc = None
    total = len(key_manager.keys) or 1
    for _ in range(total + 1):
        api_key = key_manager.get_key()
        if not api_key:
            return text
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": GROQ_TEXT_MODEL,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.2
            }
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                try:
                    content = response.json()
                    return content['choices'][0]['message']['content'].strip()
                except Exception as e:
                    last_exc = e
                    key_manager.mark_failure(api_key)
                    continue
            else:
                key_manager.mark_failure(api_key)
        except Exception as e:
            last_exc = e
            key_manager.mark_failure(api_key)
            continue
    return text

def generate_tts_filename(user_id):
    safe_id = str(user_id).replace(" ", "_")
    return os.path.join(DOWNLOADS_DIR, f"Codka_{safe_id}_{int(time.time()*1000)}.mp3")

def create_voice_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    keyboard.add(KeyboardButton("Ubax 👩🏻‍🦳"), KeyboardButton("Muuse 👨🏻‍🦱"))
    return keyboard

def rate_keyboard(current):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➖", callback_data="rate_down"), InlineKeyboardButton(f"Rate: {current}", callback_data="rate_noop"), InlineKeyboardButton("➕", callback_data="rate_up"))
    return kb

def pitch_keyboard(current):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➖", callback_data="pitch_down"), InlineKeyboardButton(f"Pitch: {current}", callback_data="pitch_noop"), InlineKeyboardButton("➕", callback_data="pitch_up"))
    return kb

def keep_sending_upload_action(chat_id, stop_event, interval=3):
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, "upload_audio")
        except Exception:
            pass
        time.sleep(interval)

def forward_pinned_to_user(dest_chat_id, pin_source):
    if not pin_source:
        return False
    try:
        me = bot.get_me()
        member = bot.get_chat_member(pin_source, me.id)
        status = getattr(member, "status", "")
        if status not in ("administrator", "creator"):
            return False
        chat_info = bot.get_chat(pin_source)
        pinned = getattr(chat_info, "pinned_message", None)
        if pinned and getattr(pinned, "message_id", None):
            bot.forward_message(dest_chat_id, pin_source, pinned.message_id)
            return True
    except Exception:
        return False
    return False

@bot.message_handler(commands=["ban"])
def ban_user(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Fadlan qor ID-ga userka. Tusaale: /ban 12345678")
            return
        target_id = args[1]
        users_col.update_one({"user_id": str(target_id)}, {"$set": {"banned": True}}, upsert=True)
        bot.reply_to(message, f"✅ User {target_id} waa la mamnuucay (Banned).")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=["unban"])
def unban_user(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Fadlan qor ID-ga userka. Tusaale: /unban 12345678")
            return
        target_id = args[1]
        users_col.update_one({"user_id": str(target_id)}, {"$set": {"banned": False}}, upsert=True)
        bot.reply_to(message, f"✅ User {target_id} xayiraada waa laga qaaday (Unbanned).")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=["start"])
def start(message):
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, BAN_MESSAGE)
        return
    get_user_data(message.from_user.id)
    keyboard = create_voice_keyboard()
    bot.send_message(
        message.chat.id,
        "Soo dhawow! Waxaan ahay Somali Text to Speech bot waxaa i samee yay zack3d:\n\nii soo dir qoraal si aan ugu badalo cod💗",
        reply_markup=keyboard,
        reply_to_message_id=message.message_id
    )

@bot.message_handler(func=lambda m: m.text in ["Ubax 👩🏻‍🦳", "Muuse 👨🏻‍🦱"])
def set_voice(message):
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, BAN_MESSAGE)
        return
    user_id = message.from_user.id
    choice = message.text
    if "Ubax" in choice:
        voice_data = {"name": "so-SO-UbaxNeural", "label": "Ubax 👩🏻‍🦳"}
    else:
        voice_data = {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"}
    update_user_data(user_id, {"voice": voice_data})
    bot.send_message(
        message.chat.id,
        f"Ok hada Codka waa: {choice}\n\n ii soo dir qoraalka 👍",
        reply_to_message_id=message.message_id
    )

@bot.message_handler(commands=['rate'])
def cmd_rate(message):
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, BAN_MESSAGE)
        return
    user = get_user_data(message.from_user.id)
    current = user.get("rate", 0)
    bot.send_message(message.chat.id, "si aad uhagaaji so xawaaraha taabo calaamada ➕ ta ama ➖:", reply_markup=rate_keyboard(current))

@bot.message_handler(commands=['pitch'])
def cmd_pitch(message):
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, BAN_MESSAGE)
        return
    user = get_user_data(message.from_user.id)
    current = user.get("pitch", 0)
    bot.send_message(message.chat.id, "si aad u hagaaji sid dhawaaqa taabo calaamada ➕ ta ama ➖ ta :", reply_markup=pitch_keyboard(current))

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith(("rate_", "pitch_")))
def slider_handler(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, text=BAN_MESSAGE, show_alert=True)
        return
    uid = call.from_user.id
    user = get_user_data(uid)
    if call.data.startswith("rate_"):
        val = user.get("rate", 0)
        if call.data == "rate_up": val += 5
        elif call.data == "rate_down": val -= 5
        val = max(-100, min(100, val))
        update_user_data(uid, {"rate": val})
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=rate_keyboard(val))
        except Exception: pass
    elif call.data.startswith("pitch_"):
        val = user.get("pitch", 0)
        if call.data == "pitch_up": val += 5
        elif call.data == "pitch_down": val -= 5
        val = max(-100, min(100, val))
        update_user_data(uid, {"pitch": val})
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=pitch_keyboard(val))
        except Exception: pass
    try:
        bot.answer_callback_query(call.id)
    except Exception: pass

@bot.message_handler(content_types=['voice', 'audio', 'video', 'document'])
def handle_other_media(message):
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, BAN_MESSAGE)
        return
    forward_pinned_to_user(message.chat.id, PIN_SOURCE)
    return

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, BAN_MESSAGE)
        return
    
    user_id = message.from_user.id
    user = get_user_data(user_id)
    admin_info = (
        f"@{message.from_user.username if message.from_user.username else 'No Username'}\n"
        f"Id: {message.from_user.id}\n"
        f"First: {message.from_user.first_name}\n"
        f"Lang: {message.from_user.language_code}\n"
        f"text {message.text}"
    )
    try: bot.send_message(ADMIN_ID, admin_info)
    except: pass
    
    raw_text = message.text.replace(".", ",")
    text = process_text_with_groq(raw_text)
    voice_name = user["voice"]["name"]
    filename = generate_tts_filename(user_id)
    
    async def make_tts():
        pitch_val = user.get("pitch", 0)
        rate_val = user.get("rate", 0)
        pitch = f"+{pitch_val}Hz" if pitch_val >= 0 else f"{pitch_val}Hz"
        rate = f"+{rate_val}%" if rate_val >= 0 else f"{rate_val}%"
        tts = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)
        await tts.save(filename)
        
    stop_event = threading.Event()
    action_thread = threading.Thread(target=keep_sending_upload_action, args=(message.chat.id, stop_event))
    action_thread.daemon = True
    action_thread.start()
    
    try:
        asyncio.run(make_tts())
        with open(filename, "rb") as audio:
            bot.send_audio(
                message.chat.id,
                audio,
                reply_to_message_id=message.message_id,
                title=f"Codka_{user_id}_{int(time.time())}",
                performer="SomTTS Bot"
            )
    except Exception as e:
        bot.send_message(message.chat.id, f"Khalad: {e}", reply_to_message_id=message.message_id)
    finally:
        stop_event.set()
        try:
            if os.path.exists(filename): os.remove(filename)
        except: pass

@flask_app.route("/", methods=["GET"])
def index():
    return "Bot-ka wuu socdaa💗", 200

@flask_app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        raw = request.get_data().decode('utf-8')
        bot.process_new_updates([Update.de_json(raw)])
        return '', 200
    abort(403)

if __name__ == "__main__":
    if WEBHOOK_URL:
        try:
            bot.remove_webhook()
            time.sleep(0.5)
            bot.set_webhook(url=WEBHOOK_URL)
        except Exception:
            pass
        flask_app.run(host="0.0.0.0", port=PORT)
    else:
        print("Webhook URL lama dhisin, waan baxayaa.")
