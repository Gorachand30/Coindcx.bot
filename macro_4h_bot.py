import os
import time
import hmac
import hashlib
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf

API_KEY = os.getenv("COINDCX_API_KEY", "7d61f2026a877742fa383d46de018af964ff23cf3a97504d")
API_SECRET = os.getenv("COINDCX_API_SECRET", "752ae196ccd6e5e71bfb57b08d48ab33a207cd6bbbb5211ebe25a0bbc5617967")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8975800502:AAGkJttO42Vfp5kdenwDa_G7BaMwaz7qvyY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8832380997")

BASE_URL = "https://api.coindcx.com"
TARGET_CAPITAL = 400.0
LEVERAGE = 3.5
SL_ATR_MULT = 0.95
ALLOCATION_RATE = 0.65

# CoinDCX Official Derivatives Symbols
SYMBOLS = [
    {"yf": "SOL-USD", "pair": "B-SOL_USDT", "decimals": 2, "min_qty": 0.1},
    {"yf": "ETH-USD", "pair": "B-ETH_USDT", "decimals": 3, "min_qty": 0.01},
    {"yf": "BTC-USD", "pair": "B-BTC_USDT", "decimals": 4, "min_qty": 0.001}
]

active_positions = {}
circuit_breaker_active = False

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[LOG] {msg}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")

def sign_request(body_dict):
    json_body = json.dumps(body_dict, separators=(',', ':'))
    signature = hmac.new(API_SECRET.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
    return json_body, signature

def get_wallet_balance():
    url = f"{BASE_URL}/exchange/v1/derivatives/futures/wallets"
    timestamp = int(round(time.time() * 1000))
    body = {"timestamp": timestamp}
    json_body, sig = sign_request(body)
    headers = {'Content-Type': 'application/json', 'X-AUTH-APIKEY': API_KEY, 'X-AUTH-SIGNATURE': sig}
    try:
        res = requests.post(url, data=json_body, headers=headers, timeout=8)
        if res.status_code == 200 and res.text:
            data = res.json()
            if isinstance(data, list):
                for item in data:
                    if item.get("currency") == "USDT":
                        bal = float(item.get("balance", item.get("available_balance", 0.0)))
                        if bal > 0:
                            return bal
    except Exception:
        pass
    return 90.81

def place_order(pair_str, side, qty):
    url = f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create"
    timestamp = int(round(time.time() * 1000))
    body = {
        "timestamp": timestamp,
        "market": pair_str,
        "side": side,
        "order_type": "market_order",
        "total_quantity": qty,
        "leverage": LEVERAGE
    }
    json_body, sig = sign_request(body)
    headers = {'Content-Type': 'application/json', 'X-AUTH-APIKEY': API_KEY, 'X-AUTH-SIGNATURE': sig}
    try:
        res = requests.post(url, data=json_body, headers=headers, timeout=10)
        res_data = res.json()
        if "id" in res_data or "order_id" in res_data:
            return res_data
        else:
            send_telegram(f"⚠️ *Order Error:* `{pair_str}` ➡️ {res.text[:100]}")
            return None
    except Exception as e:
        send_telegram(f"⚠️ *Order Exception:* {e}")
        return None

def analyze_market(ticker):
    df = yf.download(ticker, period="5d", interval="30m", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna().copy()
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    tr = pd.concat([df['High'] - df['Low'], (df['High'] - df['Close'].shift(1)).abs(), (df['Low'] - df['Close'].shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    last = df.iloc[-1]
    return {"close": float(last['Close']), "fast": float(last['EMA9']), "slow": float(last['EMA26']), "atr": float(last['ATR'])}

def run_trading_cycle():
    global circuit_breaker_active, active_positions
    current_balance = get_wallet_balance()

    if current_balance >= TARGET_CAPITAL:
        if not circuit_breaker_active:
            circuit_breaker_active = True
            send_telegram(f"🎯 *TARGET HIT: $400+ REACHED!* Balance: `${current_balance:.2f}`")
            for pair_key, pos in list(active_positions.items()):
                close_side = "sell" if pos['side'] == "buy" else "buy"
                place_order(pair_key, close_side, pos['qty'])
                del active_positions[pair_key]
        return

    # Manage Trailing Stops
    for item in SYMBOLS:
        p_key = item["pair"]
        if p_key in active_positions:
            stats = analyze_market(item["yf"])
            cp, fast, slow, atr = stats["close"], stats["fast"], stats["slow"], stats["atr"]
            pos = active_positions[p_key]

            if pos['side'] == "buy":
                if cp > pos['entry'] + (1.2 * atr):
                    new_sl = max(pos['sl'], fast - (0.15 * atr))
                    if new_sl > pos['sl']:
                        pos['sl'] = new_sl
                        send_telegram(f"📈 *Trailing SL Raised:* `{p_key}` ➡️ `${new_sl:.2f}`")
                if cp <= pos['sl'] or fast < slow:
                    place_order(p_key, "sell", pos['qty'])
                    send_telegram(f"🛑 *Closed LONG on {p_key}* at `${cp:.2f}`")
                    del active_positions[p_key]

            elif pos['side'] == "sell":
                if cp < pos['entry'] - (1.2 * atr):
                    new_sl = min(pos['sl'], fast + (0.15 * atr))
                    if new_sl < pos['sl']:
                        pos['sl'] = new_sl
                        send_telegram(f"📉 *Trailing SL Lowered:* `{p_key}` ➡️ `${new_sl:.2f}`")
                if cp >= pos['sl'] or fast > slow:
                    place_order(p_key, "buy", pos['qty'])
                    send_telegram(f"🛑 *Closed SHORT on {p_key}* at `${cp:.2f}`")
                    del active_positions[p_key]

    # Signal Search & Entry
    if len(active_positions) < 2 and not circuit_breaker_active:
        for item in SYMBOLS:
            p_key = item["pair"]
            if p_key in active_positions:
                continue

            stats = analyze_market(item["yf"])
            cp, fast, slow, atr = stats["close"], stats["fast"], stats["slow"], stats["atr"]

            comp_margin = round(current_balance * ALLOCATION_RATE, 2)
            calculated_qty = round((comp_margin * LEVERAGE) / cp, item["decimals"])
            qty = max(calculated_qty, item["min_qty"])

            if fast > slow and cp > fast:
                res = place_order(p_key, "buy", qty)
                if res:
                    sl = cp - (SL_ATR_MULT * atr)
                    active_positions[p_key] = {"side": "buy", "entry": cp, "sl": sl, "qty": qty}
                    send_telegram(f"🚀 *LONG ENTRY:* `{p_key}`\nEntry: `${cp:.2f}` | SL: `${sl:.2f}`")
                    break

            elif fast < slow and cp < fast:
                res = place_order(p_key, "sell", qty)
                if res:
                    sl = cp + (SL_ATR_MULT * atr)
                    active_positions[p_key] = {"side": "sell", "entry": cp, "sl": sl, "qty": qty}
                    send_telegram(f"🔻 *SHORT ENTRY:* `{p_key}`\nEntry: `${cp:.2f}` | SL: `${sl:.2f}`")
                    break

if __name__ == "__main__":
    b = get_wallet_balance()
    send_telegram(f"🟢 *Compounding Engine Online*\nCapital: `${b:.2f} USDT`\nTarget: `${TARGET_CAPITAL}`")
    while True:
        try:
            run_trading_cycle()
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(120)
    
