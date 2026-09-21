import os
import requests
import json
import time

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8709739410:AAEiVKTVnox-8TLO0PblGTtVPKCccYJBh9k")

# Add your ID and any friend IDs here:
CHAT_IDS = [
    "5539952821",              
    "600818828"  
]

MIN_VOLUME_USDT = 20_000_000
MIN_PUMP_PCT = 4.0   # +4% for bullish breakout
MIN_DUMP_PCT = -4.0  # -4% for sell breakdown

# Exclude permanent high-cap majors and all stablecoins/fiat
IGNORE_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", 
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT", 
    "AEURUSDT", "USD1USDT", "RLUSDUSDT"
}

STATE_FILE = "alerted_coins.json"

def load_alerted():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                # Reset cache if older than 24 hours
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
    
    # Broadcast to all registered users
    for chat_id in CHAT_IDS:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Telegram error sending to {chat_id}: {e}")

def run():
    alerted = load_alerted()
    print(f"Loaded {len(alerted)} previously alerted signals from cache.")
    
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"

    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"Binance Vision API returned status {res.status_code}")
            return
        tickers = res.json()
        print(f"Fetched {len(tickers)} tickers successfully from Binance.")
    except Exception as e:
        print(f"Fetch failed: {e}")
        return

    new_alerts = False
    qualifying_count = 0

    for item in tickers:
        sym = item.get("symbol", "")

        if sym.endswith("USDT") and sym not in IGNORE_SYMBOLS:
            try:
                vol = float(item.get("quoteVolume", 0))
                pct = float(item.get("priceChangePercent", 0))
            except (ValueError, TypeError):
                continue

            if vol >= MIN_VOLUME_USDT:
                # 1. Bullish Breakout (>= +4%)
                if pct >= MIN_PUMP_PCT:
                    qualifying_count += 1
                    signal_key = f"{sym}_LONG"
                    if signal_key not in alerted:
                        price = item.get("lastPrice", "0")
                        send_telegram(sym, vol / 1_000_000, pct, price, "LONG")
                        alerted.add(signal_key)
                        new_alerts = True
                        print(f"New LONG alert sent for {sym}")
                        time.sleep(0.3)

                # 2. Sell Breakdown (<= -4%)
                elif pct <= MIN_DUMP_PCT:
                    qualifying_count += 1
                    signal_key = f"{sym}_SHORT"
                    if signal_key not in alerted:
                        price = item.get("lastPrice", "0")
                        send_telegram(sym, vol / 1_000_000, pct, price, "SHORT")
                        alerted.add(signal_key)
                        new_alerts = True
                        print(f"New SHORT alert sent for {sym}")
                        time.sleep(0.3)

    print(f"Scan complete. Total qualifying tickers: {qualifying_count}. New alerts triggered: {new_alerts}.")

    if new_alerts:
        save_alerted(alerted)

if __name__ == "__main__":
    run()
