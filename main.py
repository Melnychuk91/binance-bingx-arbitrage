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

# ------------------------------------------------------------
# СПИСОК ПАР
# ------------------------------------------------------------

DEFAULT_SYMBOLS = (
    "BTCUSDT,"
    "ETHUSDT,"
    "SOLUSDT,"
    "XRPUSDT,"
    "DOGEUSDT,"
    "BNBUSDT,"
    "ADAUSDT,"
    "AVAXUSDT,"
    "LINKUSDT,"
    "LTCUSDT"
)

SYMBOLS = [
    x.strip().upper()
    for x in os.getenv(
        "SYMBOLS",
        DEFAULT_SYMBOLS
    ).split(",")
    if x.strip()
]


# ------------------------------------------------------------
# МИНИМАЛЬНЫЙ СПРЕД
# ------------------------------------------------------------

MIN_SPREAD = float(
    os.getenv(
        "MIN_SPREAD",
        "0.20"
    )
)


# ------------------------------------------------------------
# ЧАСТОТА ПРОВЕРКИ
# ------------------------------------------------------------

CHECK_INTERVAL = int(
    os.getenv(
        "CHECK_INTERVAL",
        "5"
    )
)


# ------------------------------------------------------------
# ПОВТОРНОЕ УВЕДОМЛЕНИЕ
# ------------------------------------------------------------

ALERT_COOLDOWN = int(
    os.getenv(
        "ALERT_COOLDOWN",
        "30"
    )
)


# ============================================================
# API
# ============================================================

BINANCE_URL = (
    "https://api.binance.com/api/v3/ticker/bookTicker"
)

