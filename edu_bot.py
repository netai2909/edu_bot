import os
import uuid
import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from gtts import gTTS
from pydub import AudioSegment
import speech_recognition as sr

# Environment variables (set in Railway dashboard)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
SARVAM_SUBSCRIPTION_KEY = os.environ.get("SARVAM_SUBSCRIPTION_KEY")
RAILWAY_STATIC_URL = os.environ.get("RAILWAY_STATIC_URL")

SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"
PROCESS_QUESTION = 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Ask a question (voice or text). I'll reply in Bengali or English based on your preference.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🧹 Language preference reset. Please ask your question again.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["last_question"] = update.message.text

    if "language" in context.user_data:
        return await process_reply_choice(update, context)

    reply_markup = ReplyKeyboardMarkup([["Bengali", "English"]], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("🗣️ In which language should I reply?", reply_markup=reply_markup)
    return PROCESS_QUESTION

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice_file = await update.message.voice.get_file()
    ogg_path = f"voice_{uuid.uuid4()}.ogg"
    wav_path = ogg_path.replace(".ogg", ".wav")
    await voice_file.download_to_drive(ogg_path)

    audio = AudioSegment.from_file(ogg_path)
    audio.export(wav_path, format="wav")

    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio_data)
            context.user_data["last_question"] = text

            if "language" in context.user_data:
                return await process_reply_choice(update, context)

            reply_markup = ReplyKeyboardMarkup([["Bengali", "English"]], one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text(f"✅ You said: {text}\n🗣️ In which language should I reply?", reply_markup=reply_markup)
            return PROCESS_QUESTION
        except:
            await update.message.reply_text("❌ Sorry, I couldn't recognize the voice.")
            return ConversationHandler.END

async def process_reply_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip().lower()

    # Set language only if it's not already remembered
    if user_input in ["bengali", "english"]:
        context.user_data["language"] = user_input

    language = context.user_data.get("language", "english")
    question = context.user_data.get("last_question", "")

    if language == "bengali":
        headers = {
            "Authorization": f"Bearer {SARVAM_API_KEY}",
            "subscription-key": SARVAM_SUBSCRIPTION_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "model": "sarvam-m",
            "messages": [
                {"role": "system", "content": "You are a helpful teacher for class 9-10, replying in Bengali."},
                {"role": "user", "content": question}
            ]
        }

        res = requests.post(SARVAM_API_URL, headers=headers, json=payload)
        if res.status_code == 200:
            answer = res.json()["choices"][0]["message"]["content"]
            await update.message.reply_text(f"📘 {answer}")

            tts = gTTS(answer, lang='bn')
            audio_path = f"bengali_reply_{uuid.uuid4()}.mp3"
            tts.save(audio_path)
            await update.message.reply_voice(voice=open(audio_path, 'rb'))
        else:
            await update.message.reply_text("⚠️ Bengali answer failed. Check Sarvam API keys or credits.")
    else:
        answer = "✅ This is a placeholder English answer. You can add GPT support for detailed English responses."
        await update.message.reply_text(f"📘 {answer}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
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
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(conv_handler)

    print("🚀 Bot running on Railway (Webhook mode)...")

    port = int(os.environ.get('PORT', 8080))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url="edubot-production-9618.up.railway.app"
    )
