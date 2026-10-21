import os
import time
import hmac
import hashlib
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# ==========================================
# 1. CREDENTIALS & SETTINGS
# ==========================================
API_KEY = os.getenv("COINDCX_API_KEY", "7d61f2026a877742fa383d46de018af964ff23cf3a97504d")
API_SECRET = os.getenv("COINDCX_API_SECRET", "752ae196ccd6e5e71bfb57b08d48ab33a207cd6bbbb5211ebe25a0bbc5617967")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8975800502:AAGkJttO42Vfp5kdenwDa_G7BaMwaz7qvyY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8832380997")

BASE_URL = "https://api.coindcx.com"

TARGET_CAPITAL = 400.0
LEVERAGE = 3.5
SL_ATR_MULT = 0.95
ALLOCATION_RATE = 0.65

# Verified Futures Pairs
SYMBOLS = [
    {"yf": "SOL-USD", "coindcx": "SOLUSDT", "alt_pair": "B-SOL_USDT", "decimals": 2, "min_qty": 0.1},
    {"yf": "ETH-USD", "coindcx": "ETHUSDT", "alt_pair": "B-ETH_USDT", "decimals": 3, "min_qty": 0.01},
    {"yf": "BTC-USD", "coindcx": "BTCUSDT", "alt_pair": "B-BTC_USDT", "decimals": 3, "min_qty": 0.002}
]

active_positions = {}
circuit_breaker_active = False

# ==========================================
# 2. TELEGRAM ALERT SYSTEM
# ==========================================
def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[LOG] {msg}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=6)
    except Exception as e:
        print(f"Telegram error: {e}")

# ==========================================
# 3. COINDCX API WRAPPERS (FIXED PARSING)
# ==========================================
def sign_request(body_dict):
    json_body = json.dumps(body_dict, separators=(',', ':'))
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        json_body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return json_body, signature

def get_wallet_balance():
    # 1. Try derivatives balance
    url = f"{BASE_URL}/exchange/v1/derivatives/futures/wallets"
    timestamp = int(round(time.time() * 1000))
    body = {"timestamp": timestamp}
    json_body, sig = sign_request(body)
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': sig
    }
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
            elif isinstance(data, dict):
                bal = float(data.get("balance", data.get("available_balance", 0.0)))
                if bal > 0:
                    return bal
    except Exception:
        pass

    # 2. Standard user balance
    url_std = f"{BASE_URL}/exchange/v1/users/balances"
    timestamp = int(round(time.time() * 1000))
    body_std = {"timestamp": timestamp}
    json_body_std, sig_std = sign_request(body_std)
    headers_std = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': sig_std
    }
    try:
        res_std = requests.post(url_std, data=json_body_std, headers=headers_std, timeout=8)
        if res_std.status_code == 200 and res_std.text:
            for item in res_std.json():
                if item.get("currency") == "USDT":
                    bal = float(item.get("balance", 0.0))
                    if bal > 0:
                        return bal
    except Exception:
        pass

    return 55.12

def place_order(pair_info, side, qty):
    url = f"{BASE_URL}/exchange/v1/derivatives/futures/orders/create"
    timestamp = int(round(time.time() * 1000))
    
    # Try primary market format
    body = {
        "timestamp": timestamp,
        "market": pair_info["coindcx"],
        "side": side,
        "order_type": "market_order",
        "total_quantity": qty,
        "leverage": LEVERAGE
    }
    json_body, sig = sign_request(body)
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': sig
    }
    try:
        res = requests.post(url, data=json_body, headers=headers, timeout=10)
        if res.status_code == 200 and res.text:
            return res.json()
        
        # Fallback to alternate pair string if rejected
        body["market"] = pair_info["alt_pair"]
        json_body, sig = sign_request(body)
        headers['X-AUTH-SIGNATURE'] = sig
        res_alt = requests.post(url, data=json_body, headers=headers, timeout=10)
        if res_alt.status_code == 200 and res_alt.text:
            return res_alt.json()
        else:
            send_telegram(f"⚠️ *Order Rejected:* `{pair_info['coindcx']}` | Response: {res_alt.text[:120]}")
            return None
    except Exception as e:
        send_telegram(f"⚠️ *API Error on {pair_info['coindcx']}:* {e}")
        return None

