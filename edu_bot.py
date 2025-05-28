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

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://yourapp.up.railway.app
PORT = int(os.getenv("PORT", "8080"))

# States for conversation
LANG_CHOICE, ASK_QUESTION, ASK_VOICE = range(3)

# Languages keyboard
lang_keyboard = ReplyKeyboardMarkup(
    [["English", "Bengali"]], one_time_keyboard=True, resize_keyboard=True
)

# Voice answer keyboard
voice_keyboard = ReplyKeyboardMarkup(
    [["Yes", "No"]], one_time_keyboard=True, resize_keyboard=True
)

# In-memory user data store, for demo only
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


async def get_free_english_bot_response(question):
    # Free API example: "https://api.affiliateplus.xyz/api/chatbot?message=your_message"
    # If this breaks, replace with any other free chatbot API
    url = "https://api.affiliateplus.xyz/api/chatbot"
    params = {"message": question, "botname": "EduBot", "ownername": "You"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", "Sorry, I could not understand.")
        except Exception as e:
            logger.error(f"English bot API error: {e}")
            return "Sorry, I could not process your question right now."


async def get_bengali_bot_response(question):
    # Replace with your Sarvam LLM API or any Bengali chatbot API
    # For demo, echoing back question:
    return f"আপনি বললেন: {question}"


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

    # Handle voice or text input
    user_text = None
    if update.message.voice:
        # Download voice file
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

    # Get response from chatbot API
    if language == "english":
        bot_response = await get_free_english_bot_response(user_text)
        tts_lang = "en"
    else:
        bot_response = await get_bengali_bot_response(user_text)
        tts_lang = "bn"

    # Save last answer for possible TTS
    user_data_store[user_id]["last_answer"] = bot_response
    user_data_store[user_id]["awaiting_voice_answer"] = True

    # Send text answer first
    await update.message.reply_text(bot_response)

    # Ask if want voice output
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

    # Reset flag and ask for language again
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

    # Run webhook
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


