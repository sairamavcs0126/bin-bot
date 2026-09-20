import os
import requests
import json
import time

BOT_TOKEN = os.getenv("BOT_TOKEN", "8709739410:AAEiVKTVnox-8TLO0PblGTtVPKCccYJBh9k")
CHAT_ID = os.getenv("CHAT_ID", "5539952821")
MIN_VOLUME_USDT = 20_000_000

# High-cap majors to ignore
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
            print(f"Alert sent to Telegram for {symbol}")
        else:
            print(f"Telegram error response: {r.text}")
    except Exception as e:
        print(f"Telegram request failed: {e}")

def get_binance_data():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    # 1. Official Binance Public Market Data Network (No 451 geo-restrictions)
    # 2. Public Free CORS/Worker proxy fallback
    target_urls = [
        "https://data-api.binance.vision/api/v3/ticker/24hr",
        "https://api.allorigins.win/raw?url=https://fapi.binance.com/fapi/v1/ticker/24hr"
    ]

    for url in target_urls:
        try:
            print(f"Attempting fetch from: {url}")
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    print(f"Successfully retrieved {len(data)} tickers.")
                    return data
            else:
                print(f"Status {res.status_code} from {url}")
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")

    return None

def run():
    alerted = load_alerted()
    tickers = get_binance_data()

    if not tickers:
        print("Could not retrieve market data.")
        return

    new_alerts = False

    for item in tickers:
        if not isinstance(item, dict):
            continue

        sym = item.get("symbol", "")

        # Target USDT pairs only
        if sym.endswith("USDT") and sym not in IGNORE_SYMBOLS:
            try:
                vol = float(item.get("quoteVolume", 0))
            except (ValueError, TypeError):
                continue

            if vol >= MIN_VOLUME_USDT and sym not in alerted:
                pct = float(item.get("priceChangePercent", 0))
                price = item.get("lastPrice", "0")
                vol_m = vol / 1_000_000

                send_telegram(sym, vol_m, pct, price)
                alerted.add(sym)
                new_alerts = True
                time.sleep(0.5)

    if new_alerts:
        save_alerted(alerted)

if __name__ == "__main__":
    run()
