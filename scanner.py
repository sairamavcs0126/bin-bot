import os
import requests
import json
import time

# Pull securely from GitHub Secrets — no credentials in plain text!
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_chat_ids = os.getenv("CHAT_IDS", "")
CHAT_IDS = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]

MIN_VOLUME_USDT = 20_000_000
MIN_PUMP_PCT = 4.0   # +4% for long breakout
MIN_DUMP_PCT = -4.0  # -4% for sell breakdown

IGNORE_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", 
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT", 
    "AEURUSDT", "USD1USDT", "RLUSDUSDT", "GUSDT"
}

STATE_FILE = "alerted_coins.json"

def load_alerted():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                if time.time() - data.get("timestamp", 0) > 86400:
                    return set()
                return set(data.get("coins", []))
        except Exception:
            return set()
    return set()

def save_alerted(coins):
    with open(STATE_FILE, "w") as f:
        json.dump({"timestamp": time.time(), "coins": list(coins)}, f)

def send_telegram(symbol, vol_m, pct_change, price, signal_type):
    tv_symbol = f"BINANCE:{symbol}.P"
    tv_url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
    
    if signal_type == "LONG":
        header = "🟢 <b>BULLISH BREAKOUT (>20M USDT)</b>"
    else:
        header = "🔴 <b>SELL BREAKDOWN (>20M USDT)</b>"

    text = (
        f"{header}\n\n"
        f"<b>Coin:</b> #{symbol}\n"
        f"<b>24h Turnover:</b> ${vol_m:.1f}M USDT\n"
        f"<b>24h Change:</b> {pct_change:+.2f}%\n"
        f"<b>Price:</b> ${price}\n\n"
        f"🔗 <a href='{tv_url}'>Open Chart on TradingView</a>"
    )
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for chat_id in CHAT_IDS:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                print(f"Delivered to {chat_id}")
            else:
                print(f"Telegram error for {chat_id}: {r.text}")
        except Exception as e:
            print(f"Network error for {chat_id}: {e}")

def run():
    if not BOT_TOKEN or not CHAT_IDS:
        print("Missing BOT_TOKEN or CHAT_IDS in environment variables.")
        return

    alerted = load_alerted()
    
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"

    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"Binance API returned status {res.status_code}")
            return
        tickers = res.json()
    except Exception as e:
        print(f"Fetch failed: {e}")
        return

    new_alerts = False

    for item in tickers:
        sym = item.get("symbol", "")

        if sym.endswith("USDT") and sym not in IGNORE_SYMBOLS:
            try:
                vol = float(item.get("quoteVolume", 0))
                pct = float(item.get("priceChangePercent", 0))
            except (ValueError, TypeError):
                continue

            if vol >= MIN_VOLUME_USDT:
                # 1. Bullish Breakout
                if pct >= MIN_PUMP_PCT and f"{sym}_LONG" not in alerted:
                    price = item.get("lastPrice", "0")
                    send_telegram(sym, vol / 1_000_000, pct, price, "LONG")
                    alerted.add(f"{sym}_LONG")
                    new_alerts = True
                    time.sleep(0.3)

                # 2. Sell Breakdown
                elif pct <= MIN_DUMP_PCT and f"{sym}_SHORT" not in alerted:
                    price = item.get("lastPrice", "0")
                    send_telegram(sym, vol / 1_000_000, pct, price, "SHORT")
                    alerted.add(f"{sym}_SHORT")
                    new_alerts = True
                    time.sleep(0.3)

    if new_alerts:
        save_alerted(alerted)

if __name__ == "__main__":
    run()
