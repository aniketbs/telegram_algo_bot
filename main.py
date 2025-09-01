#!/usr/bin/env python3
import os
import logging
import random
import json
import re
from apscheduler.schedulers.background import BackgroundScheduler
import openai
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ---------- Config ----------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "9"))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", "0"))

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Set TELEGRAM_TOKEN and OPENAI_API_KEY env vars.")

openai.api_key = OPENAI_API_KEY
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Storage ----------
registered_chats = set()
current_question = {}  # chat_id -> problem

# ---------- Problems ----------
PROBLEMS = [
    {"id":"kadane_1", "alg":"kadane", "prompt":"Find the maximum subarray sum.", "input":[2,3,-8,7,-1,2,3]},
    {"id":"kadane_2", "alg":"kadane", "prompt":"Find the maximum subarray sum.", "input":[1,-2,3,5,-1,2]},
]

# ---------- Deterministic verifier ----------
def kadane_max(arr):
    max_ending = max_so_far = arr[0]
    for x in arr[1:]:
        max_ending = max(x, max_ending + x)
        max_so_far = max(max_so_far, max_ending)
    return max_so_far

def compute_expected(problem):
    if problem['alg'] == "kadane":
        return kadane_max(problem['input'])
    return None

# ---------- ChatGPT helper ----------
def ask_chatgpt_evaluate(problem, user_approach, user_answer, expected):
    system_prompt = "You are an expert algorithms tutor. Return ONLY JSON: approach_ok (true/false), feedback, detailed (optional)."
    user_prompt = (
        f"Problem: {problem['prompt']}\nInput: {problem['input']}\n"
        f"Expected result: {expected}\nStudent answer: {user_answer}\n"
        f"Student approach: {user_approach}"
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":user_prompt}
            ],
            max_tokens=300,
            temperature=0.0
        )
        text = resp["choices"][0]["message"]["content"].strip()
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        json_text = m.group(1) if m else text
        return json.loads(json_text)
    except Exception as e:
        logger.exception("ChatGPT evaluation failed: %s", e)
        return {"approach_ok": False, "feedback": "Could not evaluate approach.", "detailed": ""}

# ---------- Telegram helpers ----------
def pick_random_problem():
    return random.choice(PROBLEMS)

def send_question(chat_id, context: CallbackContext):
    problem = pick_random_problem()
    current_question[chat_id] = problem
    text = f"*Algorithm:* `{problem['alg']}`\n*Prompt:* {problem['prompt']}\n*Input:* `{problem['input']}`"
    context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)

# ---------- Command handlers ----------
def start(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    registered_chats.add(chat_id)
    update.message.reply_text("Registered! Use /next to get a question.")
    send_question(chat_id, context)

def next_cmd(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    send_question(chat_id, context)

def handle_message(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    problem = current_question.get(chat_id)
    if not problem:
        update.message.reply_text("No active question. Use /next.")
        return

    lines = [l for l in update.message.text.splitlines() if l.strip()]
    answer_line = lines[0].strip() if lines else ""
    approach_line = lines[1].strip() if len(lines) > 1 else ""
    
    try:
        parsed_number = int(re.search(r"-?\d+", answer_line).group())
    except Exception:
        parsed_number = None

    expected = compute_expected(problem)
    numeric_ok = (parsed_number == expected)
    cgpt_eval = ask_chatgpt_evaluate(problem, approach_line or "<no approach>", parsed_number, expected)

    reply_lines = []
    reply_lines.append("✅ Correct!" if numeric_ok else f"❌ Incorrect. Expected: {expected}")
    if cgpt_eval.get("approach_ok"):
        reply_lines.append("💡 Approach: Looks good. " + cgpt_eval.get("feedback",""))
    else:
        reply_lines.append("💡 Approach: Missing key ideas. " + cgpt_eval.get("feedback",""))
    if cgpt_eval.get("detailed"):
        reply_lines.append("\nExplanation:\n" + cgpt_eval.get("detailed",""))
    update.message.reply_text("\n".join(reply_lines))

# ---------- Scheduler ----------
scheduler = BackgroundScheduler()
def daily_job(context: CallbackContext):
    for chat_id in list(registered_chats):
        try:
            send_question(chat_id, context)
        except Exception as e:
            logger.exception("Failed to send to %s: %s", chat_id, e)

# ---------- Main ----------
def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("next", next_cmd))
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))
    
    scheduler.add_job(lambda: daily_job(updater.dispatcher), 'cron', hour=DAILY_HOUR, minute=DAILY_MINUTE)
    scheduler.start()

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
