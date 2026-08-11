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

SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()

MIN_SPREAD = float(os.getenv("MIN_SPREAD", "0.20"))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))

ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "30"))


# ============================================================
# API
# ============================================================

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


# ============================================================
# BINANCE
# ============================================================

def get_binance_price():
    """
    Получает лучший BID и ASK Binance.
    """

    response = requests.get(
        BINANCE_URL,
        params={
            "symbol": SYMBOL
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Binance returned unexpected data: {data}"
        )

    if "bidPrice" not in data or "askPrice" not in data:
        raise RuntimeError(
            f"Binance price fields missing: {data}"
        )

    bid = float(data["bidPrice"])
    ask = float(data["askPrice"])

    return bid, ask


# ============================================================
# BINGX
# ============================================================

def get_bingx_price():
    """
    Получает лучший BID и ASK BingX.

    BingX может возвращать data как:
    - словарь
    - список словарей

    Поэтому обрабатываем оба варианта.
    """

    bingx_symbol = get_bingx_symbol(SYMBOL)

    response = requests.get(
        BINGX_URL,
        params={
            "symbol": bingx_symbol
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            f"BingX returned unexpected response: {data}"
        )

    # Проверяем код API
    code = str(data.get("code", "0"))

    if code != "0":
        raise RuntimeError(
            f"BingX API error: {data}"
        )

    result = data.get("data")

    if result is None:
        raise RuntimeError(
            f"BingX returned no data: {data}"
        )

    # --------------------------------------------------------
    # ВАРИАНТ 1: data = словарь
    # --------------------------------------------------------

    if isinstance(result, dict):

        if (
            "bidPrice" in result
            and "askPrice" in result
        ):

            bid = float(result["bidPrice"])
            ask = float(result["askPrice"])

            return bid, ask

        # Иногда данные могут лежать внутри symbol
        if "data" in result:

            nested = result["data"]

            if isinstance(nested, dict):

                if (
                    "bidPrice" in nested
                    and "askPrice" in nested
                ):

                    bid = float(nested["bidPrice"])
                    ask = float(nested["askPrice"])

                    return bid, ask

    # --------------------------------------------------------
    # ВАРИАНТ 2: data = список
    # --------------------------------------------------------

    if isinstance(result, list):

        if len(result) == 0:
            raise RuntimeError(
                f"BingX returned empty list: {data}"
            )

        # Ищем нужный торговый символ
        for item in result:

            if not isinstance(item, dict):
                continue

            item_symbol = str(
                item.get("symbol", "")
            ).upper()

            if (
                item_symbol == bingx_symbol.upper()
                or item_symbol == SYMBOL.upper()
            ):

                if (
                    "bidPrice" in item
                    and "askPrice" in item
                ):

                    bid = float(item["bidPrice"])
                    ask = float(item["askPrice"])

                    return bid, ask

        # Если символ не найден,
        # пробуем первый элемент списка

        first = result[0]

        if isinstance(first, dict):

            if (
                "bidPrice" in first
                and "askPrice" in first
            ):

                bid = float(first["bidPrice"])
                ask = float(first["askPrice"])

                return bid, ask

    # --------------------------------------------------------
    # Если формат неизвестен
    # --------------------------------------------------------

    raise RuntimeError(
        f"Cannot parse BingX price response: {data}"
    )


# ============================================================
# ОБЩИЕ ЦЕНЫ
# ============================================================

def get_prices():

    binance_bid, binance_ask = get_binance_price()

    bingx_bid, bingx_ask = get_bingx_price()

    return (
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    )


# ============================================================
# РАСЧЁТ СПРЕДА
# ============================================================

def calculate_spreads(
    binance_bid,
    binance_ask,
    bingx_bid,
    bingx_ask
):

    # Купить Binance -> продать BingX

    spread_1 = (
        (bingx_bid - binance_ask)
        / binance_ask
        * 100
    )

    # Купить BingX -> продать Binance

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

        print(
            "Telegram send error:",
            repr(e)
        )


# ============================================================
# /TEST
# ============================================================

def create_test_message():

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

        direction = (
            "➡️ Купить Binance → "
            "продать BingX"
        )

        best_spread = spread_1

    else:

        direction = (
            "➡️ Купить BingX → "
            "продать Binance"
        )

        best_spread = spread_2

    message = (
        "🧪 ТЕСТ АРБИТРАЖА\n\n"
        f"Пара: {SYMBOL}\n\n"

        f"Binance BID: {binance_bid}\n"
        f"Binance ASK: {binance_ask}\n\n"

        f"BingX BID: {bingx_bid}\n"
        f"BingX ASK: {bingx_ask}\n\n"

        f"Binance → BingX: {spread_1:.4f}%\n"
        f"BingX → Binance: {spread_2:.4f}%\n\n"

        f"Лучшее направление:\n"
        f"{direction}\n"
        f"Спред: {best_spread:.4f}%"
    )

    return message


# ============================================================
# АВТОМАТИЧЕСКИЙ МОНИТОРИНГ
# ============================================================

def arbitrage_monitor():

    last_alert_time = 0

    print("Arbitrage monitor started")
    print(f"Symbol: {SYMBOL}")
    print(f"Minimum spread: {MIN_SPREAD}%")
    print(
        f"Check interval: "
        f"{CHECK_INTERVAL} sec"
    )

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
                f"Binance "
                f"bid={binance_bid} "
                f"ask={binance_ask} | "
                f"BingX "
                f"bid={bingx_bid} "
                f"ask={bingx_ask} | "
                f"Spread1={spread_1:.4f}% | "
                f"Spread2={spread_2:.4f}%"
            )

            now = time.time()

            # ------------------------------------------------
            # BINANCE -> BINGX
            # ------------------------------------------------

            if (
                spread_1 >= MIN_SPREAD
                and
                now - last_alert_time
                >= ALERT_COOLDOWN
            ):

                message = (
                    "🚨 АРБИТРАЖ\n\n"
                    f"Пара: {SYMBOL}\n\n"

                    f"Binance ASK: "
                    f"{binance_ask}\n"

                    f"BingX BID: "
                    f"{bingx_bid}\n\n"

                    f"Спред: "
                    f"{spread_1:.4f}%\n\n"

                    "➡️ Купить Binance → "
                    "продать BingX"
                )

                send_telegram(message)

                last_alert_time = now

            # ------------------------------------------------
            # BINGX -> BINANCE
            # ------------------------------------------------

            elif (
                spread_2 >= MIN_SPREAD
                and
                now - last_alert_time
                >= ALERT_COOLDOWN
            ):

                message = (
                    "🚨 АРБИТРАЖ\n\n"
                    f"Пара: {SYMBOL}\n\n"

                    f"BingX ASK: "
                    f"{bingx_ask}\n"

                    f"Binance BID: "
                    f"{binance_bid}\n\n"

                    f"Спред: "
                    f"{spread_2:.4f}%\n\n"

                    "➡️ Купить BingX → "
                    "продать Binance"
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

            for update in data.get(
                "result",
                []
            ):

                offset = (
                    update["update_id"] + 1
                )

                message = update.get(
                    "message"
                )

                if not message:
                    continue

                chat = message.get(
                    "chat",
                    {}
                )

                chat_id = str(
                    chat.get("id", "")
                )

                text = message.get(
                    "text",
                    ""
                ).strip().lower()

                # Только твой Telegram
                if (
                    TELEGRAM_CHAT_ID
                    and
                    chat_id !=
                    str(TELEGRAM_CHAT_ID)
                ):
                    continue

                # ------------------------------------------------
                # /START
                # ------------------------------------------------

                if text in [
                    "/start",
                    "start"
                ]:

                    send_telegram(
                        "🤖 Binance ↔ BingX "
                        "Arbitrage Bot\n\n"

                        f"Пара: {SYMBOL}\n"

                        f"Минимальный спред: "
                        f"{MIN_SPREAD}%\n"

                        f"Проверка каждые: "
                        f"{CHECK_INTERVAL} сек.\n\n"

                        "Команды:\n"
                        "/start — информация о боте\n"
                        "/test — тест цен и спреда"
                    )

                # ------------------------------------------------
                # /TEST
                # ------------------------------------------------

                elif text in [
                    "/test",
                    "test"
                ]:

                    try:

                        test_message = (
                            create_test_message()
                        )

                        send_telegram(
                            test_message
                        )

                    except Exception as e:

                        send_telegram(
                            "❌ Ошибка теста:\n"
                            f"{e}"
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
        os.getenv(
            "PORT",
            "10000"
        )
    )

    class Handler(
        BaseHTTPRequestHandler
    ):

        def do_GET(self):

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain; "
                "charset=utf-8"
            )

            self.end_headers()

            self.wfile.write(
                b"Binance-BingX "
                b"arbitrage bot is running"
            )

        def log_message(
            self,
            format,
            *args
        ):

            return

    server = HTTPServer(
        (
            "0.0.0.0",
            port
        ),
        Handler
    )

    print(
        f"Health server running "
        f"on port {port}"
    )

    server.serve_forever()


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    print("=" * 50)
    print(
        "BINANCE ↔ BINGX "
        "ARBITRAGE BOT"
    )
    print("=" * 50)

    print(
        f"Symbol: {SYMBOL}"
    )

    print(
        f"Minimum spread: "
        f"{MIN_SPREAD}%"
    )

    print(
        f"Check interval: "
        f"{CHECK_INTERVAL} sec"
    )

    # --------------------------------------------------------
    # HEALTH SERVER
    # --------------------------------------------------------

    health_thread = threading.Thread(
        target=run_health_server,
        daemon=True
    )

    health_thread.start()

    # --------------------------------------------------------
    # TELEGRAM LISTENER
    # --------------------------------------------------------

    telegram_thread = threading.Thread(
        target=telegram_listener,
        daemon=True
    )

    telegram_thread.start()

    # --------------------------------------------------------
    # ARBITRAGE MONITOR
    # --------------------------------------------------------

    arbitrage_monitor()
