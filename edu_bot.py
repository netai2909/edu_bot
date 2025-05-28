import os
import logging
import asyncio
from gtts import gTTS
import speech_recognition as sr
import httpx

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Your deployed app URL, e.g. https://app.up.railway.app
PORT = int(os.getenv("PORT", "8080"))

# Gemini API config - put your Gemini API key here
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Sarvam API config - put your Sarvam API key here
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

LANG_CHOICE, ASK_QUESTION, ASK_VOICE = range(3)

lang_keyboard = ReplyKeyboardMarkup(
    [["English", "Bengali"]], one_time_keyboard=True, resize_keyboard=True
)

voice_keyboard = ReplyKeyboardMarkup(
    [["Yes", "No"]], one_time_keyboard=True, resize_keyboard=True
)

user_data_store = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_store[user_id] = {
        "language": None,
        "awaiting_voice_answer": False,
        "last_answer": None,
    }
    await update.message.reply_text(
        "Welcome! Please choose your language / ভাষা নির্বাচন করুন:", reply_markup=lang_keyboard
    )
    return LANG_CHOICE


async def language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.lower()

    if text not in ["english", "bengali"]:
        await update.message.reply_text(
            "Please select 'English' or 'Bengali' / অনুগ্রহ করে 'English' অথবা 'Bengali' নির্বাচন করুন:",
            reply_markup=lang_keyboard,
        )
        return LANG_CHOICE

    user_data_store[user_id]["language"] = text
    user_data_store[user_id]["awaiting_voice_answer"] = False
    await update.message.reply_text(
        f"You selected {text.capitalize()}. Now ask your question.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_QUESTION


async def recognize_speech(file_path, lang_code):
    r = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio = r.record(source)
    try:
        text = r.recognize_google(audio, language=lang_code)
        return text
    except Exception as e:
        logger.error(f"Speech recognition failed: {e}")
        return None


async def get_gemini_response(question):
    # Google Gemini API v1 example (adjust if your API differs)
    # See: https://developers.generativeai.google/api/rest/generativelanguage/models/generateText
    if not GEMINI_API_KEY:
        return "Gemini API key is not set."

    url = "https://generativelanguage.googleapis.com/v1beta2/models/text-bison-001:generateText"
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    json_data = {
        "prompt": {
            "text": question
        },
        "temperature": 0.7,
        "candidateCount": 1,
        "maxOutputTokens": 300,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, params=params, headers=headers, json=json_data, timeout=20)
            response.raise_for_status()
            resp_json = response.json()
            candidates = resp_json.get("candidates")
            if candidates and len(candidates) > 0:
                return candidates[0].get("output", "Sorry, no answer from Gemini.")
            return "Sorry, no answer from Gemini."
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return "Sorry, I could not process your question with Gemini."


async def get_sarvam_response(question):
    # Sarvam LLM API example
    if not SARVAM_API_KEY:
        return "Sarvam API key is not set."

    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "bengali-gpt",
        "messages": [{"role": "user", "content": question}],
        "max_tokens": 300,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            # Adjust based on Sarvam response format:
            choices = data.get("choices")
            if choices and len(choices) > 0:
                return choices[0].get("message", {}).get("content", "No answer from Sarvam.")
            return "No answer from Sarvam."
        except Exception as e:
            logger.error(f"Sarvam API error: {e}")
            return "Sorry, I could not process your question with Sarvam."


async def text_to_speech(text, lang_code):
    try:
        tts = gTTS(text=text, lang=lang_code)
        filename = f"tts_{asyncio.current_task().get_name()}.mp3"
        tts.save(filename)
        return filename
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return None


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = user_data_store.get(user_id)

    if not user_data or not user_data.get("language"):
        await update.message.reply_text(
            "Please select language first using /start command.", reply_markup=lang_keyboard
        )
        return LANG_CHOICE

    language = user_data["language"]

    user_text = None
    if update.message.voice:
        voice_file = await update.message.voice.get_file()
        file_path = f"voice_{user_id}.ogg"
        await voice_file.download_to_drive(file_path)
        lang_code = "en-US" if language == "english" else "bn-BD"
        recognized_text = await recognize_speech(file_path, lang_code)
        if recognized_text:
            user_text = recognized_text
        else:
            await update.message.reply_text(
                "Sorry, I couldn't understand your voice. Please try again."
            )
            return ASK_QUESTION
    else:
        user_text = update.message.text

    if not user_text:
        await update.message.reply_text("Please send your question as text or voice.")
        return ASK_QUESTION

    if language == "english":
        bot_response = await get_gemini_response(user_text)
        tts_lang = "en"
    else:
        bot_response = await get_sarvam_response(user_text)
        tts_lang = "bn"

    user_data_store[user_id]["last_answer"] = bot_response
    user_data_store[user_id]["awaiting_voice_answer"] = True

    await update.message.reply_text(bot_response)
    await update.message.reply_text(
        "Do you want me to send the answer as voice? (Yes/No)", reply_markup=voice_keyboard
    )
    return ASK_VOICE


async def handle_voice_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = user_data_store.get(user_id)

    if not user_data or not user_data.get("awaiting_voice_answer"):
        await update.message.reply_text(
            "Please ask a question first."
        )
        return ASK_QUESTION

    text = update.message.text.lower()
    if text not in ["yes", "no"]:
        await update.message.reply_text(
            "Please answer 'Yes' or 'No'.", reply_markup=voice_keyboard
        )
        return ASK_VOICE

    if text == "yes":
        last_answer = user_data.get("last_answer")
        language = user_data.get("language")
        tts_lang = "en" if language == "english" else "bn"

        audio_file = await text_to_speech(last_answer, tts_lang)
        if audio_file:
            await update.message.reply_voice(voice=open(audio_file, "rb"))
            os.remove(audio_file)
        else:
            await update.message.reply_text("Sorry, failed to generate voice.")

    user_data_store[user_id]["awaiting_voice_answer"] = False
    await update.message.reply_text(
        "Please choose language for next question / অনুগ্রহ করে পরবর্তী প্রশ্নের জন্য ভাষা নির্বাচন করুন:",
        reply_markup=lang_keyboard,
    )
    return LANG_CHOICE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_store.pop(user_id, None)
    await update.message.reply_text(
        "Bye! To start again, send /start.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG_CHOICE: [MessageHandler(filters.Regex("^(English|Bengali)$"), language_choice)],
            ASK_QUESTION: [MessageHandler(filters.VOICE | filters.TEXT & ~filters.COMMAND, handle_question)],
            ASK_VOICE: [MessageHandler(filters.Regex("^(Yes|No|yes|no)$"), handle_voice_choice)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    logger.info(f"Setting webhook: {WEBHOOK_URL}{WEBHOOK_PATH}")
    await app.delete_webhook()
    await app.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)

    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_path=WEBHOOK_PATH,
    )


if __name__ == "__main__":
    asyncio.run(main())


