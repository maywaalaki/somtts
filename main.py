import os
import asyncio
import time
import threading
import tempfile
import subprocess
import logging
from flask import Flask, request, abort
import telebot
import edge_tts
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardMarkup, InlineKeyboardButton
import requests
from pymongo import MongoClient

DB_USER = "lakicalinuur"
DB_PASSWORD = "DjReFoWZGbwjry8K"
DB_APPNAME = "SpeechBot"
MONGO_URI = f"mongodb+srv://{DB_USER}:{DB_PASSWORD}@cluster0.n4hdlxk.mongodb.net/?retryWrites=true&w=majority&appName={DB_APPNAME}"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8508232988:AAEZOvGOU9WNtC5JIhQWV68LL3gI3i-2RYg")
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE", "https://somtts.onrender.com")
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook/")
WEBHOOK_URL = WEBHOOK_URL_BASE.rstrip('/') + WEBHOOK_PATH if WEBHOOK_URL_BASE else ""
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "./downloads")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024
MAX_MESSAGE_CHUNK = 4095

GROQ_KEYS = os.environ.get("GROQ_KEYS", "")
GROQ_TEXT_MODEL = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

ADMIN_ID = 6964068910

user_voices = {}
user_rate_settings = {}
user_pitch_settings = {}

db_client = None
db = None
users_col = None

logging.basicConfig(level=logging.INFO)

class KeyRotator:
    def __init__(self, keys):
        self.keys = [k.strip() for k in keys.split(",") if k.strip()]
        self.pos = 0
        self.lock = threading.Lock()

    def get_key(self):
        with self.lock:
            if not self.keys:
                return None
            key = self.keys[self.pos]
            self.pos = (self.pos + 1) % len(self.keys)
            return key

groq_rotator = KeyRotator(GROQ_KEYS)

def init_db():
    global db_client, db, users_col
    try:
        db_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db_client.server_info()
        db = db_client[DB_APPNAME]
        users_col = db["users"]
    except:
        db_client = None
        users_col = None

def load_all_user_settings():
    if not users_col:
        return
    for doc in users_col.find({}):
        uid = str(doc["_id"])
        user_voices[uid] = doc.get("voice", {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"})
        user_rate_settings[uid] = int(doc.get("rate", 0))
        user_pitch_settings[uid] = int(doc.get("pitch", 0))

def save_user_settings(uid):
    if not users_col:
        return
    users_col.update_one(
        {"_id": str(uid)},
        {"$set": {
            "voice": user_voices.get(str(uid)),
            "rate": user_rate_settings.get(str(uid), 0),
            "pitch": user_pitch_settings.get(str(uid), 0)
        }},
        upsert=True
    )

def process_text_with_groq(text):
    instruction = """Waxaad tahay Text Normalizer Af-Soomaali. Ha turjumin Ingiriisi, u qor sida loo dhawaaqo. Dhammaan tirooyinka u beddel erayo Af-Soomaali ah si dabiici ah. Jawaabtaadu ha noqoto qoraalka la habeeyay oo keliya."""
    if not groq_rotator.keys:
        return text
    for _ in range(len(groq_rotator.keys)):
        key = groq_rotator.get_key()
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": GROQ_TEXT_MODEL,
                    "messages": [
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": text}
                    ],
                    "temperature": 0.2
                },
                timeout=15
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
        except:
            continue
    return text

def transcribe_local_file_groq(path):
    for _ in range(len(groq_rotator.keys)):
        key = groq_rotator.get_key()
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": f},
                    data={"model": "whisper-large-v3"},
                    timeout=300
                )
            if r.status_code == 200:
                return r.json().get("text", "")
        except:
            continue
    return ""

def generate_tts_filename(uid):
    return os.path.join(DOWNLOADS_DIR, f"Codka_{uid}_{int(time.time()*1000)}.mp3")

def create_voice_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Ubax 👩🏻‍🦳"), KeyboardButton("Muuse 👨🏻‍🦱"))
    return kb

def rate_keyboard(val):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("➖", callback_data="rate_down"),
        InlineKeyboardButton(f"Rate: {val}", callback_data="rate_noop"),
        InlineKeyboardButton("➕", callback_data="rate_up")
    )
    return kb

