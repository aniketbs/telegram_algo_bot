#!/usr/bin/env python3
"""
Telegram + ChatGPT Trainer for algorithm practice
Compatible with python-telegram-bot v13.15 and Python 3.8+
"""

import os
import logging
import json
import random
from apscheduler.schedulers.background import BackgroundScheduler
import openai
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ---------- Config ----------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "9"))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", "0"))

if not TELEGRAM_TOKEN:
    raise RuntimeError("Set TELEGRAM_TOKEN env var.")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY env var.")

openai.api_key = OPENAI_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- In-memory storage ----------
registered_chats = set()
current_question = {}  # chat_id -> problem

# ---------- Problem bank ----------
PROBLEMS = [
    {"id":"kadane_1", "alg":"kadane", "prompt":"Find the maximum subarray sum.", "input":[2,3,-8,7,-1,2,3]},
    {"id":"kadane_2", "alg":"kadane", "prompt":"Find the maximum subarray sum.", "input":[1,-2,3,5,-1,2]},
    {"id":"moore_1",  "alg":"moore",  "prompt":"Find the majority element (> n/2).", "input":[2,2,1,1,1,2,2]},
    {"id":"moore_2",  "alg":"moore",  "prompt":"Find the majority element (> n/2).", "input":[3,3,4,2,4,4,2,4,4]},
    {"id":"longcon_1","alg":"longcon","prompt":"Find length of longest consecutive sequence.", "input":[100,4,200,1,3,2]},
    {"id":"xor_1",    "alg":"prefix_xor","prompt":"Count subarrays with XOR == target. target=6", "input":[4,2,2,6,4], "target":6},
]

# ---------- Deterministic verifiers ----------
def kadane_max(arr):
    if not arr: return 0
    max_ending = max_so_far = arr[0]
    for x in arr[1:]:
        max_ending = max(x, max_ending + x)
        max_so_far = max(max_so_far, max_ending)
    return max_so_far

def moore_majority(arr):
    cand, cnt = None, 0
    for x in arr:
        if cnt == 0:
            cand, cnt = x, 1
        elif x == cand:
            cnt += 1
        else:
            cnt -= 1
    if cand is not None and arr.count(cand) > len(arr)//2:
        return cand
    return None

def longest_consecutive_len(nums):
    s = set(nums)
    best = 0
    for n in s:
        if n-1 not in s:
            cur = n
            length = 1
            while cur+1 in s:
                cur += 1
                length += 1
            best = max(best, length)
    return best

def count_subarrays_xor(arr, target):
    freq = {0:1}
    xr = 0
    count = 0
    for x in arr:
        xr ^= x
        needed = xr ^ target
        count += freq.get(needed, 0)
        freq[xr] = freq.get(xr,0) + 1
    return count

def compute_expected(problem):
    alg = problem['alg']
    if alg == "kadane": return kadane_max(problem['input'])
    if alg == "moore": return moore_majority(problem['input'])
    if alg == "longcon": return longest_consecutive_len(problem['input'])
    if alg == "prefix_xor": return count_subarrays_xor(problem['input'], problem.get('target'))
    return None

# ---------- ChatGPT evaluator ----------
def ask_chatgpt_evaluate(problem, user_approach, user_answer, expected):
    system_prompt = (
        "You are an expert algorithms tutor. "
        "Judge the student's one-line approach for the problem. "
        "Return ONLY JSON: keys: approach_ok (true/false), feedback (short), detailed (optional)."
    )
    
    user_prompt = (
        f"Problem: {problem['prompt']}\n"
        f"Input: {problem['input']}\n"
        + (f"Target: {problem.get('target')}\n" if 'target' in problem else "")
        + f"Expected: {expected}\n"
        + f"Student answer: {user_answer}\n"
        + f"Approach: {user_approach}"
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":user_prompt}
            ],
            max_tokens=400, 
            temperature=0
        )
        text = resp["choices"][0]["message"]["content"].strip()
        import re
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        json_text = m.group(1) if m else text
        return json.loads(json_text)
    except Exception as e:
        logger.exception("ChatGPT evaluation failed: %s", e)
        return {"approach_ok": False, "feedback": "OpenAI error", "detailed": ""}

