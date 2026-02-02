import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import io
import sys
import json

from telegram import Bot

BOT_TOKEN = "8277622547:AAEzSwX7XcpAStzpSWW3lyQY9flvxvx7ZEU"

def run_trading_strategy():
    """Returns string output with BUY/SELL/NO ENTRY"""
    buffer = io.StringIO()
    sys.stdout = buffer

    ticker = "^NSEI"

    try:
        data = yf.download(ticker, period="3mo", interval="1d", progress=False)
        data.dropna(inplace=True)
    except:
        print("Error fetching data")
        sys.stdout = sys.__stdout__
        return "Error fetching data"

    k_period = 14
    d_period = 3
    data['Low_14'] = data['Low'].rolling(k_period).min()
    data['High_14'] = data['High'].rolling(k_period).max()
    data['%K'] = 100 * ((data['Close'] - data['Low_14']) / (data['High_14'] - data['Low_14']))
    data['%D'] = data['%K'].rolling(d_period).mean()

    current_stoch = data['%K'].iloc[-1]
    previous_stoch = data['%K'].iloc[-2]
    current_price = data['Close'].iloc[-1]

    # Renko
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
        sys.stdout = sys.__stdout__
        return "Not enough Renko movement"

    last_3 = bricks[-3:]
    three_green = all(b == 1 for b in last_3)
    three_red = all(b == -1 for b in last_3)

    stoch_cross_above_20 = previous_stoch <= 20 and current_stoch > 20
    stoch_cross_below_80 = previous_stoch >= 80 and current_stoch < 80

    is_buy = three_green and (stoch_cross_above_20 or (20 < current_stoch < 40))
    is_sell = three_red and (stoch_cross_below_80 or (60 < current_stoch < 80))

    if is_buy:
        strike = round((current_price + 300) / 50) * 50
        print(f"📈 BUY CALL {strike} CE")
    elif is_sell:
        strike = round((current_price - 300) / 50) * 50
        print(f"📉 BUY PUT {strike} PE")
    else:
        print("❌ NO ENTRY")

    sys.stdout = sys.__stdout__
    return buffer.getvalue().strip()

# ---------------- Vercel handler ---------------- #
def handler(request):
    """
    Vercel calls this when Telegram sends /run
    """
    try:
        body = json.loads(request['body']) if request['body'] else {}
        message_text = body.get("message", {}).get("text", "")
        chat_id = body.get("message", {}).get("chat", {}).get("id", None)

        bot = Bot(token=BOT_TOKEN)

        if message_text == "/run" and chat_id:
            result = run_trading_strategy()
            bot.send_message(chat_id=chat_id, text=result)

        return {"statusCode": 200, "body": "OK"}
    except Exception as e:
        print(e)
        return {"statusCode": 500, "body": str(e)}
