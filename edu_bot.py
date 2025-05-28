from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
import os
import speech_recognition as sr
from pydub import AudioSegment
import requests
from gtts import gTTS

# --- API KEYS ---
TELEGRAM_TOKEN = "7747635890:AAGD7O6k5Gz9dgxQnqxf7_Zm1dmz42CWNvg"
SARVAM_API_KEY = "sk_bvi6tcvb_gHrVVU0JHdVUqstqBsVSr4R7"
SARVAM_SUBSCRIPTION_KEY = "7c6e940a-9bf9-4f7b-a914-8793378fd1b8"

# --- FOLDER SETUP ---
os.makedirs("voice_notes", exist_ok=True)

# --- STATES ---
ASK_REPLY_TYPE = 1

# --- GLOBAL STATE ---
last_question = {}

# --- Sarvam Answer Function ---
def ask_sarvam_bengali(prompt):
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json",
        "X-Subscription-Key": SARVAM_SUBSCRIPTION_KEY,
    }
    data = {
        "model": "sarvam-m",
        "messages": [
            {"role": "system", "content": "তুমি একজন বন্ধুবৎসল শিক্ষক, তুমি বাংলা ভাষায় উত্তর দেবে।"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        print(f"[Sarvam API] {response.status_code}: {response.text}")
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return "⚠️ সার্ভার থেকে উত্তর পাওয়া যায়নি।"
    except Exception as e:
        return f"❌ ত্রুটি হয়েছে: {e}"

# --- Bengali TTS ---
def text_to_bengali_voice(text, filename="bengali_reply.mp3"):
    tts = gTTS(text=text, lang="bn")
    tts.save(filename)
    return filename

# --- Start Command ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হ্যালো! প্রশ্ন করুন এবং জানিয়ে দিন কীভাবে উত্তর পেতে চান!")

# --- Handle Text Question ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    question = update.message.text
    last_question[user_id] = question

    reply_keyboard = [["🎧 Voice", "✍️ Text", "🔁 Both"]]
    await update.message.reply_text(
        "আপনি কীভাবে উত্তর পেতে চান?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return ASK_REPLY_TYPE

# --- Handle Voice Question ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    file_id = update.message.voice.file_id
    ogg_path = f"voice_notes/{file_id}.ogg"
    wav_path = ogg_path.replace(".ogg", ".wav")

    try:
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(ogg_path)
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="bn-BD")

        last_question[user_id] = text
        await update.message.reply_text(f"🎙️ আপনি বললেন: {text}")

        reply_keyboard = [["🎧 Voice", "✍️ Text", "🔁 Both"]]
        await update.message.reply_text(
            "আপনি কীভাবে উত্তর পেতে চান?",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
        )
        return ASK_REPLY_TYPE

    except sr.UnknownValueError:
        await update.message.reply_text("😕 আপনার ভয়েস বোঝা যায়নি।")
    except Exception as e:
        await update.message.reply_text(f"❌ ত্রুটি: {str(e)}")
    finally:
        if os.path.exists(ogg_path): os.remove(ogg_path)
        if os.path.exists(wav_path): os.remove(wav_path)

# --- Handle Reply Type Selection ---
async def handle_reply_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    reply_type = update.message.text
    question = last_question.get(user_id)

    if not question:
        await update.message.reply_text("❗ প্রশ্ন পাওয়া যায়নি। আবার চেষ্টা করুন।")
        return ConversationHandler.END

    answer = ask_sarvam_bengali(question)

    if reply_type == "✍️ Text":
        await update.message.reply_text(f"প্রশ্ন: {question}\n\nউত্তর: {answer}")
    elif reply_type == "🎧 Voice":
        voice_path = text_to_bengali_voice(answer, "bengali_voice.mp3")
        with open(voice_path, "rb") as audio_file:
            await update.message.reply_voice(voice=audio_file)
        os.remove(voice_path)
    elif reply_type == "🔁 Both":
        await update.message.reply_text(f"প্রশ্ন: {question}\n\nউত্তর: {answer}")
        voice_path = text_to_bengali_voice(answer, "bengali_voice.mp3")
        with open(voice_path, "rb") as audio_file:
            await update.message.reply_voice(voice=audio_file)
        os.remove(voice_path)
    else:
        await update.message.reply_text("⚠️ অনুগ্রহ করে সঠিক অপশন দিন।")

    return ConversationHandler.END

# --- Main Bot Setup ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
            MessageHandler(filters.VOICE, handle_voice)
        ],
        states={
            ASK_REPLY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_type)]
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
