
import time
import requests
import hmac
import hashlib
import json

# ================= CONFIGURATION =================
TELEGRAM_BOT_TOKEN = "8975800502:AAGkJttO42Vfp5kdenwDa_G7BaMwaz7qvyY"
TELEGRAM_CHAT_ID = "8832380997"

COINDCX_API_KEY = "7d61f2026a877742fa383d46de018af964ff23cf3a97504d"
COINDCX_API_SECRET = "752ae196ccd6e5e71bfb57b08d48ab33a207cd6bbbb5211ebe25a0bbc5617967"

SYMBOLS = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]
TIMEFRAME = "1h"
TRADE_AMOUNT_USDT = 50.0  # Margin per trade
LEVERAGE = 3
RR_RATIO = 4.0
SL_ATR_MULT = 1.5

# ================= TELEGRAM ALERT =================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

# ================= COINDCX FUTURES ORDER =================
def place_order(pair, side, price, sl, tp):
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    base_asset = pair.replace("USDT", "")
    coindcx_pair = f"B-{base_asset}_USDT"
    
    qty = round((TRADE_AMOUNT_USDT * LEVERAGE) / price, 4)
    if base_asset == "BTC":
        qty = round((TRADE_AMOUNT_USDT * LEVERAGE) / price, 3)

    timestamp = int(round(time.time() * 1000))
    body = {
        "timestamp": timestamp,
        "order": {
            "side": "buy" if side == "BUY" else "sell",
            "pair": coindcx_pair,
            "order_type": "market_order",
            "total_quantity": qty,
            "leverage": LEVERAGE,
            "notification": "no_notification",
            "time_in_force": "ioc"
        }
    }
    
    json_body = json.dumps(body, separators=(',', ':'))
    signature = hmac.new(COINDCX_API_SECRET.encode(), json_body.encode(), hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": signature
    }
    
    try:
        res = requests.post(url, data=json_body, headers=headers, timeout=10)
        res_data = res.json()
        if res.status_code == 200:
            msg = (
                f"⚡ *[AUTO-TRADE TRIGGERED - Trend Engine]*\n\n"
                f"🪙 *Pair:* `{pair}`\n"
                f"📊 *Type:* `{'LONG (BUY)' if side == 'BUY' else 'SHORT (SELL)'}`\n"
                f"💵 *Entry:* `${price}`\n"
                f"📦 *Qty:* `{qty}` ({LEVERAGE}x)\n"
                f"🛑 *SL:* `${sl}`\n"
                f"🎯 *TP (1:4):* `${tp}`\n"
                f"✅ *Status:* Order Executed on CoinDCX"
            )
            send_telegram(msg)
        else:
            send_telegram(f"⚠️ *Order Error ({pair}):* {res_data.get('message', res_data)}")
    except Exception as e:
        print(f"Execution Error: {e}")

# ================= MARKET DATA & INDICATORS =================
def fetch_klines(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={TIMEFRAME}&limit=60"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        candles = []
        for k in data:
            candles.append({
                "time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "vol": float(k[5])
            })
        return candles
    except:
        return None

def calc_ema50(closes):
    alpha = 2.0 / (50 + 1.0)
    ema = [closes[0]]
    for p in closes[1:]:
        ema.append(ema[-1] * (1.0 - alpha) + p * alpha)
    return ema

def calc_atr14(candles):
    tr_list = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
    return sum(tr_list[-14:]) / 14.0

# ================= MAIN ENGINE =================
def run_live_bot():
    print("🚀 Donchian + EMA50 + Volume MA Live Engine Started...")
    already_traded = {}
    
    while True:
        try:
            for sym in SYMBOLS:
                candles = fetch_klines(sym)
                if not candles or len(candles) < 55:
                    continue
                
                closes = [c["close"] for c in candles]
                volumes = [c["vol"] for c in candles]
                
                ema_50 = calc_ema50(closes)
                atr_14 = calc_atr14(candles)
                vol_ma20 = sum(volumes[-21:-1]) / 20.0
                
                high_20 = max([c["high"] for c in candles[-22:-2]])
                low_20 = min([c["low"] for c in candles[-22:-2]])
                
                curr = candles[-1]
                prev = candles[-2]
                pre_prev = candles[-3]
                candle_time = prev["time"]
                
                # Strategy Conditions
                bull_cross = (
                    pre_prev["close"] <= high_20 and 
                    prev["close"] > high_20 and 
                    prev["close"] > ema_50[-2] and 
                    prev["vol"] > vol_ma20
                )
                
                bear_cross = (
                    pre_prev["close"] >= low_20 and 
                    prev["close"] < low_20 and 
                    prev["close"] < ema_50[-2] and 
                    prev["vol"] > vol_ma20
                )
                
                if bull_cross and already_traded.get(sym) != candle_time:
                    entry = curr["open"]
                    sl = round(entry - (SL_ATR_MULT * atr_14), 2)
                    risk = entry - sl
                    tp = round(entry + (risk * RR_RATIO), 2)
                    place_order(sym, "BUY", entry, sl, tp)
                    already_traded[sym] = candle_time
                    
                elif bear_cross and already_traded.get(sym) != candle_time:
                    entry = curr["open"]
                    sl = round(entry + (SL_ATR_MULT * atr_14), 2)
                    risk = sl - entry
                    tp = round(entry - (risk * RR_RATIO), 2)
                    place_order(sym, "SELL", entry, sl, tp)
                    already_traded[sym] = candle_time
                
                time.sleep(2)
                
            time.sleep(120)  # Scan interval: 2 minutes
        except Exception as e:
            print(f"Scanner Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    send_telegram("🚀 *CoinDCX Futures Trend Engine Online!*\nPairs: SOL, BTC, ETH | 1:4 RR | 3x Lev")
    run_live_bot()
    
Stop c
