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
import tempfile
import subprocess
import logging
import re

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8508232988:AAEZOvGOU9WNtC5JIhQWV68LL3gI3i-2RYg")
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE", "https://somtts.onrender.com")
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook/")
WEBHOOK_URL = WEBHOOK_URL_BASE.rstrip('/') + WEBHOOK_PATH if WEBHOOK_URL_BASE else ""
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "./downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

GROQ_KEYS = os.environ.get("GROQ_KEYS", "")
GROQ_TEXT_MODEL = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")

MONGO_URI = "mongodb+srv://lakiup3_db_user:V4Nbt6YcqH0qCBix@cluster0.my3ety2.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client['somtts_bot']
users_col = db['users']

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024
MAX_MESSAGE_CHUNK = 4095

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

ADMIN_ID = 6964068910

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_user_data(user_id):
    user = users_col.find_one({"user_id": str(user_id)})
    if not user:
        user = {
            "user_id": str(user_id),
            "voice": {"name": "so-SO-MuuseNeural", "label": "Muuse"},
            "rate": 0,
            "pitch": 0
        }
        users_col.insert_one(user)
    return user

def update_user_data(user_id, updates):
    users_col.update_one({"user_id": str(user_id)}, {"$set": updates}, upsert=True)

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

def transcribe_local_file_groq(file_path, language=None):
    if not key_manager.keys:
        raise RuntimeError("No Groq keys configured")
    last_exc = None
    total = len(key_manager.keys) or 1
    for _ in range(total + 1):
        key = key_manager.get_key()
        if not key:
            raise RuntimeError("No Groq keys available")
        try:
            with open(file_path, "rb") as f:
                files = {"file": f}
                data = {"model": "whisper-large-v3"}
                if language:
                    data["language"] = language
                headers = {"authorization": f"Bearer {key}"}
                resp = requests.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=300)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("text") or data.get("transcription") or data.get("transcript") or ""
                if not text and isinstance(data.get("results"), list) and data["results"]:
                    first = data["results"][0]
                    text = first.get("text") or first.get("transcript") or ""
                key_manager.mark_success(key)
                return text
        except Exception as e:
            last_exc = e
            key_manager.mark_failure(key)
            continue
    raise RuntimeError(f"Transcription failed. Last error: {last_exc}")

def generate_tts_filename(user_id):
    safe_id = str(user_id).replace(" ", "_")
    return os.path.join(DOWNLOADS_DIR, f"Codka_{safe_id}_{int(time.time()*1000)}.mp3")

def create_voice_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    keyboard.add(KeyboardButton("Codka qulaa sada🔥"), KeyboardButton("Ubax"), KeyboardButton("Muuse"))
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

def keep_sending_action(chat_id, stop_event, action="typing", interval=3):
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, action)
        except Exception:
            pass
        time.sleep(interval)

def send_long_text(chat_id, text, reply_id):
    if not text:
        return
    for i in range(0, len(text), MAX_MESSAGE_CHUNK):
        try:
            bot.send_message(chat_id, text[i:i+MAX_MESSAGE_CHUNK], reply_to_message_id=reply_id)
        except Exception:
            pass

@bot.message_handler(commands=["start"])
def start(message):
    get_user_data(message.from_user.id)
    keyboard = create_voice_keyboard()
    bot.send_message(
        message.chat.id,
        "Soo dhawow! Waxaan ahay Somali Text to Speech bot waxaa i samee yay zack3d:\n\nii soo dir qoraal si aan ugu badalo cod💗",
        reply_markup=keyboard,
        reply_to_message_id=message.message_id
    )

@bot.message_handler(func=lambda m: m.text in ["Ubax", "Muuse", "Codka qulaa sada🔥"])
def set_voice(message):
    user_id = message.from_user.id
    choice = message.text
    if "Ubax" in choice:
        voice_data = {"name": "so-SO-UbaxNeural", "label": "Ubax"}
        update_user_data(user_id, {"voice": voice_data})
    elif "Codka qulaa" in choice or "qulaa" in choice:
        voice_data = {"name": "so-SO-MuuseNeural", "label": "Codka qulaa sada🔥"}
        update_user_data(user_id, {"voice": voice_data, "pitch": 45, "rate": 30})
    else:
        voice_data = {"name": "so-SO-MuuseNeural", "label": "Muuse"}
        update_user_data(user_id, {"voice": voice_data})
    bot.send_message(
        message.chat.id,
        f"Ok hada Codka waa: {choice}\n\n ii soo dir qoraalka 👍",
        reply_to_message_id=message.message_id
    )

@bot.message_handler(commands=['rate'])
def cmd_rate(message):
    user = get_user_data(message.from_user.id)
    current = user.get("rate", 0)
    bot.send_message(message.chat.id, "Halkan ka hagaaji xawaaraha:", reply_markup=rate_keyboard(current))

@bot.message_handler(commands=['pitch'])
def cmd_pitch(message):
    user = get_user_data(message.from_user.id)
    current = user.get("pitch", 0)
    bot.send_message(message.chat.id, "Halkan ka hagaaji pitch-ka:", reply_markup=pitch_keyboard(current))

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith(("rate_", "pitch_")))
def slider_handler(call):
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

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
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

@bot.message_handler(content_types=['voice', 'audio', 'video', 'document'])
def handle_media(message):
    media = message.voice or message.audio or message.video or message.document
    if not media:
        return
    try:
        file_info = bot.get_file(media.file_id)
    except Exception:
        bot.send_message(message.chat.id, "Khalad: lama helin faylka.", reply_to_message_id=message.message_id)
        return
    size = getattr(file_info, "file_size", 0)
    if size and size > MAX_UPLOAD_SIZE:
        bot.send_message(message.chat.id, f"Fadlan soo dir Cod ama Video ka yar {MAX_UPLOAD_MB}MB 🤓", reply_to_message_id=message.message_id)
        return
    status_msg = None
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=keep_sending_action, args=(message.chat.id, stop_event, "typing"))
    spinner_thread.daemon = True
    try:
        status_msg = bot.reply_to(message, "Ok wax yar sug 👍")
    except:
        status_msg = None
    spinner_thread.start()
    tmp_in = None
    tmp_out_path = None
    try:
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        tmp_in = tempfile.NamedTemporaryFile(delete=False, dir=DOWNLOADS_DIR)
        tmp_in_path = tmp_in.name
        tmp_in.close()
        with requests.get(download_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp_in_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        tmp_out_path = tmp_in_path + "_conv.wav"
        subprocess.run(["ffmpeg", "-y", "-i", tmp_in_path, "-ar", "16000", "-ac", "1", tmp_out_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            text = transcribe_local_file_groq(tmp_out_path)
        except Exception as e:
            logging.exception("Transcription error: %s", e)
            text = ""
        if not text:
            bot.send_message(message.chat.id, "ma aanan fahmin codka.", reply_to_message_id=message.message_id)
        else:
            send_long_text(message.chat.id, text, message.message_id)
    except Exception as e:
        logging.exception("handle_media error: %s", e)
        try:
            bot.send_message(message.chat.id, "Khalad ayaa dhacay 😓", reply_to_message_id=message.message_id)
        except:
            pass
    finally:
        stop_event.set()
        try:
            if status_msg:
                try:
                    bot.delete_message(status_msg.chat.id, status_msg.message_id)
                except:
                    pass
        except:
            pass
        try:
            if tmp_in and os.path.exists(tmp_in.name):
                os.remove(tmp_in.name)
        except:
            pass
        try:
            if tmp_out_path and os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)
        except:
            pass

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
