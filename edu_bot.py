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

# Load keys from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_SUBSCRIPTION_KEY = os.getenv("SARVAM_SUBSCRIPTION_KEY")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sarvam-m",
        "prompt": prompt,
        "max_tokens": 500
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["text"].strip()
    else:
        logger.error(f"Sarvam Error: {response.text}")
        return "উত্তর পাওয়া যায়নি। পরে আবার চেষ্টা করুন।"

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
    await voice.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(wav_path, format="wav")
    question = recognize_speech(wav_path)
    context.user_data["question"] = question
    await update.message.reply_text(f"আপনার প্রশ্ন: {question}")
    return await ask_reply_type(update, context)

async def ask_reply_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Text", "Voice"]]
    await update.message.reply_text(
        "আপনি কীভাবে উত্তর পেতে চান?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return PROCESS_QUESTION

async def process_reply_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_type = update.message.text
    question = context.user_data.get("question", "")
    lang = "bn" if any(ord(c) > 127 for c in question) else "en"

    if lang == "bn":
        answer = get_bengali_response(question)
    else:
        answer = "Here's your answer (in English): [placeholder]"  # Replace with OpenAI or logic

    if reply_type == "Voice":
        audio_path = text_to_speech_bengali(answer)
        await update.message.reply_voice(voice=open(audio_path, 'rb'))
    else:
        await update.message.reply_text(answer)

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ কনভার্সেশন বন্ধ করা হয়েছে।")
    return ConversationHandler.END

# Main
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
