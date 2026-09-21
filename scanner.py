import os
import requests
import json
import time

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHAT_IDS = [
    "5539952821",   # Your Chat ID
    "6008188228"    # Friend's Chat ID
]

# --- REFINED HIGH-CONVICTION FILTERS ---
MIN_VOLUME_24H_USDT = 40_000_000   # Raised to 40M+ to weed out low-liquidity chop
MIN_PUMP_24H_PCT = 6.0              # 24h macro filter (+6%)
MIN_DUMP_24H_PCT = -6.0             # 24h macro filter (-6%)

MIN_1H_PCT = 2.5                    # Must have moved at least 2.5% in the past 1 hour
MIN_RVOL = 1.8                      # 1h volume must be 1.8x above normal 24h hourly average

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
                # Expire alerts after 4 hours so you don't get repeated alerts on the same trend
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
    """
    Validates whether the coin is actively expanding on the 1-hour chart
    and calculates 1h relative volume (RVol).
    """
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1h&limit=2"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        candles = r.json()
        if len(candles) < 2:
            return None

        # Current forming candle
        cur = candles[-1]
        open_p = float(cur[1])
        close_p = float(cur[4])
        vol_quote_1h = float(cur[7])  # quote volume in USDT

        change_1h = ((close_p - open_p) / open_p) * 100

        # Expected hourly volume based on 24h pace
        avg_hourly_vol = quote_vol_24h / 24.0
        rvol = vol_quote_1h / avg_hourly_vol if avg_hourly_vol > 0 else 0

        return {
            "change_1h": change_1h,
            "rvol": rvol,
            "last_price": close_p
        }
    except Exception:
        return None

def send_telegram(symbol, vol_m, pct_24h, pct_1h, rvol, price, signal_type):
    tv_symbol = f"BINANCE:{symbol}.P"
    tv_url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
    
    if signal_type == "LONG":
        header = "🟢 <b>FRESH 1H BREAKOUT</b>"
    else:
        header = "🔴 <b>FRESH 1H BREAKDOWN</b>"

    text = (
        f"{header}\n\n"
        f"<b>Coin:</b> #{symbol}\n"
        f"<b>Price:</b> ${price}\n"
        f"<b>1H Move:</b> {pct_1h:+.2f}%\n"
        f"<b>1H Vol Surge:</b> {rvol:.1f}x normal\n"
        f"<b>24h Turnover:</b> ${vol_m:.1f}M USDT ({pct_24h:+.2f}%)\n\n"
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

            # First stage: 24h macro liquid movers
            if vol >= MIN_VOLUME_24H_USDT:
                is_long_candidate = (pct >= MIN_PUMP_24H_PCT and f"{sym}_LONG" not in alerted)
                is_short_candidate = (pct <= MIN_DUMP_24H_PCT and f"{sym}_SHORT" not in alerted)

                if is_long_candidate or is_short_candidate:
                    # Second stage: Confirm active 1-hour momentum & volume surge
                    m = check_1h_momentum(sym, vol)
                    time.sleep(0.05)  # Rate limit protection

                    if not m:
                        continue

                    # Long confirmation
                    if is_long_candidate and m["change_1h"] >= MIN_1H_PCT and m["rvol"] >= MIN_RVOL:
                        send_telegram(sym, vol / 1_000_000, pct, m["change_1h"], m["rvol"], m["last_price"], "LONG")
                        alerted.add(f"{sym}_LONG")
                        new_alerts = True

                    # Short confirmation
                    elif is_short_candidate and m["change_1h"] <= -MIN_1H_PCT and m["rvol"] >= MIN_RVOL:
                        send_telegram(sym, vol / 1_000_000, pct, m["change_1h"], m["rvol"], m["last_price"], "SHORT")
                        alerted.add(f"{sym}_SHORT")
                        new_alerts = True

    if new_alerts:
        save_alerted(alerted)

if __name__ == "__main__":
    run()
