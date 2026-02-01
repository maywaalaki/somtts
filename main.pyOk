import os
import asyncio
import time
import threading
from flask import Flask, request, abort
import telebot
import edge_tts
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardMarkup, InlineKeyboardButton
import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8508232988:AAEZOvGOU9WNtC5JIhQWV68LL3gI3i-2RYg")
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE", "https://somtts.onrender.com")
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook/")
WEBHOOK_URL = WEBHOOK_URL_BASE.rstrip('/') + WEBHOOK_PATH if WEBHOOK_URL_BASE else ""
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "./downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

GROQ_KEYS = os.environ.get("GROQ_KEYS", "")
GROQ_TEXT_MODEL = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

ADMIN_ID = 6964068910

user_voices = {}
user_rate_settings = {}
user_pitch_settings = {}

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
    instruction = """Waxaad tahay kaaliye ku takhasusay hagaajinta qoraalka (Text Normalizer). Shaqadaadu waa inaad qoraalka Ingiriisiga, tirooyinka, iyo soo-gaabinnada u beddesho qaab Af-Soomaali ah oo si fudud loo akhrin karo loona maqli karo, kana dhawaajiya hadal dabiici ah oo Soomaali ah.

Jawaabtaadu waa inay noqotaa oo keliya qoraalka la beddelay. Ha ku darin salaan, sharraxaad, faallo, ama hadal kale oo dheeraad ah.

Marka aad la kulanto lacago, waa inaad raacdaa naxwaha iyo dhawaaqa Af-Soomaaliga. Ereyga “oo” isticmaal marka ay tiradu tahay milyan ama bilyan, ama marka ay tahay boqol sax ah. Tusaale ahaan, $1m waa hal milyan oo doolar, £5bn waa shan bilyan oo ginni, $900 waa sagaal boqol oo doolar, halka $100 uu yahay boqol doolar. Haddii tiradu ka kooban tahay boqol iyo wax ka dambeeya sida tobaneeyo ama unugyo, ha isticmaalin “oo”. Tusaale ahaan, $120 waa boqol iyo labaatan doolar, $450 waa afar boqol iyo konton doolar, $1,250 waa kun iyo laba boqol iyo konton doolar, halka $10 uu yahay toban doolar.

Magacyada waddamada iyo ururada waa in loo adeegsadaa magacyadooda Af-Soomaaliga ah ee rasmiga ah. USA ama United States waa Maraykanka, UK ama United Kingdom waa Boqortooyada Ingiriiska, EU waa Midowga Yurub, halka UN ay tahay Qaramada Midoobay.

Haddii qoraalku ka kooban yahay soo-gaabin ama xarfo isku-dhafan oo aan lahayn magac Soomaali ah, waa in loo qoraa xaraf-xaraf sida ay u dhawaaqaan Af-Soomaali ahaan. Tusaale ahaan, USB waa yuu es bii, AI waa e ay, GPT waa ji pi ti, HTTP-na waa hej ti ti bi.

Dhammaan tirooyinka iyo boqolleyda waa in loo beddelaa erayo Soomaali ah. Tusaale ahaan, 2026 waa labada kun lix iyo labaatan, 5%-na waa shan boqolkiiba.

Erayada farsamada ee leh u dhigma Af-Soomaali ah waa in la turjumo, sida ( km ) oo noqota kiilo mitir. Haddii eray farsamo uusan lahayn turjumaad toos ah, waa in loo qoraa sida uu u dhawaaqo, sida Drive oo noqda darayf, ama Email oo noqda iimayl.

Haddii eray ama isku-dar erayo u muuqdaan magac gaar ah (magac qof, magac isticmaale, magac hees, magac shirkad, ama brand ama magac koox,) HA turjumin xitaa haddii uu leeyahay macne Af-Soomaali ah. U qor sida uu u dhawaaqo ama sida uu u qoran yahay.

sidoo kale wax yaabaha ka hoo seeyo 1$ u qor hab fudu tusaale 0.5$ u qor > nusdoolar 0.1$ toban sinti 0.9& sagaashan sinti

Mar walba ilaali macnaha guud ee jumlada, hana beddelin ujeeddada qoraalka. Sidoo kale ilaali calaamadaha qoraalka sida dhibcaha iyo su’aalaha si akhrisku u ahaado mid hagaagsan oo la fahmi karo """
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
    keyboard = create_voice_keyboard()
    user_id_str = str(message.from_user.id)
    if user_id_str not in user_voices:
        user_voices[user_id_str] = {"name": "so-SO-MuuseNeural", "label": "Muuse 👨🏻‍🦱"}
    bot.send_message(
        message.chat.id,
        "Soo dhawow! Waxaan ahay Somali Text to Speech bot waxaa i samee yay zack3d:\n\nii soo dir qoraal si aan ugu badalo cod💗",
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
    groq_processed = process_text_with_groq(raw_text)
    text = groq_processed
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
