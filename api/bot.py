import os
import io
import sys
from datetime import datetime

import yfinance as yf
import pandas as pd
import numpy as np
from supabase import create_client, Client

from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, ContextTypes

# ==================================================
# SUPABASE SETUP
# ==================================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TABLE_NAME = "last_signal"  # Table with columns: id (int), signal (text), created_at (timestamp)

# ==================================================
# TELEGRAM SETUP
# ==================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")  # Group or personal chat ID
bot = Bot(BOT_TOKEN)

# Dispatcher for processing Telegram updates
dispatcher = Dispatcher(bot, None, workers=0)

# ==================================================
# TRADING STRATEGY FUNCTION
# ==================================================
def run_trading_strategy():
    ticker = "^NSEI"

    try:
        data = yf.download(
            ticker, period="3mo", interval="1d", progress=False, auto_adjust=False
        )
    except Exception as e:
        return f"Error downloading data: {e}", None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if len(data) < 20:
        return "Not enough data fetched.", None

    data.dropna(inplace=True)

    # ---- STOCHASTICS (14,3,3)
    k_period = 14
    d_period = 3
    data['Low_14'] = data['Low'].rolling(k_period).min()
    data['High_14'] = data['High'].rolling(k_period).max()
    data['%K'] = 100 * ((data['Close'] - data['Low_14']) / (data['High_14'] - data['Low_14']))
    data['%D'] = data['%K'].rolling(d_period).mean()

    current_stoch = data['%K'].iloc[-1]
    previous_stoch = data['%K'].iloc[-2]
    current_price = data['Close'].iloc[-1]

    # ---- RENKO (Brick Size = 20)
    brick_size = 20
    bricks = []
    last_brick_price = data['Close'].iloc[0]

    for _, row in data.iterrows():
        diff = row['Close'] - last_brick_price
        if diff > 0:
            for _ in range(int(diff // brick_size)):
                bricks.append(1)
                last_brick_price += brick_size
        elif diff < 0:
            for _ in range(int(abs(diff) // brick_size)):
                bricks.append(-1)
                last_brick_price -= brick_size

    if len(bricks) < 3:
        return "Not enough Renko movement.", None

    last_3 = bricks[-3:]
    three_green = all(b == 1 for b in last_3)
    three_red = all(b == -1 for b in last_3)

    pattern = "Green, Green, Green" if three_green else "Red, Red, Red" if three_red else "Mixed/Choppy"

    # ---- SIGNAL LOGIC
    stoch_cross_above_20 = previous_stoch <= 20 and current_stoch > 20
    stoch_cross_below_80 = previous_stoch >= 80 and current_stoch < 80

    is_buy = three_green and (stoch_cross_above_20 or (20 < current_stoch < 40))
    is_sell = three_red and (stoch_cross_below_80 or (60 < current_stoch < 80))

    signal = "NO ENTRY"
    strike = None
    if is_buy:
        signal = "BUY CALL"
        strike = round((current_price + 300) / 50) * 50
    elif is_sell:
        signal = "BUY PUT"
        strike = round((current_price - 300) / 50) * 50

    output = (
        f"Date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"Nifty Price: {current_price:.2f}\n"
        f"Stoch: {current_stoch:.2f} (Prev: {previous_stoch:.2f})\n"
        f"Renko: {pattern}\n"
        f"Signal: {signal}"
    )
    if strike:
        output += f"\nStrike: {strike}"

    return output, signal

# ==================================================
# TELEGRAM COMMAND HANDLERS
# ==================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Trading Bot Active ✅\nUse /run to get current signal"
    )

async def run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        output, signal = run_trading_strategy()
    except Exception as e:
        output = f"Error: {e}"
        signal = None

    # Send response to user who called /run
    await update.message.reply_text(output)

    # Fetch last signal from Supabase
    last_signal_data = supabase.table(TABLE_NAME).select("signal").order("id", desc=True).limit(1).execute()
    last_signal = None
    if last_signal_data.data:
        last_signal = last_signal_data.data[0]["signal"]

    # Send alert if signal changed
    if signal and signal != last_signal:
        if CHAT_ID:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚡ New Signal: {signal}\n{output}")
        supabase.table(TABLE_NAME).insert({"signal": signal}).execute()

# Register handlers with dispatcher
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("run", run))

# ==================================================
# VERCEL SERVERLESS HANDLER
# ==================================================
async def handler(request):
    """Vercel serverless function entrypoint"""
    if request.method == "POST":
        json_data = await request.json()
        update = Update.de_json(json_data, bot)
        await dispatcher.process_update(update)
        return {"status": "ok"}
    else:
        return {"status": "error", "message": "Use POST request"}