# ---------- Telegram helpers ----------
def make_question_text(problem):
    txt = f"*Algorithm:* `{problem['alg']}`\n*Prompt:* {problem['prompt']}\n"
    txt += f"*Input:* `{problem['input']}`\n"
    if 'target' in problem:
        txt += f"*Target:* `{problem['target']}`\n"
    txt += "\nReply with numeric answer (line1) and optional one-line approach (line2).\nExample:\n`11\nKadane: keep current & max sum`"
    return txt

def pick_random_problem():
    return random.choice(PROBLEMS)

def send_question(chat_id, context: CallbackContext):
    problem = pick_random_problem()
    current_question[chat_id] = problem
    context.bot.send_message(chat_id=chat_id, text=make_question_text(problem), parse_mode=ParseMode.MARKDOWN)

# ---------- Command handlers ----------
def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    registered_chats.add(chat_id)
    update.message.reply_text("Registered! Use /next for a question, /stop to unregister, /explain for explanation.")
    send_question(chat_id, context)

def stop(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    registered_chats.discard(chat_id)
    update.message.reply_text("Unregistered. Send /start to register again.")

def next_cmd(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    registered_chats.add(chat_id)
    send_question(chat_id, context)

def explain(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    problem = current_question.get(chat_id)
    if not problem:
        update.message.reply_text("No active question. Use /next.")
        return
    expected = compute_expected(problem)
    expl = f"Explanation (expected result = {expected}) for algorithm `{problem['alg']}`."
    update.message.reply_text(expl)

def handle_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    problem = current_question.get(chat_id)
    if not problem:
        update.message.reply_text("No active question. Use /next.")
        return
    lines = [l for l in text.splitlines() if l.strip()]
    answer_line = lines[0].strip() if lines else ""
    approach_line = lines[1].strip() if len(lines) > 1 else ""
    parsed_number = None
    try:
        parsed_number = int(answer_line.split()[0])
    except:
        import re
        m = re.search(r"-?\d+", answer_line)
        if m: parsed_number = int(m.group())
    expected = compute_expected(problem)
    numeric_ok = (parsed_number == expected) if expected is not None else (parsed_number is None)
    cgpt_eval = ask_chatgpt_evaluate(problem, approach_line or "<no approach>", parsed_number, expected)
    reply_lines = []
    reply_lines.append("✅ Numeric answer correct." if numeric_ok else f"❌ Numeric incorrect (expected: {expected}).")
    approach_ok = cgpt_eval.get("approach_ok", False)
    feedback = cgpt_eval.get("feedback", "")
    detailed = cgpt_eval.get("detailed", "")
    if approach_ok:
        reply_lines.append("💡 Approach looks good. " + feedback)
    else:
        reply_lines.append("💡 Approach missing key ideas. " + feedback)
    if detailed:
        reply_lines.append("\nExplanation:\n" + detailed)
    reply_lines.append("\nSend /explain for deterministic explanation or /next for another problem.")
    update.message.reply_text("\n".join(reply_lines))

# ---------- Scheduler ----------
scheduler = BackgroundScheduler()

def daily_job(context: CallbackContext = None):
    for chat_id in list(registered_chats):
        try:
            send_question(chat_id, bot_updater.dispatcher)
        except Exception as e:
            logger.exception("Failed to send to %s: %s", chat_id, e)

# ---------- Main ----------
def main():
    global bot_updater
    bot_updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = bot_updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop))
    dp.add_handler(CommandHandler("next", next_cmd))
    dp.add_handler(CommandHandler("explain", explain))
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    scheduler.add_job(lambda: daily_job(bot_updater), 'cron', hour=DAILY_HOUR, minute=DAILY_MINUTE)
    scheduler.start()

    bot_updater.start_polling()
    logger.info("Bot started.")
    bot_updater.idle()

if __name__ == "__main__":
    main()