def pitch_keyboard(val):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("➖", callback_data="pitch_down"),
        InlineKeyboardButton(f"Pitch: {val}", callback_data="pitch_noop"),
        InlineKeyboardButton("➕", callback_data="pitch_up")
    )
    return kb

def keep_action(chat_id, stop_event, action):
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, action)
        except:
            pass
        time.sleep(3)

@bot.message_handler(commands=["start"])
def start(message):
    uid = str(message.from_user.id)
    if uid not in user_voices:
        user_voices[uid] = {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"}
        save_user_settings(uid)
    bot.send_message(message.chat.id, "Soo dhawow! Waxaan ahay Somali Text to Speech bot waxaa i samee yay zack3d:\n\nii soo dir qoraal si aan ugu badalo cod💗", reply_markup=create_voice_keyboard())

@bot.message_handler(func=lambda m: m.text in ["Ubax 👩🏻‍🦳", "Muuse 👨🏻‍🦱"])
def set_voice(message):
    uid = str(message.from_user.id)
    if "Ubax" in message.text:
        user_voices[uid] = {"name": "so-SO-UbaxNeural", "label": "Ubax 👩🏻‍🦳"}
    else:
        user_voices[uid] = {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"}
    save_user_settings(uid)
    bot.send_message(message.chat.id, "OK, ii soo dir qoraalka.")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    uid = str(message.from_user.id)
    raw = message.text.replace("?", ", ")
    text = process_text_with_groq(raw)
    filename = generate_tts_filename(uid)

    async def run_tts():
        rate = user_rate_settings.get(uid, 0)
        pitch = user_pitch_settings.get(uid, 0)
        tts = edge_tts.Communicate(
            text,
            user_voices.get(uid, {}).get("name", "so-SO-MuuseNeural"),
            rate=f"{rate:+d}%",
            pitch=f"{pitch:+d}Hz"
        )
        await tts.save(filename)

    stop = threading.Event()
    threading.Thread(target=keep_action, args=(message.chat.id, stop, "upload_audio"), daemon=True).start()

    try:
        asyncio.run(run_tts())
        with open(filename, "rb") as a:
            bot.send_audio(message.chat.id, a, reply_to_message_id=message.message_id)
    except Exception as e:
        bot.send_message(message.chat.id, f"Khalad: {e}")
    finally:
        stop.set()
        if os.path.exists(filename):
            os.remove(filename)

@bot.message_handler(content_types=["voice", "audio", "video", "document"])
def handle_media(message):
    media = message.voice or message.audio or message.video or message.document
    file_info = bot.get_file(media.file_id)
    if file_info.file_size > MAX_UPLOAD_SIZE:
        bot.send_message(message.chat.id, f"isoo dir Cod ama muuqaal kayar {MAX_UPLOAD_MB}MB 👍")
        return

    tmp_in = tempfile.NamedTemporaryFile(delete=False, dir=DOWNLOADS_DIR).name
    tmp_out = tmp_in + ".wav"
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

    with requests.get(url, stream=True) as r:
        with open(tmp_in, "wb") as f:
            for c in r.iter_content(8192):
                f.write(c)

    subprocess.run(["ffmpeg", "-y", "-i", tmp_in, "-ar", "16000", "-ac", "1", tmp_out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    text = transcribe_local_file_groq(tmp_out)

    if text:
        for i in range(0, len(text), MAX_MESSAGE_CHUNK):
            bot.send_message(message.chat.id, text[i:i+MAX_MESSAGE_CHUNK])
    else:
        bot.send_message(message.chat.id, "Codka lama fahmin")

    os.remove(tmp_in)
    os.remove(tmp_out)

@flask_app.route("/", methods=["GET"])
def index():
    return "Bot-ka wuu socdaa 💗", 200

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        bot.process_new_updates([Update.de_json(request.get_data().decode())])
        return "", 200
    abort(403)

if __name__ == "__main__":
    init_db()
    load_all_user_settings()
    if WEBHOOK_URL:
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        flask_app.run(host="0.0.0.0", port=PORT)