BINGX_URL = (
    "https://open-api.bingx.com/"
    "openApi/spot/v1/ticker/bookTicker"
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_bingx_symbol(symbol):
    """
    BTCUSDT -> BTC-USDT
    ETHUSDT -> ETH-USDT
    SOLUSDT -> SOL-USDT
    """

    if symbol.endswith("USDT"):
        return (
            symbol[:-4]
            + "-USDT"
        )

    if symbol.endswith("USDC"):
        return (
            symbol[:-4]
            + "-USDC"
        )

    if symbol.endswith("BTC"):
        return (
            symbol[:-3]
            + "-BTC"
        )

    return symbol


# ============================================================
# BINANCE
# ============================================================

def get_binance_price(symbol):
    """
    Получает лучший BID и ASK Binance.
    """

    response = requests.get(
        BINANCE_URL,
        params={
            "symbol": symbol
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if "bidPrice" not in data:
        raise RuntimeError(
            f"Binance unexpected response: {data}"
        )

    bid = float(
        data["bidPrice"]
    )

    ask = float(
        data["askPrice"]
    )

    return bid, ask


# ============================================================
# BINGX
# ============================================================

def get_bingx_price(symbol):
    """
    Получает лучший BID и ASK BingX.

    BingX может возвращать data
    в разных структурах, поэтому
    здесь предусмотрена обработка
    словаря и списка.
    """

    bingx_symbol = get_bingx_symbol(
        symbol
    )

    response = requests.get(
        BINGX_URL,
        params={
            "symbol": bingx_symbol
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    # Проверяем API код
    if str(
        data.get(
            "code",
            "0"
        )
    ) != "0":

        raise RuntimeError(
            f"BingX API error: {data}"
        )

    result = data.get(
        "data"
    )

    if not result:

        raise RuntimeError(
            f"BingX empty data for "
            f"{symbol}: {data}"
        )

    # --------------------------------------------------------
    # Если data является списком
    # --------------------------------------------------------

    if isinstance(
        result,
        list
    ):

        if len(result) == 0:
            raise RuntimeError(
                f"BingX empty list: {data}"
            )

        item = None

        # Ищем нужный символ
        for element in result:

            if not isinstance(
                element,
                dict
            ):
                continue

            element_symbol = str(
                element.get(
                    "symbol",
                    ""
                )
            ).upper()

            if element_symbol in (
                bingx_symbol.upper(),
                symbol.upper()
            ):
                item = element
                break

        # Если конкретный символ
        # не найден — берём первый
        if item is None:
            item = result[0]

        result = item

    # --------------------------------------------------------
    # Проверяем словарь
    # --------------------------------------------------------

    if not isinstance(
        result,
        dict
    ):

        raise RuntimeError(
            f"BingX unexpected data: {data}"
        )

    # --------------------------------------------------------
    # Получаем цены
    # --------------------------------------------------------

    bid_value = result.get(
        "bidPrice"
    )

    ask_value = result.get(
        "askPrice"
    )

    # Некоторые ответы могут
    # использовать bid / ask
    if bid_value is None:
        bid_value = result.get(
            "bid"
        )

    if ask_value is None:
        ask_value = result.get(
            "ask"
        )

    if (
        bid_value is None
        or ask_value is None
    ):

        raise RuntimeError(
            f"BingX price fields "
            f"not found: {result}"
        )

    bid = float(
        bid_value
    )

    ask = float(
        ask_value
    )

    return bid, ask


# ============================================================
# ПОЛУЧЕНИЕ ЦЕН
# ============================================================

def get_prices(symbol):

    binance_bid, binance_ask = (
        get_binance_price(
            symbol
        )
    )

    bingx_bid, bingx_ask = (
        get_bingx_price(
            symbol
        )
    )

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

    # --------------------------------------------------------
    # Купить Binance -> продать BingX
    # --------------------------------------------------------

    spread_1 = (
        (
            bingx_bid
            - binance_ask
        )
        / binance_ask
        * 100
    )

    # --------------------------------------------------------
    # Купить BingX -> продать Binance
    # --------------------------------------------------------

    spread_2 = (
        (
            binance_bid
            - bingx_ask
        )
        / bingx_ask
        * 100
    )

    return (
        spread_1,
        spread_2
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "TELEGRAM_BOT_TOKEN is not set"
        )

        return

    if not TELEGRAM_CHAT_ID:

        print(
            "TELEGRAM_CHAT_ID is not set"
        )

        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendMessage"
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
# ТЕСТ ОДНОЙ ПАРЫ
# ============================================================

def create_test_message(
    symbol
):

    (
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    ) = get_prices(
        symbol
    )

    (
        spread_1,
        spread_2
    ) = calculate_spreads(
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    )

    if spread_1 >= spread_2:

        direction = (
            "➡️ Купить Binance "
            "→ продать BingX"
        )

        best_spread = spread_1

    else:

        direction = (
            "➡️ Купить BingX "
            "→ продать Binance"
        )

        best_spread = spread_2

    message = (
        "🧪 ТЕСТ АРБИТРАЖА\n\n"

        f"Пара: {symbol}\n\n"

        f"Binance BID: "
        f"{binance_bid}\n"

        f"Binance ASK: "
        f"{binance_ask}\n\n"

        f"BingX BID: "
        f"{bingx_bid}\n"

        f"BingX ASK: "
        f"{bingx_ask}\n\n"

        f"Binance → BingX: "
        f"{spread_1:.4f}%\n"

        f"BingX → Binance: "
        f"{spread_2:.4f}%\n\n"

        "Лучшее направление:\n"

        f"{direction}\n"

        f"Спред: "
        f"{best_spread:.4f}%"
    )

    return message


# ============================================================
# TELEGRAM LISTENER
# ============================================================

def telegram_listener():

    offset = None

    print(
        "Telegram listener started"
    )

    while True:

        try:

            if not TELEGRAM_BOT_TOKEN:

                print(
                    "Telegram token missing"
                )

                time.sleep(10)

                continue

            url = (
                "https://api.telegram.org/"
                f"bot{TELEGRAM_BOT_TOKEN}/"
                "getUpdates"
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

            if not data.get(
                "ok"
            ):

                raise RuntimeError(
                    f"Telegram API error: "
                    f"{data}"
                )

            for update in data.get(
                "result",
                []
            ):

                offset = (
                    update["update_id"]
                    + 1
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
                    chat.get(
                        "id",
                        ""
                    )
                )

                text = (
                    message
                    .get(
                        "text",
                        ""
                    )
                    .strip()
                    .lower()
                )

                # ------------------------------------------------
                # Проверяем пользователя
                # ------------------------------------------------

                if (
                    TELEGRAM_CHAT_ID
                    and
                    chat_id
                    != str(
                        TELEGRAM_CHAT_ID
                    )
                ):

                    continue

                # ------------------------------------------------
                # /start
                # ------------------------------------------------

                if text in [
                    "/start",
                    "start"
                ]:

                    symbols_text = (
                        "\n".join(
                            f"• {symbol}"
                            for symbol
                            in SYMBOLS
                        )
                    )

                    send_telegram(
                        "🤖 Binance ↔ BingX "
                        "Arbitrage Bot\n\n"

                        f"Мониторинг пар:\n"
                        f"{symbols_text}\n\n"

                        f"Минимальный спред: "
                        f"{MIN_SPREAD}%\n"

                        f"Проверка каждые: "
                        f"{CHECK_INTERVAL} сек.\n\n"

                        "Команды:\n"
                        "/start — информация\n"
                        "/test — тест всех пар"
                    )

                # ------------------------------------------------
                # /test
                # ------------------------------------------------

                elif text in [
                    "/test",
                    "test"
                ]:

                    send_telegram(
                        "🔎 Проверяю пары...\n"
                        "Это может занять несколько секунд."
                    )

                    for symbol in SYMBOLS:

                        try:

                            test_message = (
                                create_test_message(
                                    symbol
                                )
                            )

                            send_telegram(
                                test_message
                            )

                        except Exception as e:

                            send_telegram(
                                f"❌ {symbol}\n"
                                f"Ошибка: {e}"
                            )

        except Exception as e:

            print(
                "Telegram listener error:",
                repr(e)
            )

            time.sleep(5)


# ============================================================
# АВТОМАТИЧЕСКИЙ МОНИТОРИНГ
# ============================================================

def arbitrage_monitor():

    last_alert_time = {}

    print(
        "Arbitrage monitor started"
    )

    print(
        f"Symbols: {', '.join(SYMBOLS)}"
    )

    print(
        f"Minimum spread: "
        f"{MIN_SPREAD}%"
    )

    print(
        f"Check interval: "
        f"{CHECK_INTERVAL} sec"
    )

    while True:

        for symbol in SYMBOLS:

            try:

                (
                    binance_bid,
                    binance_ask,
                    bingx_bid,
                    bingx_ask
                ) = get_prices(
                    symbol
                )

                (
                    spread_1,
                    spread_2
                ) = calculate_spreads(
                    binance_bid,
                    binance_ask,
                    bingx_bid,
                    bingx_ask
                )

                print(
                    f"{symbol} | "
                    f"Binance "
                    f"{binance_bid}/"
                    f"{binance_ask} | "
                    f"BingX "
                    f"{bingx_bid}/"
                    f"{bingx_ask} | "
                    f"S1="
                    f"{spread_1:.4f}% | "
                    f"S2="
                    f"{spread_2:.4f}%"
                )

                now = time.time()

                last_time = (
                    last_alert_time.get(
                        symbol,
                        0
                    )
                )

                # ------------------------------------------------
                # Binance -> BingX
                # ------------------------------------------------

                if (
                    spread_1
                    >= MIN_SPREAD
                    and
                    now - last_time
                    >= ALERT_COOLDOWN
                ):

                    message = (
                        "🚨 АРБИТРАЖ\n\n"

                        f"Пара: {symbol}\n\n"

                        f"Binance ASK: "
                        f"{binance_ask}\n"

                        f"BingX BID: "
                        f"{bingx_bid}\n\n"

                        f"Спред: "
                        f"{spread_1:.4f}%\n\n"

                        "➡️ Купить Binance "
                        "→ продать BingX"
                    )

                    send_telegram(
                        message
                    )

                    last_alert_time[
                        symbol
                    ] = now

                # ------------------------------------------------
                # BingX -> Binance
                # ------------------------------------------------

                elif (
                    spread_2
                    >= MIN_SPREAD
                    and
                    now - last_time
                    >= ALERT_COOLDOWN
                ):

                    message = (
                        "🚨 АРБИТРАЖ\n\n"

                        f"Пара: {symbol}\n\n"

                        f"BingX ASK: "
                        f"{bingx_ask}\n"

                        f"Binance BID: "
                        f"{binance_bid}\n\n"

                        f"Спред: "
                        f"{spread_2:.4f}%\n\n"

                        "➡️ Купить BingX "
                        "→ продать Binance"
                    )

                    send_telegram(
                        message
                    )

                    last_alert_time[
                        symbol
                    ] = now

            except Exception as e:

                print(
                    f"{symbol} error:",
                    repr(e)
                )

        time.sleep(
            CHECK_INTERVAL
        )


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

            self.send_response(
                200
            )

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

    print(
        "=" * 60
    )

    print(
        "BINANCE ↔ BINGX "
        "ARBITRAGE BOT"
    )

    print(
        "=" * 60
    )

    print(
        f"Symbols: "
        f"{', '.join(SYMBOLS)}"
    )

    print(
        f"Minimum spread: "
        f"{MIN_SPREAD}%"
    )

    print(
        f"Check interval: "
        f"{CHECK_INTERVAL} sec"
    )

    print(
        f"Telegram configured: "
        f"{bool(TELEGRAM_BOT_TOKEN)}"
    )

    print(
        f"Chat ID configured: "
        f"{bool(TELEGRAM_CHAT_ID)}"
    )

    # --------------------------------------------------------
    # Health server
    # --------------------------------------------------------

    health_thread = threading.Thread(
        target=run_health_server,
        daemon=True
    )

    health_thread.start()

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    telegram_thread = threading.Thread(
        target=telegram_listener,
        daemon=True
    )

    telegram_thread.start()

    # --------------------------------------------------------
    # Основной мониторинг
    # --------------------------------------------------------

    arbitrage_monitor()
