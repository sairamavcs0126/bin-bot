import os
import requests
import json
import time
from datetime import datetime, timezone

# 1. Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Telegram Recipient ID (Your chat only)
CHAT_IDS = [
    "5539952821"
]

# 2. Filtering & Indicator Parameters
MIN_24H_VOLUME_USDT = 15_000_000   # 15M USDT threshold to filter out dead pairs
BB_LENGTH = 20                     # 20-period Bollinger Bands
BB_MULT = 1.0                      # 1.0 Standard Deviation

IGNORE_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", 
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT", 
    "AEURUSDT", "USD1USDT", "RLUSDUSDT", "GUSDT"
}

STATE_FILE = "alerted_coins.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def load_alerted():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                if time.time() - data.get("timestamp", 0) > 7200:
                    return set()
                return set(data.get("coins", []))
        except Exception:
            return set()
    return set()

def save_alerted(coins):
    with open(STATE_FILE, "w") as f:
        json.dump({"timestamp": time.time(), "coins": list(coins)}, f)

def calculate_bollinger_bands(closes, length=20, mult=1.0):
    """Calculates 20-SMA Basis, Upper, and Lower Bollinger Bands (1.0 StdDev)."""
    if len(closes) < length:
        return None, None, None
    
    slice_c = closes[-length:]
    basis = sum(slice_c) / length
    variance = sum((x - basis) ** 2 for x in slice_c) / length
    stdev = variance ** 0.5
    
    upper = basis + (mult * stdev)
    lower = basis - (mult * stdev)
    return basis, upper, lower

def calculate_session_vwap(candles):
    """
    Calculates Daily Session-Anchored VWAP (resets at 00:00 UTC).
    Uses 'Close' as source to match your Pine Script configuration.
    """
    if not candles:
        return None
    
    latest_ts = candles[-1]["open_time"] / 1000
    latest_day = datetime.fromtimestamp(latest_ts, tz=timezone.utc).date()
    
    cum_vol = 0.0
    cum_pv = 0.0
    
    for c in candles:
        c_ts = c["open_time"] / 1000
        c_day = datetime.fromtimestamp(c_ts, tz=timezone.utc).date()
        
        if c_day == latest_day:
            vol = c["volume"]
            price = c["close"]
            cum_pv += price * vol
            cum_vol += vol
            
    if cum_vol == 0:
        return None
        
    return cum_pv / cum_vol

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for chat_id in CHAT_IDS:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception:
            pass

def scan_symbol(symbol):
    """Fetches 15m candles from Binance public Vision API."""
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=15m&limit=100"
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code != 200:
            return None
        raw_candles = r.json()
        if len(raw_candles) < 30:
            return None
            
        candles = []
        # Exclude the current open candle; evaluate on the completed bar
        for c in raw_candles[:-1]:
            candles.append({
                "open_time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5])
            })
            
        target = candles[-1]
        closes = [c["close"] for c in candles]
        
        basis, upper_bb, lower_bb = calculate_bollinger_bands(closes, BB_LENGTH, BB_MULT)
        vwap = calculate_session_vwap(candles)
        
        if None in (basis, upper_bb, lower_bb, vwap):
            return None
            
        # Pre-condition: VWAP inside Bollinger Bands
        if not (lower_bb < vwap < upper_bb):
            return None
            
        o, h, l, c = target["open"], target["high"], target["low"], target["close"]
        
        # 🔴 SELL SIGNAL: High reached upper band / above VWAP, then broke lower band
        if (h > vwap and h <= upper_bb) and (c < lower_bb or l < lower_bb):
            return {
                "signal": "SELL",
                "price": c,
                "open": o, "high": h, "low": l, "close": c,
                "vwap": vwap,
                "upper_bb": upper_bb,
                "lower_bb": lower_bb
            }
            
        # 🟢 BUY SIGNAL: Low reached lower band / below VWAP, then broke upper band
        if (l < vwap and l >= lower_bb) and (c > upper_bb or h > upper_bb):
            return {
                "signal": "BUY",
                "price": c,
                "open": o, "high": h, "low": l, "close": c,
                "vwap": vwap,
                "upper_bb": upper_bb,
                "lower_bb": lower_bb
            }
            
        return None
    except Exception:
        return None

def run():
    if not BOT_TOKEN:
        print("Missing BOT_TOKEN in environment.")
        return

    alerted = load_alerted()
    
    # Unrestricted Binance Vision endpoint for market tickers
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            send_telegram(f"⚠️ <b>API Warning:</b> Binance returned status {res.status_code}.")
            return
        tickers = res.json()
    except Exception as e:
        send_telegram(f"⚠️ <b>Scanner Error:</b> Failed to fetch Binance tickers: {e}")
        return

    triggered_count = 0

    for item in tickers:
        sym = item.get("symbol", "")
        if sym.endswith("USDT") and sym not in IGNORE_SYMBOLS:
            try:
                quote_vol = float(item.get("quoteVolume", 0))
            except (ValueError, TypeError):
                continue
                
            if quote_vol >= MIN_24H_VOLUME_USDT:
                time.sleep(0.04)  # Prevent rate limits
                result = scan_symbol(sym)
                
                if result:
                    sig = result["signal"]
                    alert_key = f"{sym}_{sig}"
                    
                    if alert_key not in alerted:
                        tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}.P"
                        
                        if sig == "BUY":
                            header = "🟢 <b>15M BB/VWAP EXPANSION (BUY)</b>"
                        else:
                            header = "🔴 <b>15M BB/VWAP EXPANSION (SELL)</b>"
                            
                        msg = (
                            f"{header}\n\n"
                            f"<b>Coin:</b> #{sym}\n"
                            f"<b>Signal Candle Close:</b> ${result['close']}\n"
                            f"<b>O:</b> ${result['open']} | <b>H:</b> ${result['high']} | <b>L:</b> ${result['low']}\n\n"
                            f"<b>VWAP:</b> ${result['vwap']:.4f}\n"
                            f"<b>Upper BB (1.0σ):</b> ${result['upper_bb']:.4f}\n"
                            f"<b>Lower BB (1.0σ):</b> ${result['lower_bb']:.4f}\n\n"
                            f"🔗 <a href='{tv_url}'>Open Chart on TradingView</a>"
                        )
                        
                        send_telegram(msg)
                        alerted.add(alert_key)
                        triggered_count += 1

    if triggered_count == 0:
        status_msg = "ℹ️ <b>Market Scanner:</b> 15m scan completed. No coins currently matching BB/VWAP traversal criteria."
        send_telegram(status_msg)
    else:
        save_alerted(alerted)

if __name__ == "__main__":
    run()