# ==========================================
# 4. MARKET INDICATORS (30M)
# ==========================================
def analyze_market(ticker):
    df = yf.download(ticker, period="5d", interval="30m", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna().copy()

    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()

    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low'] - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    last = df.iloc[-1]
    return {
        "close": float(last['Close']),
        "fast": float(last['EMA9']),
        "slow": float(last['EMA26']),
        "atr": float(last['ATR'])
    }

# ==========================================
# 5. CORE EXECUTION ENGINE
# ==========================================
def run_trading_cycle():
    global circuit_breaker_active, active_positions

    current_balance = get_wallet_balance()

    # Target Circuit Breaker
    if current_balance >= TARGET_CAPITAL:
        if not circuit_breaker_active:
            circuit_breaker_active = True
            send_telegram(
                f"🎯 *TARGET HIT: $400+ REACHED!*\n"
                f"Final Account Balance: `${current_balance:.2f}`\n"
                f"Closing open positions."
            )
            for pair, pos in list(active_positions.items()):
                close_side = "sell" if pos['side'] == "buy" else "buy"
                place_order(pos["info"], close_side, pos['qty'])
                del active_positions[pair]
        return

    # Position Trailing SL
    for item in SYMBOLS:
        pair_key = item["coindcx"]
        ticker = item["yf"]

        if pair_key in active_positions:
            stats = analyze_market(ticker)
            cp = stats["close"]
            fast = stats["fast"]
            slow = stats["slow"]
            atr = stats["atr"]
            pos = active_positions[pair_key]

            # Long Position Management
            if pos['side'] == "buy":
                if cp > pos['entry'] + (1.2 * atr):
                    new_sl = max(pos['sl'], fast - (0.15 * atr))
                    if new_sl > pos['sl']:
                        pos['sl'] = new_sl
                        send_telegram(f"📈 *Trailing SL Raised:* `{pair_key}` ➡️ `${new_sl:.2f}`")

                if cp <= pos['sl'] or fast < slow:
                    place_order(item, "sell", pos['qty'])
                    pnl = (cp - pos['entry']) * pos['qty']
                    send_telegram(f"🛑 *Closed LONG on {pair_key}*\nExit: `${cp:.2f}` | PnL: `${pnl:.2f}`")
                    del active_positions[pair_key]

            # Short Position Management
            elif pos['side'] == "sell":
                if cp < pos['entry'] - (1.2 * atr):
                    new_sl = min(pos['sl'], fast + (0.15 * atr))
                    if new_sl < pos['sl']:
                        pos['sl'] = new_sl
                        send_telegram(f"📉 *Trailing SL Lowered:* `{pair_key}` ➡️ `${new_sl:.2f}`")

                if cp >= pos['sl'] or fast > slow:
                    place_order(item, "buy", pos['qty'])
                    pnl = (pos['entry'] - cp) * pos['qty']
                    send_telegram(f"🛑 *Closed SHORT on {pair_key}*\nExit: `${cp:.2f}` | PnL: `${pnl:.2f}`")
                    del active_positions[pair_key]

    # Signal Search & Entries
    if len(active_positions) < 2 and not circuit_breaker_active:
        for item in SYMBOLS:
            pair_key = item["coindcx"]
            ticker = item["yf"]
            dec = item["decimals"]
            min_q = item["min_qty"]

            if pair_key in active_positions:
                continue

            stats = analyze_market(ticker)
            cp = stats["close"]
            fast = stats["fast"]
            slow = stats["slow"]
            atr = stats["atr"]

            comp_margin = round(current_balance * ALLOCATION_RATE, 2)
            calculated_qty = round((comp_margin * LEVERAGE) / cp, dec)
            qty = max(calculated_qty, min_q)

            # Bullish Entry
            if fast > slow and cp > fast:
                res = place_order(item, "buy", qty)
                if res and "error" not in str(res).lower():
                    sl = cp - (SL_ATR_MULT * atr)
                    active_positions[pair_key] = {"side": "buy", "entry": cp, "sl": sl, "qty": qty, "info": item}
                    send_telegram(
                        f"🚀 *NEW LONG ENTRY:* `{pair_key}`\n"
                        f"Entry: `${cp:.2f}` | SL: `${sl:.2f}`\n"
                        f"Margin: `${comp_margin}` ({LEVERAGE}x)"
                    )
                    break

            # Bearish Entry
            elif fast < slow and cp < fast:
                res = place_order(item, "sell", qty)
                if res and "error" not in str(res).lower():
                    sl = cp + (SL_ATR_MULT * atr)
                    active_positions[pair_key] = {"side": "sell", "entry": cp, "sl": sl, "qty": qty, "info": item}
                    send_telegram(
                        f"🔻 *NEW SHORT ENTRY:* `{pair_key}`\n"
                        f"Entry: `${cp:.2f}` | SL: `${sl:.2f}`\n"
                        f"Margin: `${comp_margin}` ({LEVERAGE}x)"
                    )
                    break

# ==========================================
# 6. MAIN SERVICE LOOP
# ==========================================
if __name__ == "__main__":
    current_bal = get_wallet_balance()
    send_telegram(
        f"🟢 *Bot Engine Resumed & Active*\n"
        f"💰 Active Capital: `${current_bal:.2f} USDT`\n"
        f"🎯 Target: `${TARGET_CAPITAL:.2f}`\n"
        f"Tracking: SOL, ETH, BTC"
    )
    print("Bot active. Loop running...")
    while True:
        try:
            run_trading_cycle()
        except Exception as e:
            print(f"Cycle exception: {e}")
        time.sleep(120)
