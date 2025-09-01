#!/usr/bin/env python3
"""
Telegram + ChatGPT Trainer for algorithm practice
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
# ---------- End config ----------

if not TELEGRAM_TOKEN:
    raise RuntimeError("Set TELEGRAM_TOKEN env var.")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY env var.")

openai.api_key = OPENAI_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage
registered_chats = set()
current_question = {}  # chat_id -> problem

# Problem bank
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
        f"Problem: {problem['prompt']}\nInput: {problem['input']}\n"
        + (f"Target: {problem.get('target')}\n" if 'target' in problem else "")
        + f"Expected: {expected}\nStudent answer: {user_answer}\nApproach: {user_approach}"
