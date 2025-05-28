import os
import logging
import tempfile
import asyncio
import speech_recognition as sr
from gtts import gTTS
from pydub import AudioSegment
from telegram import Update, InputFile, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import httpx

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
SARVAM_KEY = os.getenv("SARVAM_KEY")
SARVAM_SUBSCRIPTION = os.getenv("SARVAM_SUBSCRIPTION")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Language context
user_language = {}

# Helper: Detect voice and return text
def recognize_voice(file_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio = recognizer.record(source)
    try:
        return recognizer.recognize_google(audio, language='bn-BD')
    except sr.UnknownValueError:
        return "Could not understand audio."

# Helper: Generate voice from text
def generate_voice(text, lang):
    tts = gTTS(text=text, lang='bn' if lang == 'Bengali' else 'en')
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        tts.save(tmp.name)
        return tmp.name

# Sarvam API for Bengali answers
async def ask_sarvam(prompt):
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {SARVAM_KEY}",
        "Subscription-Key": SARVAM_SUBSCRIPTION,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sarvam-m",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        return "Sorry, could not get a response."

# Dummy English chatbot
async def ask_english_bot(prompt):
    return f"[Dummy English Answer]: {prompt}"

# Ask language preference
def get_language_keyboard():
    return ReplyKeyboardMarkup([["English", "Bengali"]], one_time_keyboard=True, resize_keyboard=True)

# Ask for voice reply
def get_voice_keyboard():
    return ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Please select your preferred language:", reply_markup=get_language_keyboard())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # Handle language choice
    if text in ["English", "Bengali"]:
        user_language[uid] = text
        await update.message.reply_text("Please ask your question (text or voice).")
        return

    # Handle voice reply choice
    if text in ["Yes", "No"] and 'last_answer' in context.chat_data:
        if text == "Yes":
            voice_path = generate_voice(context.chat_data['last_answer'], user_language[uid])
            await update.message.reply_voice(voice=open(voice_path, 'rb'))
        await update.message.reply_text("What language do you want to continue with?", reply_markup=get_language_keyboard())
        return

    # Handle question
    lang = user_language.get(uid, "English")
    if lang == "Bengali":
        response = await ask_sarvam(text)
    else:
        response = await ask_english_bot(text)
    context.chat_data['last_answer'] = response
    await update.message.reply_text(response)
    await update.message.reply_text("Do you want voice output?", reply_markup=get_voice_keyboard())

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    voice_file = await update.message.voice.get_file()
    file_path = tempfile.mktemp(suffix=".ogg")
    await voice_file.download_to_drive(file_path)
    mp3_path = file_path.replace(".ogg", ".mp3")
    AudioSegment.from_ogg(file_path).export(mp3_path, format="mp3")
    text = recognize_voice(mp3_path)
    update.message.text = text
    await handle_text(update, context)

# Webhook setup
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers here (CommandHandler, MessageHandler, etc.)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))

    # Webhook setup (no webhook_path)
    PORT = int(os.environ.get("PORT", 8080))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Set this in Railway as env var

    await app.bot.delete_webhook()
    await app.bot.set_webhook(url=WEBHOOK_URL)

    # Run webhook
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="",
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
