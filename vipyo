import os
import asyncio
import time
import threading
from flask import Flask, request, abort
import telebot
import edge_tts
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardMarkup, InlineKeyboardButton
import re
from pymongo import MongoClient
import tempfile
import requests
import subprocess
import glob
import logging

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
GROQ_KEYS = os.environ.get("GROQ_KEYS", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024
MAX_MESSAGE_CHUNK = 4095

os.makedirs(DOWNLOADS_DIR, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

ADMIN_ID = 6964068910

user_voices = {}
user_rate_settings = {}
user_pitch_settings = {}

UNITS = {
    0: "eber", 1: "kow", 2: "labo", 3: "saddex", 4: "afar",
    5: "shan", 6: "lix", 7: "toddobo", 8: "siddeed", 9: "sagaal",
    10: "toban", 20: "labaatan", 30: "soddon", 40: "afartan",
    50: "konton", 60: "lixdan", 70: "toddobaatan", 80: "sideedan", 90: "sagaashan"
}

db_client = None
db = None
users_col = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class KeyRotator:
    def __init__(self, keys):
        self.keys = [k.strip() for k in keys.split(",") if k.strip()] if isinstance(keys, str) else list(keys or [])
        self.pos = 0
        self.lock = threading.Lock()
    def get_key(self):
        with self.lock:
            if not self.keys:
                return None
            key = self.keys[self.pos]
            self.pos = (self.pos + 1) % len(self.keys)
            return key
    def mark_success(self, key):
        with self.lock:
            try:
                i = self.keys.index(key)
                self.pos = (i + 1) % len(self.keys)
            except ValueError:
                pass
    def mark_failure(self, key):
        self.mark_success(key)

groq_rotator = KeyRotator(GROQ_KEYS)

def execute_groq_action(action_callback):
    last_exc = None
    total = len(groq_rotator.keys) or 1
    for _ in range(total + 1):
        key = groq_rotator.get_key()
        if not key:
            raise RuntimeError("No Groq keys available")
        try:
            result = action_callback(key)
            groq_rotator.mark_success(key)
            return result
        except Exception as e:
            last_exc = e
            logging.warning(f"Groq error with key {str(key)[:4]}: {e}")
            groq_rotator.mark_failure(key)
    raise RuntimeError(f"Groq failed after rotations. Last error: {last_exc}")

def transcribe_local_file_groq(file_path, language=None):
    if not groq_rotator.keys:
        raise RuntimeError("Groq key(s) not configured")
    def perform_all_steps(key):
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
            return text
    return execute_groq_action(perform_all_steps)

def init_db():
    global db_client, db, users_col
    try:
        db_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db_client.server_info()
        db = db_client[DB_APPNAME]
        users_col = db['users']
    except Exception as e:
        db_client = None
        users_col = None

def load_all_user_settings():
    if users_col is None:
        return
    try:
        for doc in users_col.find({}):
            uid = str(doc.get("_id"))
            v = doc.get("voice")
            if v:
                user_voices[uid] = v
            user_rate_settings[uid] = int(doc.get("rate", 0))
            user_pitch_settings[uid] = int(doc.get("pitch", 0))
    except Exception:
        pass

def save_user_settings(user_id):
    if users_col is None:
        return
    try:
        uid = str(user_id)
        doc = {
            "voice": user_voices.get(uid, {}),
            "rate": int(user_rate_settings.get(uid, 0)),
            "pitch": int(user_pitch_settings.get(uid, 0))
        }
        users_col.update_one({"_id": uid}, {"$set": doc}, upsert=True)
    except Exception:
        pass

def number_to_somali(n: int, is_one_as_hal=False) -> str:
    if n == 1 and is_one_as_hal:
        return "hal"
    if n < 20:
        if n <= 10:
            return UNITS[n]
        return f"toban iyo {UNITS[n-10]}"
    if n < 100:
        tens = (n // 10) * 10
        rest = n % 10
        return UNITS[tens] if rest == 0 else f"{UNITS[tens]} iyo {UNITS[rest]}"
    if n < 1000:
        hundreds = n // 100
        rest = n % 100
        prefix = "boqol" if hundreds == 1 else f"{number_to_somali(hundreds, True)} boqol"
        if rest == 0:
            return prefix
        return f"{prefix} iyo {number_to_somali(rest)}"
    if n < 1000000:
        thousands = n // 1000
        rest = n % 1000
        prefix = "kun" if thousands == 1 else f"{number_to_somali(thousands, True)} kun"
        if rest == 0:
            return prefix
        return f"{prefix} iyo {number_to_somali(rest)}"
    if n < 1000000000:
        millions = n // 1000000
        rest = n % 1000000
        prefix = "malyan" if millions == 1 else f"{number_to_somali(millions, True)} malyan"
        if rest == 0:
            return prefix
        return f"{prefix} iyo {number_to_somali(rest)}"
    if n < 1000000000000:
        billions = n // 1000000000
        rest = n % 1000000000
        prefix = "bilyan" if billions == 1 else f"{number_to_somali(billions, True)} bilyan"
        if rest == 0:
            return prefix
        return f"{prefix} iyo {number_to_somali(rest)}"
    if n < 1000000000000000:
        trillions = n // 1000000000000
        rest = n % 1000000000000
        prefix = "trilyan" if trillions == 1 else f"{number_to_somali(trillions, True)} trilyan"
        if rest == 0:
            return prefix
        return f"{prefix} iyo {number_to_somali(rest)}"
    if n < 1000000000000000000:
        quadrillions = n // 1000000000000000
        rest = n % 1000000000000000
        prefix = "kuadrilyan" if quadrillions == 1 else f"{number_to_somali(quadrillions, True)} kuadrilyan"
        if rest == 0:
            return prefix
        return f"{prefix} iyo {number_to_somali(rest)}"
    return str(n)

def replace_numbers_with_words(text: str) -> str:
    text = re.sub(r'(?<!\d)\.(?!\d)', ', ', text)
    text = text.replace("%", " boqolkiiba ")
    text = re.sub(r'(?<=\d),(?=\d)', '', text)
    text = re.sub(r"\$(\d+(\.\d+)?[kKmMbBtT]?)", r"\1 doolar", text)
    text = re.sub(r"€(\d+(\.\d+)?[kKmMbBtT]?)", r"\1 yuuro", text)
    text = re.sub(r"£(\d+(\.\d+)?[kKmMbBtT]?)", r"\1 bownd", text)
    text = re.sub(r"\b(\d+(\.\d+)?)[kK]\b", lambda m: str(float(m.group(1)) * 1000).rstrip('0').rstrip('.'), text)
    text = re.sub(r"\b(\d+(\.\d+)?)[mM]\b", lambda m: str(float(m.group(1)) * 1000000).rstrip('0').rstrip('.'), text)
    text = re.sub(r"\b(\d+(\.\d+)?)[bB]\b", lambda m: str(float(m.group(1)) * 1000000000).rstrip('0').rstrip('.'), text)
    text = re.sub(r"\b(\d+(\.\d+)?)[tT]\b", lambda m: str(float(m.group(1)) * 1000000000000).rstrip('0').rstrip('.'), text)
    def repl(match):
        num_str = match.group()
        if "." in num_str:
            parts = num_str.split(".")
            whole_num = int(parts[0])
            decimal_str = parts[1]
            whole_somali = number_to_somali(whole_num, is_one_as_hal=True)
            if len(decimal_str) <= 2:
                decimal_somali = number_to_somali(int(decimal_str))
            else:
                decimal_somali = " ".join([UNITS[int(d)] for d in decimal_str])
            return f"{whole_somali} dhibic {decimal_somali}"
        n = int(num_str)
        return number_to_somali(n, is_one_as_hal=(n == 1))
    return re.sub(r"\b\d+(\.\d+)?\b", repl, text)

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
        except:
            pass

@bot.message_handler(commands=["start"])
def start(message):
    keyboard = create_voice_keyboard()
    user_id_str = str(message.from_user.id)
    if user_id_str not in user_voices:
        user_voices[user_id_str] = {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"}
        save_user_settings(user_id_str)
    bot.send_message(
        message.chat.id,
        "👋🏻 Soo dhawow! Waxaan ahay SomTTS Bot waxaan qoraalada afsomaliga ubadali karaa cod ai afsomali sidoo kale waxaan codadka iyo muuqaalada English ka iyo Carabi ga ubadali karaa qoraal hadii hadal uu jiro 😜 \n\nIi soo dir qoraal si aan ugu badalo cod 💗 ama soo dir muuqaal ama cod ka yar 20mb si aan u qoro 😎",
        reply_markup=keyboard,
        reply_to_message_id=message.message_id
    )

@bot.message_handler(func=lambda m: m.text in ["Ubax 👩🏻‍🦳", "Muuse 👨🏻‍🦱"])
def set_voice(message):
    user_id_str = str(message.from_user.id)
    choice = message.text
    if "Ubax" in choice:
        user_voices[user_id_str] = {"name": "so-SO-UbaxNeural", "label": "Ubax 👩🏻‍🦳"}
    elif "Muuse" in choice:
        user_voices[user_id_str] = {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"}
    save_user_settings(user_id_str)
    bot.send_message(
        message.chat.id,
        "OK, ii soo dir qoraalka.",
        reply_to_message_id=message.message_id
    )

@bot.message_handler(commands=['rate'])
def cmd_rate(message):
    user_id = str(message.from_user.id)
    current = user_rate_settings.get(user_id, 0)
    bot.send_message(message.chat.id, "Halkan ka hagaaji xawaaraha:", reply_markup=rate_keyboard(current))

@bot.message_handler(commands=['pitch'])
def cmd_pitch(message):
    user_id = str(message.from_user.id)
    current = user_pitch_settings.get(user_id, 0)
    bot.send_message(message.chat.id, "Halkan ka hagaaji pitch-ka:", reply_markup=pitch_keyboard(current))

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith(("rate_", "pitch_")))
def slider_handler(call):
    uid = str(call.from_user.id)
    if call.data.startswith("rate_"):
        val = user_rate_settings.get(uid, 0)
        if call.data == "rate_up":
            val += 5
        elif call.data == "rate_down":
            val -= 5
        val = max(-100, min(100, val))
        user_rate_settings[uid] = val
        save_user_settings(uid)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=rate_keyboard(val))
        except Exception:
            pass
    elif call.data.startswith("pitch_"):
        val = user_pitch_settings.get(uid, 0)
        if call.data == "pitch_up":
            val += 5
        elif call.data == "pitch_down":
            val -= 5
        val = max(-100, min(100, val))
        user_pitch_settings[uid] = val
        save_user_settings(uid)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=pitch_keyboard(val))
        except Exception:
            pass
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    user_id_str = str(message.from_user.id)
    admin_info = (
        f"@{message.from_user.username if message.from_user.username else 'No Username'}\n"
        f"Id: {message.from_user.id}\n"
        f"First: {message.from_user.first_name}\n"
        f"Lang: {message.from_user.language_code}\n"
        f"text {message.text}"
    )
    try:
        bot.send_message(ADMIN_ID, admin_info)
    except:
        pass
    raw_text = message.text.replace("?", ", ")
    text = replace_numbers_with_words(raw_text)
    voice_name = user_voices.get(user_id_str, {}).get("name", "so-SO-MuuseNeural")
    filename = generate_tts_filename(user_id_str)
    async def make_tts():
        pitch_val = user_pitch_settings.get(user_id_str, 0)
        rate_val = user_rate_settings.get(user_id_str, 0)
        pitch = f"+{pitch_val}Hz" if pitch_val >= 0 else f"{pitch_val}Hz"
        rate = f"+{rate_val}%" if rate_val >= 0 else f"{rate_val}%"
        tts = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)
        await tts.save(filename)
    stop_event = threading.Event()
    action_thread = threading.Thread(target=keep_sending_action, args=(message.chat.id, stop_event, "upload_audio"))
    action_thread.daemon = True
    action_thread.start()
    try:
        asyncio.run(make_tts())
        with open(filename, "rb") as audio:
            bot.send_audio(
                message.chat.id,
                audio,
                reply_to_message_id=message.message_id,
                title=f"Codka_{user_id_str}_{int(time.time())}",
                performer="SomTTS Bot"
            )
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"Khalad: {e}",
            reply_to_message_id=message.message_id
        )
    finally:
        stop_event.set()
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except:
            pass

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
def index_route():
    return "Bot-ka wuu socdaa💗", 200

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        raw = request.get_data().decode('utf-8')
        bot.process_new_updates([Update.de_json(raw)])
        return '', 200
    abort(403)

if __name__ == "__main__":
    init_db()
    load_all_user_settings()
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
