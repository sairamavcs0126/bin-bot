import os
import requests
import json
import time

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Recipient Telegram IDs
CHAT_IDS = [
    "5539952821",   # Your Chat ID
    "6008188228"    # Friend's Chat ID
]

# --- SCANNER CRITERIA ---
MIN_VOLUME_24H_USDT = 40_000_000   # 40M+ USDT 24h turnover
MIN_PUMP_24H_PCT = 4.0              # +6% 24h gain
MIN_DUMP_24H_PCT = -3.0             # -6% 24h drop

MIN_1H_PCT = 2.5                    # 2.5% move in current 1h candle
MIN_RVOL = 1.8                      # 1h volume >= 1.8x normal pace

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
                if time.time() - data.get("timestamp", 0) > 14400:
                    return set()
                return set(data.get("coins", []))
        except Exception:
            return set()
    return set()

def save_alerted(coins):
    with open(STATE_FILE, "w") as f:
        json.dump({"timestamp": time.time(), "coins": list(coins)}, f)

def check_1h_momentum(symbol, quote_vol_24h):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1h&limit=2"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        candles = r.json()
        if len(candles) < 2:
            return None

        cur = candles[-1]
        open_p = float(cur[1])
        close_p = float(cur[4])
        vol_quote_1h = float(cur[7])

        change_1h = ((close_p - open_p) / open_p) * 100
        avg_hourly_vol = quote_vol_24h / 24.0
        rvol = vol_quote_1h / avg_hourly_vol if avg_hourly_vol > 0 else 0

        return {
            "change_1h": change_1h,
            "rvol": rvol,
            "last_price": close_p
        }
    except Exception:
        return None

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

def run():
    if not BOT_TOKEN:
        print("Missing BOT_TOKEN.")
        return

    alerted = load_alerted()
    headers = {"User-Agent": "Mozilla/5.0"}
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"

    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code != 200:
            send_telegram(f"⚠️ <b>Scanner Warning:</b> Binance API returned status {res.status_code}.")
            return
        tickers = res.json()
    except Exception as e:
        send_telegram(f"⚠️ <b>Scanner Error:</b> Failed to fetch Binance data: {e}")
        return

    triggered_count = 0

    for item in tickers:
        sym = item.get("symbol", "")

        if sym.endswith("USDT") and sym not in IGNORE_SYMBOLS:
            try:
                vol = float(item.get("quoteVolume", 0))
                pct = float(item.get("priceChangePercent", 0))
            except (ValueError, TypeError):
                continue

            if vol >= MIN_VOLUME_24H_USDT:
                is_long_candidate = (pct >= MIN_PUMP_24H_PCT and f"{sym}_LONG" not in alerted)
                is_short_candidate = (pct <= MIN_DUMP_24H_PCT and f"{sym}_SHORT" not in alerted)

                if is_long_candidate or is_short_candidate:
                    m = check_1h_momentum(sym, vol)
                    time.sleep(0.05)

                    if not m:
                        continue

                    # Bullish breakout alert
                    if is_long_candidate and m["change_1h"] >= MIN_1H_PCT and m["rvol"] >= MIN_RVOL:
                        tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}.P"
                        msg = (
                            f"🟢 <b>FRESH 1H BREAKOUT</b>\n\n"
                            f"<b>Coin:</b> #{sym}\n"
                            f"<b>Price:</b> ${m['last_price']}\n"
                            f"<b>1H Move:</b> {m['change_1h']:+.2f}%\n"
                            f"<b>1H Vol Surge:</b> {m['rvol']:.1f}x normal\n"
                            f"<b>24h Turnover:</b> ${vol/1_000_000:.1f}M USDT ({pct:+.2f}%)\n\n"
                            f"🔗 <a href='{tv_url}'>Open Chart on TradingView</a>"
                        )
                        send_telegram(msg)
                        alerted.add(f"{sym}_LONG")
                        triggered_count += 1

                    # Bearish breakdown alert
                    elif is_short_candidate and m["change_1h"] <= -MIN_1H_PCT and m["rvol"] >= MIN_RVOL:
                        tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}.P"
                        msg = (
                            f"🔴 <b>FRESH 1H BREAKDOWN</b>\n\n"
                            f"<b>Coin:</b> #{sym}\n"
                            f"<b>Price:</b> ${m['last_price']}\n"
                            f"<b>1H Move:</b> {m['change_1h']:+.2f}%\n"
                            f"<b>1H Vol Surge:</b> {m['rvol']:.1f}x normal\n"
                            f"<b>24h Turnover:</b> ${vol/1_000_000:.1f}M USDT ({pct:+.2f}%)\n\n"
                            f"🔗 <a href='{tv_url}'>Open Chart on TradingView</a>"
                        )
                        send_telegram(msg)
                        alerted.add(f"{sym}_SHORT")
                        triggered_count += 1

    # If no coins matched the strict criteria, notify Telegram that scan ran cleanly
    if triggered_count == 0:
        status_msg = "ℹ️ <b>Market Scanner:</b> Active scan completed. No coins currently matching breakout/breakdown conditions."
        send_telegram(status_msg)
    else:
        save_alerted(alerted)

if __name__ == "__main__":
    run()
