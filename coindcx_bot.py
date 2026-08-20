import hashlib
import hmac
import json
import time
import numpy as np
import pandas as pd
import requests

TELEGRAM_BOT_TOKEN = "8975800502:AAGkJttO42Vfp5kdenwDa_G7BaMwaz7qvyY"
TELEGRAM_CHAT_ID = "8832380997"

COINDCX_API_KEY = "7d61f2026a877742fa383d46de018af964ff23cf3a97504d"
COINDCX_API_SECRET = (
    "752ae196ccd6e5e71bfb57b08d48ab33a207cd6bbbb5211ebe25a0bbc5617967"
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
LEVERAGE = 3
TRADE_AMOUNT_USDT = 50.0


def send_telegram(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {
      "chat_id": TELEGRAM_CHAT_ID,
      "text": message,
      "parse_mode": "Markdown",
  }
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Telegram Alert Error: {e}")


def place_coindcx_futures_order(pair, side, price, sl, tp):
  url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
  base_asset = pair.replace("USDT", "")
  coindcx_pair = f"B-{base_asset}_USDT"

  quantity = round((TRADE_AMOUNT_USDT * LEVERAGE) / price, 4)
  if base_asset == "BTC":
    quantity = round((TRADE_AMOUNT_USDT * LEVERAGE) / price, 3)

  timestamp = int(round(time.time() * 1000))

  body = {
      "timestamp": timestamp,
      "order": {
          "side": "buy" if side == "BUY" else "sell",
          "pair": coindcx_pair,
          "order_type": "market_order",
          "total_quantity": quantity,
          "leverage": LEVERAGE,
          "notification": "no_notification",
          "time_in_force": "ioc",
      },
  }

  json_body = json.dumps(body, separators=(",", ":"))
  signature = hmac.new(
      COINDCX_API_SECRET.encode(), json_body.encode(), hashlib.sha256
  ).hexdigest()

  headers = {
      "Content-Type": "application/json",
      "X-AUTH-APIKEY": COINDCX_API_KEY,
      "X-AUTH-SIGNATURE": signature,
  }

  try:
    response = requests.post(url, data=json_body, headers=headers, timeout=10)
    res_data = response.json()

    if response.status_code == 200:
      msg = (
          f"⚡ *[AUTO-TRADE EXECUTED - CoinDCX Futures]*\n\n"
          f"🪙 *Pair:* `{pair}`\n"
          f"📊 *Side:* `{'LONG / BUY' if side == 'BUY' else 'SHORT / SELL'}`\n"
          f"💵 *Executed Price:* `${price}`\n"
          f"📦 *Qty:* `{quantity}` (Lev: {LEVERAGE}x)\n"
          f"🛑 *Stop Loss:* `${sl}`\n"
          f"🎯 *Target (TP):* `${tp}`\n"
          f"✅ *Status:* Order Placed Successfully!"
      )
      send_telegram(msg)
    else:
      err_msg = (
          f"⚠️ *CoinDCX Order Failed!*\nPair: {pair}\nError:"
          f" {res_data.get('message', res_data)}"
      )
      send_telegram(err_msg)
  except Exception as e:
    print(f"Execution Exception: {e}")


def fetch_binance_data(symbol, interval="1h", limit=80):
  url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
  try:
    res = requests.get(url, timeout=10)
    df = pd.DataFrame(
        res.json(),
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "q_vol",
            "trades",
            "tb_base",
            "tb_quote",
            "ignore",
        ],
    )
    for col in ["open", "high", "low", "close", "volume"]:
      df[col] = df[col].astype(float)
    return df
  except:
    return None


def run_auto_trade_engine():
  print("💎 CoinDCX Futures Auto-Trade Scanner Running...")
  already_traded = {}

  while True:
    try:
      for symbol in SYMBOLS:
        df = fetch_binance_data(symbol, interval="1h", limit=80)
        if df is None or len(df) < 50:
          continue

        df["EMA_50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["Vol_MA"] = df["volume"].rolling(20).mean()

        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()

        df["High_20"] = df["high"].shift(1).rolling(20).max()
        df["Low_20"] = df["low"].shift(1).rolling(20).min()

        prev = df.iloc[-2]
        pre_prev = df.iloc[-3]
        current_candle = df.iloc[-1]
        candle_time = df["timestamp"].iloc[-2]

        bull_cross = (
            (pre_prev["close"] <= pre_prev["High_20"])
            and (prev["close"] > prev["High_20"])
            and (prev["close"] > prev["EMA_50"])
            and (prev["volume"] > prev["Vol_MA"])
        )

        bear_cross = (
            (pre_prev["close"] >= pre_prev["Low_20"])
            and (prev["close"] < prev["Low_20"])
            and (prev["close"] < prev["EMA_50"])
            and (prev["volume"] > prev["Vol_MA"])
        )

        if bull_cross and already_traded.get(symbol) != candle_time:
          entry = current_candle["open"]
          sl = round(entry - (1.5 * prev["ATR"]), 2)
          risk = entry - sl
          tp = round(entry + (risk * 4.0), 2)
          place_coindcx_futures_order(symbol, "BUY", entry, sl, tp)
          already_traded[symbol] = candle_time

        elif bear_cross and already_traded.get(symbol) != candle_time:
          entry = current_candle["open"]
          sl = round(entry + (1.5 * prev["ATR"]), 2)
          risk = sl - entry
          tp = round(entry - (risk * 4.0), 2)
          place_coindcx_futures_order(symbol, "SELL", entry, sl, tp)
          already_traded[symbol] = candle_time

        time.sleep(2)

          time.sleep(120)
    except Exception as e:
        print(f"Scanner Loop Error: {e}")
        time.sleep(10)

if __name__ == "__main__":
    send_telegram("🚀 *CoinDCX Futures Auto-Trade Bot is Online (Render Cloud)!*\nLeverage: 3x | Monitoring: BTC, ETH, SOL")
    run_auto_trade_engine()
  
  
