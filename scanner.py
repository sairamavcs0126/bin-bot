import os
import requests
import json
import time

# Credentials loaded from environment or directly entered
BOT_TOKEN = os.getenv("BOT_TOKEN", "8709739410:AAEiVKTVnox-8TLO0PblGTtVPKCccYJBh9k")
CHAT_ID = os.getenv("CHAT_ID", "5539952821")
MIN_VOLUME_USDT = 20_000_000

# Exclude permanent top-cap coins to avoid constant spam
IGNORE_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", 
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT"
}

STATE_FILE = "alerted_coins.json"

def load_alerted():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_alerted(coins):
    with open(STATE_FILE, "w") as f:
        json.dump(list(coins), f)

def send_telegram(symbol, vol_m, pct_change, price):
    # TradingView Direct Link
    tv_symbol = f"BINANCE:{symbol}.P"
    tv_url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
    
    text = (
        f"🚨 <b>VOLUME SURGE ALERT (&gt;20M USDT)</b> 🚨\n\n"
        f"<b>Coin:</b> #{symbol}\n"
        f"<b>24h Turnover:</b> ${vol_m:.1f}M USDT\n"
        f"<b>24h Price Change:</b> {pct_change:+.2f}%\n"
        f"<b>Price:</b> ${price}\n\n"
        f"🔗 <a href='{tv_url}'>Open Chart on TradingView</a>"
    )
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"Alert sent for {symbol}")
        else:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Request error: {e}")

def run():
    alerted = load_alerted()
    api_url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    
    try:
        response = requests.get(api_url, timeout=12).json()
        new_alerts = False

        for item in response:
            sym = item.get("symbol", "")
            
            # USDT perpetual futures only
            if sym.endswith("USDT") and sym not in IGNORE_SYMBOLS:
                vol = float(item["quoteVolume"])
                
                # Check threshold and deduplicate
                if vol >= MIN_VOLUME_USDT and sym not in alerted:
                    pct = float(item["priceChangePercent"])
                    price = item["lastPrice"]
                    vol_m = vol / 1_000_000
                    
                    send_telegram(sym, vol_m, pct, price)
                    alerted.add(sym)
                    new_alerts = True
                    time.sleep(1)  # Prevent rate limits

        if new_alerts:
            save_alerted(alerted)

    except Exception as err:
        print(f"Binance API check failed: {err}")

if __name__ == "__main__":
    run()
