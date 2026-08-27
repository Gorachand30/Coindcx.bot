import time
import requests
import hmac
import hashlib
import json

# ================= ⚙️ PRO 4H TREND BOT =================
TELEGRAM_BOT_TOKEN = "8975800502:AAGkJttO42Vfp5kdenwDa_G7BaMwaz7qvyY"
TELEGRAM_CHAT_ID = "8832380997"

COINDCX_API_KEY = "7d61f2026a877742fa383d46de018af964ff23cf3a97504d"
COINDCX_API_SECRET = "752ae196ccd6e5e71bfb57b08d48ab33a207cd6bbbb5211ebe25a0bbc5617967"

PAIRS_MAP = {
    "SOLUSDT": {"coindcx_pair": "B-SOL_USDT", "precision": 4},
    "BTCUSDT": {"coindcx_pair": "B-BTC_USDT", "precision": 3},
    "ETHUSDT": {"coindcx_pair": "B-ETH_USDT", "precision": 4}
}

TIMEFRAME = "4h"
CAPITAL_INR = 5000.0
USD_INR = 89.0
RISK_PER_TRADE_PCT = 0.04
LEVERAGE = 5
SL_ATR_MULT = 1.8
RR_RATIO = 3.5

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def place_order(symbol, side, price, sl, tp, base_risk_inr=200.0):
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    cfg = PAIRS_MAP[symbol]
    
    sl_dist = abs(price - sl)
    risk_usd = base_risk_inr / USD_INR
    qty = round(risk_usd / sl_dist, cfg["precision"])
    max_qty = round((CAPITAL_INR / USD_INR * LEVERAGE) / price, cfg["precision"])
    qty = min(qty, max_qty)

    timestamp = int(round(time.time() * 1000))
    body = {
        "timestamp": timestamp,
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
    signature = hmac.new(COINDCX_API_SECRET.encode(), json_body.encode(), hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": signature
    }
    
    try:
        res = requests.post(url, data=json_body, headers=headers, timeout=10)
        target_profit_inr = (abs(tp - price) * qty * USD_INR)
        msg = (
            f"⚡ *[4H MACRO BOT - TRADE TRIGGERED]*\n\n"
            f"🪙 *Pair:* `{symbol}` (4H Timeframe)\n"
            f"📊 *Side:* `{'LONG 🟢' if side == 'BUY' else 'SHORT 🔴'}`\n"
            f"⚙️ *Leverage:* `{LEVERAGE}x`\n"
            f"💵 *Entry:* `${price}`\n"
            f"📦 *Qty:* `{qty}`\n"
            f"🛑 *SL:* `${sl}`\n"
            f"🎯 *TP (1:3.5):* `${tp}` (~+₹{target_profit_inr:,.0f})"
        )
        send_telegram(msg)
    except Exception as e:
        print(f"Order Error: {e}")

def fetch_4h_candles(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={TIMEFRAME}&limit=210"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        candles = []
        for k in data:
            candles.append({
                "time": k[0], "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]), "vol": float(k[5])
            })
        return candles
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
    
    tr_list = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_14 = sum(tr_list[-14:]) / 14.0
    
    pdm_list, ndm_list = [], []
    for i in range(1, len(candles)):
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        pdm_list.append(up if up > dn and up > 0 else 0.0)
        ndm_list.append(dn if dn > up and dn > 0 else 0.0)
        
    tr_sum = sum(tr_list[-14:])
    pdi = 100 * (sum(pdm_list[-14:]) / tr_sum) if tr_sum > 0 else 0
    ndi = 100 * (sum(ndm_list[-14:]) / tr_sum) if tr_sum > 0 else 0
    adx_14 = 100 * (abs(pdi - ndi) / (pdi + ndi)) if (pdi + ndi) > 0 else 0
    
    return ema_200[-2], high_55, low_55, atr_14, adx_14

def run_macro_engine():
    send_telegram("🚀 *[4H Macro Trend Bot Online (5x | 1:3.5 RR)]*")
    already_traded = {}

    while True:
        try:
            for sym in PAIRS_MAP.keys():
                candles = fetch_4h_candles(sym)
                if not candles or len(candles) < 205:
                    continue
                
                ema200, high55, low55, atr14, adx14 = calc_indicators(candles)
                curr, prev = candles[-1], candles[-2]
                candle_time = prev["time"]
                
                bull = (prev["close"] > high55 and prev["close"] > ema200 and adx14 > 20)
                bear = (prev["close"] < low55 and prev["close"] < ema200 and adx14 > 20)
                
                if bull and already_traded.get(sym) != candle_time:
                    entry = curr["open"]
                    sl = round(entry - (SL_ATR_MULT * atr14), 2)
                    tp = round(entry + ((entry - sl) * RR_RATIO), 2)
                    place_order(sym, "BUY", entry, sl, tp)
                    already_traded[sym] = candle_time
                    
                elif bear and already_traded.get(sym) != candle_time:
                    entry = curr["open"]
                    sl = round(entry + (SL_ATR_MULT * atr14), 2)
                    tp = round(entry - ((sl - entry) * RR_RATIO), 2)
                    place_order(sym, "SELL", entry, sl, tp)
                    already_traded[sym] = candle_time
                    
                time.sleep(2)
            time.sleep(300)
        except Exception as e:
            print(f"Scanner Loop Error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    run_macro_engine()
              
