import os
import asyncio
from gtts import gTTS
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import speech_recognition as sr
import httpx

# === CONFIG ===
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
WEBHOOK_URL = "https://your-railway-app-url.com"  # Railway static URL with trailing slash
WEBHOOK_PATH = "/webhook"  # Path Telegram calls for updates, must match railway config

# === USER STATES ===
user_language = {}  # user_id: "english" or "bengali"
user_waiting_for_voice_choice = set()  # user_id waiting to say yes/no for voice reply

# === Helper Functions ===

def recognize_speech(file_path: str, lang_code: str) -> str:
    r = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio = r.record(source)
    try:
        if lang_code == "bengali":
            text = r.recognize_google(audio, language="bn-BD")
        else:
            text = r.recognize_google(audio, language="en-US")
        return text
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        print(f"Speech recognition error: {e}")
        return ""

async def get_english_response(prompt: str) -> str:
    # Using a free API for English chatbot response
    # This is an example using Huggingface Inference API (no API key needed for small demo)
    async with httpx.AsyncClient() as client:
        payload = {"inputs": prompt}
        try:
            resp = await client.post("https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium", json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "error" in data:
                    return "Sorry, I can't answer right now."
                # The response from DialoGPT is a list with 'generated_text' in first item
                if isinstance(data, list) and len(data) > 0 and "generated_text" in data[0]:
                    return data[0]["generated_text"]
                # fallback
                return str(data)
            else:
                return "Sorry, I'm having trouble understanding."
        except Exception as e:
            print("English chatbot API error:", e)
            return "Sorry, I'm having trouble answering."

def get_bengali_response(prompt: str) -> str:
    # Here you should call your Sarvam LLM API for Bengali chatbot (replace with your actual code)
    # Example dummy static reply:
    return "আপনার প্রশ্নটি বুঝতে পারলাম, আমি শীঘ্রই উত্তর দেব।"

async def send_voice(update: Update, text: str, lang_code: str):
    filename = f"voice_{update.effective_user.id}.mp3"
    try:
        tts = gTTS(text=text, lang="bn" if lang_code == "bengali" else "en")
        tts.save(filename)
        with open(filename, "rb") as f:
            await update.message.reply_voice(voice=f)
    finally:
        if os.path.exists(filename):
            os.remove(filename)

# === Telegram Bot Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Please select your language / অনুগ্রহ করে ভাষা নির্বাচন করুন:\nType 'English' or 'Bengali'."
    )

async def language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()

    if text in ["english", "bengali"]:
        user_language[user_id] = text
        await update.message.reply_text(
            f"Language set to {text.capitalize()}. Now, send me your question (voice or text)."
        )
    else:
        await update.message.reply_text("Please reply with 'English' or 'Bengali' to choose your language.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # If language not selected, force language choice first
    if user_id not in user_language:
        await update.message.reply_text("Please choose your language first: English or Bengali.")
        return

    if user_id in user_waiting_for_voice_choice:
        # Waiting for yes/no to send voice reply
        text = update.message.text.strip().lower()
        if text == "yes":
            # Send voice
            answer = context.user_data.get("last_answer", None)
            lang = user_language[user_id]
            if answer:
                await send_voice(update, answer, lang)
            else:
                await update.message.reply_text("Sorry, no answer to convert to voice.")
        elif text == "no":
            await update.message.reply_text("Okay, no voice reply.")
        else:
            await update.message.reply_text("Please reply with 'yes' or 'no'.")

        user_waiting_for_voice_choice.discard(user_id)
        await update.message.reply_text("Please choose language for your next question: English or Bengali.")
        user_language.pop(user_id, None)  # Force language choice again
        return

    lang = user_language[user_id]

    # Detect if voice message or text
    if update.message.voice:
        # Download voice file
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        ogg_path = f"voice_{user_id}.ogg"
        wav_path = f"voice_{user_id}.wav"
        await voice_file.download_to_drive(ogg_path)

        # Convert ogg to wav using ffmpeg (needs ffmpeg installed in environment)
        # Try system call, else skip recognition with error message
        try:
            import subprocess

            subprocess.run(
                ["ffmpeg", "-i", ogg_path, wav_path], capture_output=True, check=True
            )
        except Exception as e:
            print("ffmpeg conversion error:", e)
            await update.message.reply_text("Sorry, voice conversion failed.")
            os.remove(ogg_path)
            return

        # Recognize speech
        recognized_text = recognize_speech(wav_path, lang)
        os.remove(ogg_path)
        os.remove(wav_path)

        if recognized_text == "":
            await update.message.reply_text(
                "Sorry, I couldn't understand your voice clearly. Please try again."
            )
            return

        query = recognized_text
    else:
        query = update.message.text.strip()

    # Get answer
    if lang == "bengali":
        answer = get_bengali_response(query)
    else:
        answer = await get_english_response(query)

    context.user_data["last_answer"] = answer
    await update.message.reply_text(answer)

    # Ask if want voice
    user_waiting_for_voice_choice.add(user_id)
    await update.message.reply_text("Do you want the answer in voice? Reply 'yes' or 'no'.")

# === MAIN ===

async def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^(English|Bengali|english|bengali)$"), language_choice))
    app.add_handler(MessageHandler(filters.VOICE | filters.TEXT & ~filters.COMMAND, handle_message))

    # Webhook mode setup
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.bot.set_webhook(url=WEBHOOK_URL + WEBHOOK_PATH)
    print("Webhook set:", WEBHOOK_URL + WEBHOOK_PATH)

    # Run webhook server, listen on all interfaces and port 8080 (Railway default)
    await app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        webhook_path=WEBHOOK_PATH,
    )

if __name__ == "__main__":
    asyncio.run(main())

