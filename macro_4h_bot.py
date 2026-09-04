import time
import requests
import hmac
import hashlib
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleServer)
    server.serve_forever()

# Server ko background me start karein
threading.Thread(target=keep_alive, daemon=True).start()

# ================= ⚙️ PRO 4H TREND BOT =================
TELEGRAM_BOT_TOKEN = "8975800502:AAGkJttO42Vfp5kdenwDa_G7BaMwaz7qvyY"
TELEGRAM_CHAT_ID = "8832380997"

COINDCX_API_KEY = "7d61f2026a877742fa383d46de018af964ff23cf3a97504d"
COINDCX_API_SECRET = "752ae196ccd6e5e71bfb57b08d48ab33a207cd6bbbb5211ebe25a0bbc5617967"

PAIRS_MAP = {
    "SOLUSDT": {"coindcx_pair": "B-SOL_USDT", "precision": 2, "min_qty": 0.1},
    "BTCUSDT": {"coindcx_pair": "B-BTC_USDT", "precision": 3, "min_qty": 0.001},
    "ETHUSDT": {"coindcx_pair": "B-ETH_USDT", "precision": 3, "min_qty": 0.01}
}

TIMEFRAME = "4h"
USD_INR = 89.0
LEVERAGE = 5
SL_ATR_MULT = 1.8
RR_RATIO = 3.5

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except:
        pass

def get_futures_balance():
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/balances"
    ts = int(round(time.time() * 1000))
    body = {"timestamp": ts}
    json_body = json.dumps(body, separators=(',', ':'))
    sig = hmac.new(COINDCX_API_SECRET.encode(), json_body.encode(), hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
    try:
        res = requests.post(url, data=json_body, headers=headers, timeout=10)
        for b in res.json():
            if b.get("currency") == "INR":
                return float(b.get("available_balance", 5000.0))
        return 5000.0
    except:
        return 5000.0

def place_order(symbol, side, price, sl, tp):
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    cfg = PAIRS_MAP[symbol]
    
    current_inr = get_futures_balance()
    risk_inr = current_inr * 0.04 # 4% Risk
    sl_dist = abs(price - sl)
    
    qty = round((risk_inr / USD_INR) / sl_dist, cfg["precision"])
    max_qty = round(((current_inr / USD_INR) * LEVERAGE * 0.9) / price, cfg["precision"])
    qty = max(min(qty, max_qty), cfg["min_qty"])

    ts = int(round(time.time() * 1000))
    body = {
        "timestamp": ts,
        "order": {
            "side": "buy" if side == "BUY" else "sell",
            "pair": cfg["coindcx_pair"],
            "order_type": "market_order",
            "total_quantity": qty,
            "leverage": LEVERAGE,
            "notification": "no_notification",
            "time_in_force": "ioc"
        }
    }
    
    json_body = json.dumps(body, separators=(',', ':'))
    sig = hmac.new(COINDCX_API_SECRET.encode(), json_body.encode(), hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
    
    try:
        res = requests.post(url, data=json_body, headers=headers, timeout=10)
        res_data = res.json()
        if "id" in res_data or res_data.get("status") == "success":
            msg = (
                f"⚡ *[TRADE EXECUTED ON COINDCX]*\n\n"
                f"🪙 *Pair:* `{symbol}`\n"
                f"📊 *Side:* `{'LONG 🟢' if side == 'BUY' else 'SHORT 🔴'}`\n"
                f"⚙️ *Leverage:* `{LEVERAGE}x`\n"
                f"📦 *Qty:* `{qty}`\n"
                f"💵 *Entry:* `${price}` | 🛑 *SL:* `${sl}` | 🎯 *TP:* `${tp}`"
            )
            send_telegram(msg)
            return True
        else:
            err = res_data.get("message", "Unknown Error")
            send_telegram(f"⚠️ *Order Error ({symbol}):* `{err}`")
            return False
    except Exception as e:
        send_telegram(f"⚠️ *Network Error ({symbol}):* `{e}`")
        return False

def fetch_4h_candles(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={TIMEFRAME}&limit=210", timeout=10)
        return [{"time": k[0], "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in res.json()]
    except:
        return None

def calc_indicators(candles):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    
    alpha = 2.0 / (200 + 1.0)
    ema_200 = [closes[0]]
    for p in closes[1:]:
        ema_200.append(ema_200[-1] * (1.0 - alpha) + p * alpha)
        
    high_55 = max(highs[-56:-1])
    low_55 = min(lows[-56:-1])
    
    tr = [max(candles[i]["high"] - candles[i]["low"], abs(candles[i]["high"] - candles[i-1]["close"]), abs(candles[i]["low"] - candles[i-1]["close"])) for i in range(1, len(candles))]
    atr_14 = sum(tr[-14:]) / 14.0
    
    pdm = [highs[i] - highs[i-1] if (highs[i] - highs[i-1]) > (lows[i-1] - lows[i]) and (highs[i] - highs[i-1]) > 0 else 0 for i in range(1, len(candles))]
    ndm = [lows[i-1] - lows[i] if (lows[i-1] - lows[i]) > (highs[i] - highs[i-1]) and (lows[i-1] - lows[i]) > 0 else 0 for i in range(1, len(candles))]
    tr_s = sum(tr[-14:])
    pdi = 100 * (sum(pdm[-14:]) / tr_s) if tr_s > 0 else 0
    ndi = 100 * (sum(ndm[-14:]) / tr_s) if tr_s > 0 else 0
    adx_14 = 100 * (abs(pdi - ndi) / (pdi + ndi)) if (pdi + ndi) > 0 else 0
    
    return ema_200[-2], high_55, low_55, atr_14, adx_14

def run_macro_engine():
    send_telegram("🚀 *[4H Macro Engine Online - Live Balance Synced]*")
    already_traded = {}

    while True:
        try:
            for sym in PAIRS_MAP.keys():
                candles = fetch_4h_candles(sym)
                if not candles or len(candles) < 205:
                    continue
                
                ema200, high55, low55, atr14, adx14 = calc_indicators(candles)
                curr, prev = candles[-1], candles[-2]
                c_time = prev["time"]
                
                bull = (prev["close"] > high55 and prev["close"] > ema200 and adx14 > 20)
                bear = (prev["close"] < low55 and prev["close"] < ema200 and adx14 > 20)
                
                if bull and already_traded.get(sym) != c_time:
                    entry = curr["open"]
                    sl = round(entry - (SL_ATR_MULT * atr14), 2)
                    tp = round(entry + ((entry - sl) * RR_RATIO), 2)
                    if place_order(sym, "BUY", entry, sl, tp):
                        already_traded[sym] = c_time
                        time.sleep(10)
                        break
                        
                elif bear and already_traded.get(sym) != c_time:
                    entry = curr["open"]
                    sl = round(entry + (SL_ATR_MULT * atr14), 2)
                    tp = round(entry - ((sl - entry) * RR_RATIO), 2)
                    if place_order(sym, "SELL", entry, sl, tp):
                        already_traded[sym] = c_time
                        time.sleep(10)
                        break
                        
                time.sleep(2)
            time.sleep(300)
        except Exception as e:
            time.sleep(15)

if __name__ == "__main__":
    run_macro_engine()
    
