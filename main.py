import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


# ============================================================
# НАСТРОЙКИ
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Можно задать в Render → Environment
# Например: BTCUSDT, ETHUSDT, PAXGUSDT
SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()

# Минимальный спред для автоматического уведомления
MIN_SPREAD = float(os.getenv("MIN_SPREAD", "0.20"))

# Как часто проверять цены
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))

# Не отправлять одинаковое уведомление слишком часто
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "30"))


BINANCE_URL = "https://api.binance.com/api/v3/ticker/bookTicker"
BINGX_URL = "https://open-api.bingx.com/openApi/spot/v1/ticker/bookTicker"


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_bingx_symbol(symbol):
    """
    BTCUSDT -> BTC-USDT
    ETHUSDT -> ETH-USDT
    PAXGUSDT -> PAXG-USDT
    """

    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USDT"

    if symbol.endswith("USDC"):
        return symbol[:-4] + "-USDC"

    if symbol.endswith("BTC"):
        return symbol[:-3] + "-BTC"

    return symbol


def get_binance_price():
    """
    Получает лучший bid и ask Binance.
    """

    response = requests.get(
        BINANCE_URL,
        params={"symbol": SYMBOL},
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    bid = float(data["bidPrice"])
    ask = float(data["askPrice"])

    return bid, ask


def get_bingx_price():
    """
    Получает лучший bid и ask BingX.
    """

    bingx_symbol = get_bingx_symbol(SYMBOL)

    response = requests.get(
        BINGX_URL,
        params={"symbol": bingx_symbol},
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    # Проверяем ответ BingX
    if str(data.get("code", "0")) != "0":
        raise RuntimeError(
            f"BingX API error: {data}"
        )

    result = data.get("data")

    if not result:
        raise RuntimeError(
            f"BingX returned empty data: {data}"
        )

    bid = float(result["bidPrice"])
    ask = float(result["askPrice"])

    return bid, ask


def get_prices():
    """
    Получает цены обеих бирж.
    """

    binance_bid, binance_ask = get_binance_price()
    bingx_bid, bingx_ask = get_bingx_price()

    return (
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    )


def calculate_spreads(
    binance_bid,
    binance_ask,
    bingx_bid,
    bingx_ask
):
    """
    Считает два направления арбитража.

    Направление 1:
    Купить Binance -> продать BingX

    Направление 2:
    Купить BingX -> продать Binance
    """

    spread_1 = (
        (bingx_bid - binance_ask)
        / binance_ask
        * 100
    )

    spread_2 = (
        (binance_bid - bingx_ask)
        / bingx_ask
        * 100
    )

    return spread_1, spread_2


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    """
    Отправляет сообщение в Telegram.
    """

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set")
        return

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID is not set")
        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        response.raise_for_status()

    except Exception as e:
        print("Telegram send error:", e)


# ============================================================
# ФОРМИРОВАНИЕ ТЕСТОВОГО СООБЩЕНИЯ
# ============================================================

def create_test_message():
    """
    Получает цены и создаёт сообщение для /test.
    """

    (
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    ) = get_prices()

    spread_1, spread_2 = calculate_spreads(
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    )

    if spread_1 >= spread_2:

        message = (
            "🧪 ТЕСТ АРБИТРАЖА\n\n"
            f"Пара: {SYMBOL}\n\n"
            f"Binance ASK: {binance_ask}\n"
            f"BingX BID: {bingx_bid}\n"
            f"Спред: {spread_1:.4f}%\n\n"
            "➡️ Купить Binance → продать BingX\n\n"
            f"Второе направление: {spread_2:.4f}%"
        )

    else:

        message = (
            "🧪 ТЕСТ АРБИТРАЖА\n\n"
            f"Пара: {SYMBOL}\n\n"
            f"BingX ASK: {bingx_ask}\n"
            f"Binance BID: {binance_bid}\n"
            f"Спред: {spread_2:.4f}%\n\n"
            "➡️ Купить BingX → продать Binance\n\n"
            f"Второе направление: {spread_1:.4f}%"
        )

    return message


# ============================================================
# АВТОМАТИЧЕСКИЙ МОНИТОРИНГ
# ============================================================

def arbitrage_monitor():
    """
    Постоянно проверяет цены.
    """

    last_alert_time = 0

    print("Arbitrage monitor started")
    print(f"Symbol: {SYMBOL}")
    print(f"Minimum spread: {MIN_SPREAD}%")
    print(f"Check interval: {CHECK_INTERVAL} sec")

    while True:

        try:

            (
                binance_bid,
                binance_ask,
                bingx_bid,
                bingx_ask
            ) = get_prices()

            spread_1, spread_2 = calculate_spreads(
                binance_bid,
                binance_ask,
                bingx_bid,
                bingx_ask
            )

            print(
                f"{SYMBOL} | "
                f"Binance: bid={binance_bid} ask={binance_ask} | "
                f"BingX: bid={bingx_bid} ask={bingx_ask} | "
                f"Spread1={spread_1:.4f}% | "
                f"Spread2={spread_2:.4f}%"
            )

            now = time.time()

            # ------------------------------------------------
            # BINANCE -> BINGX
            # ------------------------------------------------

            if (
                spread_1 >= MIN_SPREAD
                and now - last_alert_time >= ALERT_COOLDOWN
            ):

                message = (
                    "🚨 АРБИТРАЖ\n\n"
                    f"Пара: {SYMBOL}\n\n"
                    f"Binance ASK: {binance_ask}\n"
                    f"BingX BID: {bingx_bid}\n\n"
                    f"Спред: {spread_1:.4f}%\n\n"
                    "➡️ Купить Binance → продать BingX"
                )

                send_telegram(message)

                last_alert_time = now

            # ------------------------------------------------
            # BINGX -> BINANCE
            # ------------------------------------------------

            elif (
                spread_2 >= MIN_SPREAD
                and now - last_alert_time >= ALERT_COOLDOWN
            ):

                message = (
                    "🚨 АРБИТРАЖ\n\n"
                    f"Пара: {SYMBOL}\n\n"
                    f"BingX ASK: {bingx_ask}\n"
                    f"Binance BID: {binance_bid}\n\n"
                    f"Спред: {spread_2:.4f}%\n\n"
                    "➡️ Купить BingX → продать Binance"
                )

                send_telegram(message)

                last_alert_time = now

        except Exception as e:

            print(
                "Arbitrage monitor error:",
                repr(e)
            )

        time.sleep(CHECK_INTERVAL)


# ============================================================
# TELEGRAM LISTENER
# ============================================================

def telegram_listener():
    """
    Слушает команды Telegram.

    /start
    /test
    """

    offset = None

    print("Telegram listener started")

    while True:

        try:

            url = (
                f"https://api.telegram.org/"
                f"bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            )

            params = {
                "timeout": 30,
                "offset": offset
            }

            response = requests.get(
                url,
                params=params,
                timeout=40
            )

            response.raise_for_status()

            data = response.json()

            if not data.get("ok"):
                raise RuntimeError(
                    f"Telegram API error: {data}"
                )

            for update in data.get("result", []):

                offset = update["update_id"] + 1

                message = update.get("message")

                if not message:
                    continue

                chat = message.get("chat", {})

                chat_id = str(
                    chat.get("id", "")
                )

                text = message.get(
                    "text",
                    ""
                ).strip().lower()

                # Принимаем команды только от своего Telegram
                if (
                    TELEGRAM_CHAT_ID
                    and chat_id != str(TELEGRAM_CHAT_ID)
                ):
                    continue

                # --------------------------------------------
                # /start
                # --------------------------------------------

                if text in ["/start", "start"]:

                    send_telegram(
                        "🤖 Binance ↔ BingX Arbitrage Bot\n\n"
                        f"Пара: {SYMBOL}\n"
                        f"Минимальный спред: {MIN_SPREAD}%\n"
                        f"Проверка каждые: {CHECK_INTERVAL} сек.\n\n"
                        "Команды:\n"
                        "/start — информация о боте\n"
                        "/test — тест цен и спреда"
                    )

                # --------------------------------------------
                # /test
                # --------------------------------------------

                elif text in ["/test", "test"]:

                    try:

                        test_message = create_test_message()

                        send_telegram(
                            test_message
                        )

                    except Exception as e:

                        send_telegram(
                            f"❌ Ошибка теста:\n{e}"
                        )

        except Exception as e:

            print(
                "Telegram listener error:",
                repr(e)
            )

            time.sleep(5)


# ============================================================
# HEALTH SERVER ДЛЯ RENDER
# ============================================================

def run_health_server():

    port = int(
        os.getenv("PORT", "10000")
    )

    class Handler(BaseHTTPRequestHandler):

        def do_GET(self):

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8"
            )

            self.end_headers()

            self.wfile.write(
                b"Binance-BingX arbitrage bot is running"
            )

        def log_message(
            self,
            format,
            *args
        ):
            return

    server = HTTPServer(
        ("0.0.0.0", port),
        Handler
    )

    print(
        f"Health server running on port {port}"
    )

    server.serve_forever()


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    print("=" * 50)
    print("BINANCE ↔ BINGX ARBITRAGE BOT")
    print("=" * 50)

    print(f"Symbol: {SYMBOL}")
    print(f"Minimum spread: {MIN_SPREAD}%")
    print(f"Check interval: {CHECK_INTERVAL} sec")

    # Health server
    health_thread = threading.Thread(
        target=run_health_server,
        daemon=True
    )

    health_thread.start()

    # Telegram listener
    telegram_thread = threading.Thread(
        target=telegram_listener,
        daemon=True
    )

    telegram_thread.start()

    # Основной мониторинг
    arbitrage_monitor()
