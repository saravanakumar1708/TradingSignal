import os
import json
from datetime import datetime

import yfinance as yf
import pandas as pd
from supabase import create_client
from telegram import Bot, Update

# =========================
# ENV VARIABLES
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

bot = Bot(token=BOT_TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "last_signal"

# =========================
# STRATEGY
# =========================
def run_trading_strategy():
    data = yf.download("^NSEI", period="3mo", interval="1d", progress=False)

    if len(data) < 20:
        return "Not enough data", None

    data["Low_14"] = data["Low"].rolling(14).min()
    data["High_14"] = data["High"].rolling(14).max()
    data["%K"] = 100 * ((data["Close"] - data["Low_14"]) / (data["High_14"] - data["Low_14"]))

    current = data["%K"].iloc[-1]
    previous = data["%K"].iloc[-2]
    price = data["Close"].iloc[-1]

    signal = "NO ENTRY"

    if previous <= 20 and current > 20:
        signal = "BUY CALL"
    elif previous >= 80 and current < 80:
        signal = "BUY PUT"

    output = (
        f"Date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"Nifty: {price:.2f}\n"
        f"Stoch: {current:.2f}\n"
        f"Signal: {signal}"
    )

    return output, signal

# =========================
# VERCEL WEBHOOK HANDLER
# =========================
def handler(request):
    if request.method != "POST":
        return {"statusCode": 200, "body": "OK"}

    update = Update.de_json(json.loads(request.body), bot)

    if not update.message or not update.message.text:
        return {"statusCode": 200, "body": "Ignored"}

    if update.message.text == "/run":
        output, signal = run_trading_strategy()

        # Reply to user
        bot.send_message(chat_id=update.message.chat_id, text=output)

        # Get last signal
        res = supabase.table(TABLE_NAME).select("signal").order("id", desc=True).limit(1).execute()
        last_signal = res.data[0]["signal"] if res.data else None

        # Send alert only on change
        if signal != last_signal:
            bot.send_message(chat_id=CHAT_ID, text=f"⚡ SIGNAL CHANGED\n{output}")
            supabase.table(TABLE_NAME).insert({"signal": signal}).execute()

    return {"statusCode": 200, "body": "OK"}
