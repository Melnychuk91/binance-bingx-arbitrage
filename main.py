import os
import time
import requests
import ccxt
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
# =========================
# НАСТРОЙКИ
# =========================

SYMBOL = "BTC/USDT"
MIN_SPREAD = 0.05 # минимальная разница в %
CHECK_INTERVAL = 10        # проверка каждые 10 секунд

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        return

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# =========================
# БИРЖИ
# =========================

binance = ccxt.binance({
    "enableRateLimit": True
})

bingx = ccxt.bingx({
    "enableRateLimit": True
})


# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram не настроен:")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Ошибка Telegram:", e)


# =========================
# ПОЛУЧЕНИЕ ЦЕН
# =========================

def get_price(exchange, symbol):
    ticker = exchange.fetch_ticker(symbol)

    bid = ticker.get("bid")
    ask = ticker.get("ask")

    return bid, ask


# =========================
# ПОИСК АРБИТРАЖА
# =========================

def check_arbitrage():

    binance_bid, binance_ask = get_price(binance, SYMBOL)
    bingx_bid, bingx_ask = get_price(bingx, SYMBOL)

    if not all([
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    ]):
        return

    # Покупаем дешевле на одной бирже
    # и продаём дороже на другой.

    # Binance -> BingX
    spread_1 = ((bingx_bid - binance_ask) / binance_ask) * 100

    # BingX -> Binance
    spread_2 = ((binance_bid - bingx_ask) / bingx_ask) * 100

    print(
        f"BTC/USDT | "
        f"Binance: {binance_ask:.2f} | "
        f"BingX: {bingx_ask:.2f} | "
        f"Spread: {max(spread_1, spread_2):.3f}%"
    )

    if spread_1 >= MIN_SPREAD:

        message = (
            "🚨 АРБИТРАЖ\n\n"
            f"Пара: {SYMBOL}\n\n"
            f"Купить Binance: {binance_ask:.2f}\n"
            f"Продать BingX: {bingx_bid:.2f}\n\n"
            f"Разница: {spread_1:.3f}%\n\n"
            "⚠️ Без учёта комиссий и проскальзывания."
        )

        print(message)
        send_telegram(message)

    elif spread_2 >= MIN_SPREAD:

        message = (
            "🚨 АРБИТРАЖ\n\n"
            f"Пара: {SYMBOL}\n\n"
            f"Купить BingX: {bingx_ask:.2f}\n"
            f"Продать Binance: {binance_bid:.2f}\n\n"
            f"Разница: {spread_2:.3f}%\n\n"
            "⚠️ Без учёта комиссий и проскальзывания."
        )

        print(message)
        send_telegram(message)

# =========================
# TELEGRAM COMMAND LISTENER
# =========================

def telegram_listener():
    offset = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

            params = {
                "timeout": 30,
                "offset": offset
            }

            response = requests.get(url, params=params, timeout=40)
            data = response.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message")

                if not message:
                    continue

                chat_id = str(message["chat"]["id"])
                text = message.get("text", "").strip().lower()

                # Принимаем команды только от твоего Telegram ID
                if str(TELEGRAM_CHAT_ID) != chat_id:
                    continue

                if text in ["/start", "start", "/test", "test"]:
                    send_telegram(
                        "🤖 Binance ↔ BingX Arbitrage Bot работает!\n\n"
                        f"Пара: {SYMBOL}\n"
                        f"Минимальный спред: {MIN_SPREAD}%\n"
                        f"Проверка каждые: {CHECK_INTERVAL} сек."
                    )

        except Exception as e:
            print("Telegram listener error:", e)
            time.sleep(5)
# =========================
# ЗАПУСК
# =========================

print("🚀 Binance ↔ BingX Arbitrage Scanner запущен")
print(f"Пара: {SYMBOL}")
print(f"Минимальный спред: {MIN_SPREAD}%")
threading.Thread(target=telegram_listener, daemon=True).start()
while True:

    try:
        check_arbitrage()

    except Exception as e:
        print("Ошибка:", e)

    time.sleep(CHECK_INTERVAL)
