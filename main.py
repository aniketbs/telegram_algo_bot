import os
import logging
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler
import openai

# ----------------- Configuration -----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", 9))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", 0))

if not TELEGRAM_TOKEN:
    raise RuntimeError("Set TELEGRAM_TOKEN env var.")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY env var.")

openai.api_key = OPENAI_API_KEY

# ----------------- Logging -----------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------- Bot Handlers -----------------
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Hello! I'm your OpenAI-powered Telegram bot. Send me any message, and I'll reply!"
    )

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Send any text message and I will respond using OpenAI GPT model."
    )

def handle_message(update: Update, context: CallbackContext):
    user_text = update.message.text
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_text}
            ]
        )
        reply_text = response['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        reply_text = "Sorry, I couldn't process that."
    
    update.message.reply_text(reply_text)

# ----------------- Daily Message -----------------
def send_daily_message(context: CallbackContext):
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")  # Put your chat ID here
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID not set. Skipping daily message.")
        return
    try:
        context.bot.send_message(chat_id=chat_id, text="Good morning! Here's your daily message.")
    except Exception as e:
        logger.error(f"Failed to send daily message: {e}")

# ----------------- Main -----------------
def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # Start the bot
    updater.start_polling()
    logger.info("Bot started!")

    # Schedule daily message
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_daily_message,
        trigger="cron",
        hour=DAILY_HOUR,
        minute=DAILY_MINUTE,
