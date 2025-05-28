import os
import logging
import requests
import tempfile
import speech_recognition as sr
from pydub import AudioSegment
from gtts import gTTS
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters,
    CommandHandler, ContextTypes, ConversationHandler
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load keys from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_SUBSCRIPTION_KEY = os.getenv("SARVAM_SUBSCRIPTION_KEY")

if not TELEGRAM_TOKEN or not SARVAM_API_KEY or not SARVAM_SUBSCRIPTION_KEY:
    logger.error("One or more API keys are missing! Please set TELEGRAM_TOKEN, SARVAM_API_KEY, and SARVAM_SUBSCRIPTION_KEY in your environment.")
    exit(1)

# Reply mode constants
ASK_REPLY_TYPE, PROCESS_QUESTION = range(2)
user_language = {}

# Helper: Text-to-Speech (Bengali)
def text_to_speech_bengali(text):
    tts = gTTS(text=text, lang='bn')
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
        tts.save(fp.name)
        return fp.name

# Helper: Speech-to-Text
def recognize_speech(file_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio = recognizer.record(source)
    try:
        return recognizer.recognize_google(audio, language="bn-IN")
    except sr.UnknownValueError:
        return "ভয়েস বোঝা যায়নি, দয়া করে আবার বলুন।"

# Sarvam Bengali API Call
def get_bengali_response(prompt):
    url = "https://api.sarvam.ai/v1/completions"
    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Subscription-Key": SARVAM_SUBSCRIPTION_KEY,
        "X-Subscription-Key": SARVAM_SUBSCRIPTION_KEY,  # Backward compatibility
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sarvam-m",
        "prompt": prompt,
        "max_tokens": 500
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()["choices"][0]["text"].strip()
        else:
            logger.error(f"Sarvam Error: {response.text}")
            return "উত্তর পাওয়া যায়নি। পরে আবার চেষ্টা করুন।"
    except Exception as e:
        logger.error(f"Sarvam Exception: {e}")
        return "❌ ত্রুটি হয়েছে: {}".format(e)

# Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হ্যালো! প্রশ্ন পাঠান (ভয়েস বা টেক্সট)।")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["question"] = update.message.text
    return await ask_reply_type(update, context)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = await update.message.voice.get_file()
    ogg_path = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg").name
    wav_path = ogg_path.replace(".ogg", ".wav")
    try:
        await voice.download_to_drive(ogg_path)
        AudioSegment.from_ogg(ogg_path).export(wav_path, format="wav")
        question = recognize_speech(wav_path)
        context.user_data["question"] = question
        await update.message.reply_text(f"আপনার প্রশ্ন: {question}")
        return await ask_reply_type(update, context)
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await update.message.reply_text(f"❌ ভয়েস প্রসেস করতে সমস্যা হয়েছে: {e}")
        return ConversationHandler.END
    finally:
        # Cleanup temp files
        if os.path.exists(ogg_path):
            try: os.remove(ogg_path)
            except Exception as e: logger.warning(f"Could not remove ogg file: {e}")
        if os.path.exists(wav_path):
            try: os.remove(wav_path)
            except Exception as e: logger.warning(f"Could not remove wav file: {e}")

async def ask_reply_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Text", "Voice"], ["✍️ Text", "🎧 Voice", "🔁 Both"]]
    await update.message.reply_text(
        "আপনি কীভাবে উত্তর পেতে চান?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return PROCESS_QUESTION

async def process_reply_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_type = update.message.text
    question = context.user_data.get("question", "")
    lang = "bn" if any(ord(c) > 127 for c in question) else "en"

    if not question:
        await update.message.reply_text("❗ প্রশ্ন পাওয়া যায়নি। আবার চেষ্টা করুন।")
        return ConversationHandler.END

    if lang == "bn":
        answer = get_bengali_response(question)
    else:
        answer = "Here's your answer (in English): [placeholder]"

    # Accept both new and old reply types
    reply_type = reply_type.strip()
    try:
        if reply_type in ["Voice", "🎧 Voice"]:
            audio_path = text_to_speech_bengali(answer)
            with open(audio_path, 'rb') as audio_file:
                await update.message.reply_voice(voice=audio_file)
            os.remove(audio_path)
        elif reply_type in ["Text", "✍️ Text"]:
            await update.message.reply_text(answer)
        elif reply_type in ["Both", "🔁 Both"]:
            await update.message.reply_text(answer)
            audio_path = text_to_speech_bengali(answer)
            with open(audio_path, 'rb') as audio_file:
                await update.message.reply_voice(voice=audio_file)
            os.remove(audio_path)
        else:
            await update.message.reply_text("⚠️ অনুগ্রহ করে সঠিক অপশন দিন।")
    except Exception as e:
        logger.error(f"Error sending reply: {e}")
        await update.message.reply_text("❌ উত্তর পাঠাতে সমস্যা হয়েছে।")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ কনভার্সেশন বন্ধ করা হয়েছে।")
    return ConversationHandler.END

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
            MessageHandler(filters.VOICE, handle_voice)
        ],
        states={
            PROCESS_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_reply_choice)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("🤖 Bot is running...")
    app.run_polling()
