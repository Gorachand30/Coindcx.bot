"""
gold_bot.py
Gold (GC=F) 30-Minute Trend Engine with Trailing SL & Telegram Alerts
Compatible with: Termux (Android), Linux, Windows, GitHub Actions
"""

import logging
import time
from datetime import datetime
import pandas as pd
import requests
import yfinance as yf

# --------------------------------------------------
# 1. Credentials & Configuration
# --------------------------------------------------
TELEGRAM_TOKEN = "8975800502:AAGkJttO42Vfp5kdenwDa_G7BaMwaz7qvyY"
TELEGRAM_CHAT_ID = "8832380997"

TICKER = "GC=F"  # Gold Futures on Yahoo Finance
INTERVAL = "30m"
SL_DISTANCE = 1.6
SPREAD_COST = 0.08
INITIAL_CAPITAL_INR = 5000.0
USD_INR_RATE = 88.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

# --------------------------------------------------
# 2. Telegram Alert Dispatcher
# --------------------------------------------------


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        logging.error(f"Telegram error: {e}")


# --------------------------------------------------
# 3. Data & Indicator Calculation
# --------------------------------------------------


def fetch_gold_data():
    try:
        df = yf.download(
            TICKER, period="5d", interval=INTERVAL, progress=False
        )
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna().copy()
        df["EMA_Fast"] = df["Close"].ewm(span=12, adjust=False).mean()
        df["EMA_Slow"] = df["Close"].ewm(span=36, adjust=False).mean()
        return df
    except Exception as e:
        logging.error(f"Data fetch error: {e}")
        return None


# --------------------------------------------------
# 4. Main Automated Loop
# --------------------------------------------------


def main():
    position = 0  # 1: Long, -1: Short, 0: Flat
    entry_price = 0.0
    stop_loss = 0.0
    last_processed_candle = None

    startup_msg = (
        f"🤖 <b>Gold Cloud Bot Active</b>\n"
        f"Ticker: <code>{TICKER}</code>\n"
        f"Interval: <code>{INTERVAL}</code>\n"
        f"Trailing SL: <code>Active</code>\n"
        f"Environment: Mobile / Termux Compatible"
    )
    logging.info("Bot starting...")
    send_telegram(startup_msg)

    while True:
        try:
            df = fetch_gold_data()
            if df is None or len(df) < 2:
                time.sleep(30)
                continue

            # Latest closed candle check
            closed_bar = df.iloc[-2]
            candle_time = closed_bar.name
            current_bar = df.iloc[-1]
            cp = float(current_bar["Close"])
            fast_ema = float(closed_bar["EMA_Fast"])
            slow_ema = float(closed_bar["EMA_Slow"])

            # 1. Trailing Stop Loss Management
            if position == 1:
                if cp > entry_price + 1.5:
                    new_sl = max(stop_loss, fast_ema - 0.4)
                    if new_sl > stop_loss:
                        stop_loss = new_sl
                        send_telegram(
                            f"🛡️ <b>SL Trailed (BUY)</b>\nNew SL: {stop_loss:.2f}"
                        )

                # Stop loss hit
                if cp <= stop_loss:
                    pnl = (cp - entry_price - SPREAD_COST) * USD_INR_RATE
                    send_telegram(
                        f"🛑 <b>BUY SL Hit</b>\nExit: {cp:.2f}\nPnL: ₹{pnl:.2f}"
                    )
                    position = 0

            elif position == -1:
                if cp < entry_price - 1.5:
                    new_sl = min(stop_loss, fast_ema + 0.4)
                    if new_sl < stop_loss:
                        stop_loss = new_sl
                        send_telegram(
                            f"🛡️ <b>SL Trailed (SELL)</b>\nNew SL: {stop_loss:.2f}"
                        )

                # Stop loss hit
                if cp >= stop_loss:
                    pnl = (entry_price - cp - SPREAD_COST) * USD_INR_RATE
                    send_telegram(
                        f"🛑 <b>SELL SL Hit</b>\nExit: {cp:.2f}\nPnL: ₹{pnl:.2f}"
                    )
                    position = 0

            # 2. New Candle Close Signal Evaluation
            if candle_time != last_processed_candle:
                last_processed_candle = candle_time

                close_price = float(closed_bar["Close"])
                signal = 0
                if (fast_ema > slow_ema) and (close_price > fast_ema):
                    signal = 1
                elif (fast_ema < slow_ema) and (close_price < fast_ema):
                    signal = -1

                logging.info(
                    f"Bar {candle_time} | Close: {close_price:.2f} | Signal: {signal}"
                )

                # Reverse Exit
                if (position == 1 and signal == -1) or (
                    position == -1 and signal == 1
                ):
                    pnl = (
                        (cp - entry_price)
                        if position == 1
  
