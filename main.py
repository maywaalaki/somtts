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

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

ADMIN_ID = 6964068910

def get_user_data(user_id):
    user = users_col.find_one({"user_id": str(user_id)})
    if not user:
        user = {
            "user_id": str(user_id),
            "voice": {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"},
            "rate": 0,
            "pitch": 0
        }
        users_col.insert_one(user)
    return user

def update_user_data(user_id, updates):
    users_col.update_one({"user_id": str(user_id)}, {"$set": updates}, upsert=True)

class KeyRotator:
    def __init__(self, keys_str):
        self.keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        self.index = 0
        self.lock = threading.Lock()

    def get_key(self):
        with self.lock:
            if not self.keys:
                return None
            key = self.keys[self.index]
            self.index = (self.index + 1) % len(self.keys)
            return key

key_manager = KeyRotator(GROQ_KEYS)

def process_text_with_groq(text):
    instruction = """Waxaad tahay kaaliye ku takhasusay hagaajinta qoraalka (Text Normalizer). Shaqadaadu waa inaad qoraalka Ingiriisiga, tirooyinka, iyo soo-gaabinnada u beddesho qaab Af-Soomaali ah oo si fudud loo akhrin karo loona maqli karo.

    XEERARKA MUHIIMKA AH:

    1. HA TURJUMIN ERAYADA INGIRIISIGA: Haddii qoraalka ay ku jiraan erayo Ingiriis ah (sida magacyo cilmiyeed, koorsooyin, cinwaanno, ama erayo farsamo), HA U BEDDELIN MACNAHOODA SOOMAALIGA. Taa beddelkeeda, u qor sida loogu dhawaaqo (Phonetic Transliteration).
       - Tusaale: "Nutrition" ha ka dhigin "Nafaqo", ka dhig "Nuutrishin".
       - Tusaale: "Pharmacology" ha ka dhigin "Cilmiga dawooyinka", ka dhig "Faarmakooloji".
       - Tusaale: "Supply chain" -> "Sablay jeen".
       - Tusaale: "Maternal and child health" -> "Matarnal end jayld helt".

    2. LACAGAHA IYO TIROOYINKA: Raac naxwaha iyo dhawaaqa Af-Soomaaliga.
       - $1m -> hal milyan oo doolar.
       - $120 -> boqol iyo labaatan doolar.
       - 0.5$ -> nusdoolar.
       - 0.1$ -> toban sinti.
       - 0.01$ halsinti
    3. SOO-GAABINNADA (ACRONYMS): Haddii ay yihiin xarfo la soo gaabiyay, u qor sida xarfaha loo akhriyo.
       - USB -> yuu es bii.
       - AI -> e ay.
       - HIV -> hej ay vii.

    4. MAGACYADA DALALKA: Kuwaas waad turjumi kartaa haddii ay caan yihiin (USA -> Maraykanka), laakiin magacyada gaarka ah (Brands, Shirkado, Magacyo dad) sidiisa u daa ama u qor sida loogu dhawaaqo.

    5. TIROOYINKA IYO IS-RAACINTA NAXWAHA (Contextual Numbers):
       Dhammaan tirooyinka u qor ereyo Af-Soomaali ah (Tusaale: 2026 -> laba kun lix iyo labaatan).
       MUHIIM: Kahor inta aadan tirada qorin, fiiri ereyada ka horreeya iyo nuxurka jumladda si aad ugu dartid daba-galka (suffix) saxda ah:
       - Haddii jumlada ay tilmaamayso waqti xaadir ah ama qeexid guud, raaci "-ka" ama "-ta".
         Tusaale: "Sanadkii 2020" -> "Sanadkii labada kun iyo labaatanka".
       - Haddii jumlada ay ka hadlayso waqti hore (Past Tense) ama wax dhacay, isticmaal "-kii" ama "-tii" beddelka "-ka".
         Tusaale: "Dhismihii 1990" -> "Dhismihii kun sagaal boqol iyo sagaashankii".

    Hadafku waa in qoraalka marka cod loo beddelo uu u dhawaaco sidii qof Soomaali ah oo akhrinaya erayadaas Ingiriisiga ah si dabiici ah. Jawaabtaadu waa inay noqotaa oo keliya qoraalka la habeeyay."""
    if not key_manager.keys:
        return text
    for _ in range(len(key_manager.keys) or 1):
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
                    return response.json()['choices'][0]['message']['content'].strip()
                except Exception:
                    return text
        except Exception:
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

@bot.message_handler(commands=["start"])
def start(message):
    get_user_data(message.from_user.id)
    keyboard = create_voice_keyboard()
    bot.send_message(
        message.chat.id,
        "Soo dhawow Laki! Waxaan ahay Somali Text to Speech bot waxaa i samee yay zack3d:\n\nii soo dir qoraal si aan ugu badalo cod💗",
        reply_markup=keyboard,
        reply_to_message_id=message.message_id
    )

@bot.message_handler(func=lambda m: m.text in ["Ubax 👩🏻‍🦳", "Muuse 👨🏻‍🦱"])
def set_voice(message):
    user_id = message.from_user.id
    choice = message.text
    if "Ubax" in choice:
        voice_data = {"name": "so-SO-UbaxNeural", "label": "Ubax 👩🏻‍🦳"}
    else:
        voice_data = {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"}
    update_user_data(user_id, {"voice": voice_data})
    bot.send_message(
        message.chat.id,
        f"Codka waa la beddelay: {choice}\n\nOK, ii soo dir qoraalka.",
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
    raw_text = message.text.replace("?", ", ")
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
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        flask_app.run(host="0.0.0.0", port=PORT)
    else:
        print("Webhook URL lama dhisin, waan baxayaa.")
