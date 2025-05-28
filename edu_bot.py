import os
import logging
import asyncio
from io import BytesIO

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
)

import speech_recognition as sr
from gtts import gTTS

import httpx

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

CHOOSING_LANG, WAITING_QUESTION, ASK_VOICE = range(3)

# Your environment variables (make sure to set these in Railway or locally)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PORT = int(os.getenv("PORT", "8080"))

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_SUBSCRIPTION_KEY = os.getenv("SARVAM_SUBSCRIPTION_KEY")  # If needed
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

lang_keyboard = [["English", "বাংলা"]]
lang_markup = ReplyKeyboardMarkup(lang_keyboard, one_time_keyboard=True, resize_keyboard=True)

yes_no_keyboard = [["Yes", "No"]]
yes_no_markup = ReplyKeyboardMarkup(yes_no_keyboard, one_time_keyboard=True, resize_keyboard=True)


def recognize_voice_english(file_path: str) -> str:
    r = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio = r.record(source)
    try:
        text = r.recognize_google(audio, language='en-US')
        logger.info(f"Recognized English text: {text}")
        return text
    except Exception as e:
        logger.error(f"English voice recognition error: {e}")
        return ""


def recognize_voice_bengali(file_path: str) -> str:
    r = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio = r.record(source)
    try:
        text = r.recognize_google(audio, language='bn-IN')
        logger.info(f"Recognized Bengali text: {text}")
        return text
    except Exception as e:
        logger.error(f"Bengali voice recognition error: {e}")
        return ""


async def get_english_response_gemini(prompt: str) -> str:
    url = "https://api.gemini.example.com/v1/chat"  # Replace with your real Gemini API endpoint
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    json_data = {"prompt": prompt, "max_tokens": 100}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, json=json_data, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("choices", [{}])[0].get("text", "Sorry, I couldn't get the answer.")
            return answer.strip()
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return "Sorry, I am unable to respond right now."


async def get_bengali_response_sarvam(prompt: str) -> str:
    url = "https://api.sarvam.ai/v1/generate"
    headers = {"Authorization": f"Bearer {SARVAM_API_KEY}"}
    json_data = {
        "prompt": prompt,
        "lang": "bn",
        "max_tokens": 100,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, json=json_data, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("text", "দুঃখিত, আমি উত্তর দিতে পারছি না।")
            return answer.strip()
        except Exception as e:
            logger.error(f"Sarvam API error: {e}")
            return "দুঃখিত, আমি এখন উত্তর দিতে পারছি না।"


def generate_tts_audio(text: str, lang_code: str = "en") -> BytesIO:
    tts = gTTS(text=text, lang=lang_code)
    audio_bytes = BytesIO()
    tts.write_to_fp(audio_bytes)
    audio_bytes.seek(0)
    return audio_bytes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Please select your language / ভাষা নির্বাচন করুন:",
        reply_markup=lang_markup,
    )
    return CHOOSING_LANG


async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = update.message.text
    if lang not in ["English", "বাংলা"]:
        await update.message.reply_text("Please select a valid language.", reply_markup=lang_markup)
        return CHOOSING_LANG

    context.user_data["language"] = lang
    await update.message.reply_text(f"You chose {lang}. Please send your question as text or voice.",
                                    reply_markup=ReplyKeyboardRemove())
    return WAITING_QUESTION


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("language", "English")
    user_message = ""

    if update.message.voice:
        voice = await update.message.voice.get_file()
        file_path = await voice.download_to_drive()
        if lang == "English":
            user_message = recognize_voice_english(file_path)
        else:
            user_message = recognize_voice_bengali(file_path)
    else:
        user_message = update.message.text

    if not user_message:
        await update.message.reply_text("Sorry, I could not understand your voice. Please try again.")
        return WAITING_QUESTION

    logger.info(f"User message in {lang}: {user_message}")

    if lang == "English":
        answer = await get_english_response_gemini(user_message)
        tts_lang = "en"
    else:
        answer = await get_bengali_response_sarvam(user_message)
        tts_lang = "bn"

    await update.message.reply_text(answer)

    context.user_data["last_answer"] = answer
    context.user_data["tts_lang"] = tts_lang

    await update.message.reply_text(
        "Do you want me to send voice answer? / আপনি কি ভয়েস আউটপুট চান?",
        reply_markup=yes_no_markup,
    )
    return ASK_VOICE


async def handle_voice_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if text == "yes":
        answer = context.user_data.get("last_answer", "")
        tts_lang = context.user_data.get("tts_lang", "en")
        audio_bytes = generate_tts_audio(answer, lang_code=tts_lang)
        await update.message.reply_voice(voice=audio_bytes)
    elif text != "no":
        await update.message.reply_text("Please answer Yes or No.", reply_markup=yes_no_markup)
        return ASK_VOICE

    await update.message.reply_text(
        "Please select language for next question / পরবর্তী প্রশ্নের জন্য ভাষা নির্বাচন করুন:",
        reply_markup=lang_markup,
    )
    return CHOOSING_LANG


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bye! To start again send /start.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_LANG: [MessageHandler(filters.TEXT & (~filters.COMMAND), choose_language)],
            WAITING_QUESTION: [MessageHandler((filters.TEXT | filters.VOICE) & (~filters.COMMAND), handle_question)],
            ASK_VOICE: [MessageHandler(filters.Regex("^(Yes|No|yes|no)$"), handle_voice_choice)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    logger.info(f"Setting webhook: https://{WEBHOOK_URL}{WEBHOOK_PATH}")
    await application.bot.set_webhook(f"https://{WEBHOOK_URL}{WEBHOOK_PATH}")

    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_path=WEBHOOK_PATH,
    )


if __name__ == "__main__":
    asyncio.run(main())


