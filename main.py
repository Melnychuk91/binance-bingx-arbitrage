import os
import time
import requests
import ccxt

# =========================
# НАСТРОЙКИ
# =========================

SYMBOL = "BTC/USDT"
MIN_SPREAD = 0.30          # минимальная разница в %
CHECK_INTERVAL = 10        # проверка каждые 10 секунд

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


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
# ЗАПУСК
# =========================

print("🚀 Binance ↔ BingX Arbitrage Scanner запущен")
print(f"Пара: {SYMBOL}")
print(f"Минимальный спред: {MIN_SPREAD}%")

while True:

    try:
        check_arbitrage()

    except Exception as e:
        print("Ошибка:", e)

    time.sleep(CHECK_INTERVAL)
