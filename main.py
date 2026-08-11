import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


# ============================================================
# НАСТРОЙКИ
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# ПАРЫ ДЛЯ МОНИТОРИНГА
# ============================================================

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "LTCUSDT",
]


# ============================================================
# ФИЛЬТР ВЫГОДНОГО АРБИТРАЖА
# ============================================================

# Минимальный сырой спред
MIN_SPREAD = float(
    os.getenv(
        "MIN_SPREAD",
        "0.35"
    )
)

# Комиссия Binance
BINANCE_FEE = float(
    os.getenv(
        "BINANCE_FEE",
        "0.10"
    )
)

# Комиссия BingX
BINGX_FEE = float(
    os.getenv(
        "BINGX_FEE",
        "0.10"
    )
)

# Запас на проскальзывание
SLIPPAGE_BUFFER = float(
    os.getenv(
        "SLIPPAGE_BUFFER",
        "0.05"
    )
)

# Минимальный чистый спред
MIN_NET_SPREAD = float(
    os.getenv(
        "MIN_NET_SPREAD",
        "0.10"
    )
)


# ============================================================
# ЧАСТОТА ПРОВЕРКИ
# ============================================================

CHECK_INTERVAL = int(
    os.getenv(
        "CHECK_INTERVAL",
        "5"
    )
)

# Один и тот же сигнал не чаще этого времени
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
# ПРЕОБРАЗОВАНИЕ СИМВОЛА
# ============================================================

def get_bingx_symbol(symbol):

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
# BINANCE PRICE
# ============================================================

def get_binance_price(symbol):

    response = requests.get(
        BINANCE_URL,
        params={
            "symbol": symbol
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Unexpected Binance response: {data}"
        )

    if "bidPrice" not in data:
        raise RuntimeError(
            f"Binance response has no bidPrice: {data}"
        )

    if "askPrice" not in data:
        raise RuntimeError(
            f"Binance response has no askPrice: {data}"
        )

    bid = float(
        data["bidPrice"]
    )

    ask = float(
        data["askPrice"]
    )

    return bid, ask


# ============================================================
# BINGX PRICE
# ============================================================

def get_bingx_price(symbol):

    bingx_symbol = (
        get_bingx_symbol(symbol)
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

    print(
        f"BingX raw response "
        f"{symbol}: {data}"
    )

    # --------------------------------------------------------
    # Проверяем API code
    # --------------------------------------------------------

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

    if result is None:
        raise RuntimeError(
            f"BingX returned no data: {data}"
        )

    # --------------------------------------------------------
    # ВАЖНО:
    # BingX может вернуть LIST
    # --------------------------------------------------------

    if isinstance(
        result,
        list
    ):

        if len(result) == 0:
            raise RuntimeError(
                f"BingX returned empty list: {data}"
            )

        result = result[0]

    # --------------------------------------------------------
    # Иногда API может вернуть словарь,
    # внутри которого снова находится список
    # --------------------------------------------------------

    if isinstance(
        result,
        dict
    ):

        if (
            "bidPrice" not in result
            or "askPrice" not in result
        ):

            possible_list = (
                result.get("data")
                or result.get("list")
                or result.get("ticker")
            )

            if isinstance(
                possible_list,
                list
            ):

                if len(possible_list) == 0:
                    raise RuntimeError(
                        f"BingX empty nested list: {data}"
                    )

                result = possible_list[0]

    # --------------------------------------------------------
    # После всех преобразований должен быть словарь
    # --------------------------------------------------------

    if not isinstance(
        result,
        dict
    ):

        raise RuntimeError(
            "Unexpected BingX data format: "
            f"{type(result).__name__} | {result}"
        )

    if "bidPrice" not in result:

        raise RuntimeError(
            f"BingX response has no bidPrice: "
            f"{result}"
        )

    if "askPrice" not in result:

        raise RuntimeError(
            f"BingX response has no askPrice: "
            f"{result}"
        )

    bid = float(
        result["bidPrice"]
    )

    ask = float(
        result["askPrice"]
    )

    return bid, ask


# ============================================================
# SPREAD
# ============================================================

def calculate_spreads(
    binance_bid,
    binance_ask,
    bingx_bid,
    bingx_ask
):

    # Binance -> BingX
    spread_1 = (
        (
            bingx_bid
            - binance_ask
        )
        / binance_ask
        * 100
    )

    # BingX -> Binance
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
# ЧИСТЫЙ СПРЕД
# ============================================================

def calculate_net_spread(
    raw_spread
):

    total_cost = (
        BINANCE_FEE
        + BINGX_FEE
        + SLIPPAGE_BUFFER
    )

    return (
        raw_spread
        - total_cost
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    message
):

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
# ТЕСТ ОДНОЙ ПАРЫ
# ============================================================

def create_test_message(
    symbol
):

    (
        binance_bid,
        binance_ask
    ) = get_binance_price(
        symbol
    )

    (
        bingx_bid,
        bingx_ask
    ) = get_bingx_price(
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

    net_1 = calculate_net_spread(
        spread_1
    )

    net_2 = calculate_net_spread(
        spread_2
    )

    if spread_1 >= spread_2:

        direction = (
            "➡️ Купить Binance "
            "→ продать BingX"
        )

        best_spread = spread_1
        best_net = net_1

    else:

        direction = (
            "➡️ Купить BingX "
            "→ продать Binance"
        )

        best_spread = spread_2
        best_net = net_2

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

        f"Лучшее направление:\n"
        f"{direction}\n\n"

        f"Сырой спред: "
        f"{best_spread:.4f}%\n"

        f"Комиссии: "
        f"{BINANCE_FEE + BINGX_FEE:.4f}%\n"

        f"Запас: "
        f"{SLIPPAGE_BUFFER:.4f}%\n"

        f"Ориентировочно чистыми: "
        f"{best_net:.4f}%"
    )

    return message


# ============================================================
# TEST ВСЕХ ПАР
# ============================================================

def test_all_pairs():

    send_telegram(
        "🔎 Проверяю все пары...\n"
        "Это может занять несколько секунд."
    )

    for symbol in SYMBOLS:

        try:

            message = (
                create_test_message(
                    symbol
                )
            )

            send_telegram(
                message
            )

        except Exception as e:

            send_telegram(
                f"❌ {symbol}\n"
                f"Ошибка: {e}"
            )

        time.sleep(0.3)


# ============================================================
# МОНИТОРИНГ
# ============================================================

def arbitrage_monitor():

    last_alerts = {}

    print(
        "=" * 60
    )

    print(
        "ARBITRAGE MONITOR STARTED"
    )

    print(
        "=" * 60
    )

    print(
        "Pairs:",
        ", ".join(SYMBOLS)
    )

    print(
        f"Minimum raw spread: "
        f"{MIN_SPREAD}%"
    )

    print(
        f"Binance fee: "
        f"{BINANCE_FEE}%"
    )

    print(
        f"BingX fee: "
        f"{BINGX_FEE}%"
    )

    print(
        f"Slippage buffer: "
        f"{SLIPPAGE_BUFFER}%"
    )

    print(
        f"Minimum net spread: "
        f"{MIN_NET_SPREAD}%"
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
                    binance_ask
                ) = get_binance_price(
                    symbol
                )

                (
                    bingx_bid,
                    bingx_ask
                ) = get_bingx_price(
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

                net_1 = (
                    calculate_net_spread(
                        spread_1
                    )
                )

                net_2 = (
                    calculate_net_spread(
                        spread_2
                    )
                )

                print(
                    f"{symbol} | "
                    f"S1={spread_1:.4f}% "
                    f"NET1={net_1:.4f}% | "
                    f"S2={spread_2:.4f}% "
                    f"NET2={net_2:.4f}%"
                )

                now = time.time()

                # ==================================================
                # BINANCE -> BINGX
                # ==================================================

                if (
                    spread_1 >= MIN_SPREAD
                    and net_1 >= MIN_NET_SPREAD
                ):

                    key = (
                        f"{symbol}_BINANCE_BINGX"
                    )

                    last_time = (
                        last_alerts.get(
                            key,
                            0
                        )
                    )

                    if (
                        now - last_time
                        >= ALERT_COOLDOWN
                    ):

                        message = (
                            "🚨 ВЫГОДНЫЙ АРБИТРАЖ\n\n"

                            f"Пара: {symbol}\n\n"

                            "🟢 Направление:\n"
                            "➡️ Купить Binance "
                            "→ продать BingX\n\n"

                            f"Binance ASK: "
                            f"{binance_ask}\n"

                            f"BingX BID: "
                            f"{bingx_bid}\n\n"

                            f"Сырой спред: "
                            f"{spread_1:.4f}%\n"

                            f"Комиссии: "
                            f"{BINANCE_FEE + BINGX_FEE:.4f}%\n"

                            f"Запас: "
                            f"{SLIPPAGE_BUFFER:.4f}%\n"

                            f"Чистый спред: "
                            f"{net_1:.4f}%\n\n"

                            "⚠️ Только сигнал. "
                            "Сделки автоматически "
                            "не совершаются."
                        )

                        send_telegram(
                            message
                        )

                        last_alerts[
                            key
                        ] = now

                # ==================================================
                # BINGX -> BINANCE
                # ==================================================

                if (
                    spread_2 >= MIN_SPREAD
                    and net_2 >= MIN_NET_SPREAD
                ):

                    key = (
                        f"{symbol}_BINGX_BINANCE"
                    )

                    last_time = (
                        last_alerts.get(
                            key,
                            0
                        )
                    )

                    if (
                        now - last_time
                        >= ALERT_COOLDOWN
                    ):

                        message = (
                            "🚨 ВЫГОДНЫЙ АРБИТРАЖ\n\n"

                            f"Пара: {symbol}\n\n"

                            "🟢 Направление:\n"
                            "➡️ Купить BingX "
                            "→ продать Binance\n\n"

                            f"BingX ASK: "
                            f"{bingx_ask}\n"

                            f"Binance BID: "
                            f"{binance_bid}\n\n"

                            f"Сырой спред: "
                            f"{spread_2:.4f}%\n"

                            f"Комиссии: "
                            f"{BINANCE_FEE + BINGX_FEE:.4f}%\n"

                            f"Запас: "
                            f"{SLIPPAGE_BUFFER:.4f}%\n"

                            f"Чистый спред: "
                            f"{net_2:.4f}%\n\n"

                            "⚠️ Только сигнал. "
                            "Сделки автоматически "
                            "не совершаются."
                        )

                        send_telegram(
                            message
                        )

                        last_alerts[
                            key
                        ] = now

            except Exception as e:

                print(
                    f"{symbol} ERROR:",
                    repr(e)
                )

        time.sleep(
            CHECK_INTERVAL
        )


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

            url = (
                "https://api.telegram.org/"
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

                message = (
                    update.get(
                        "message"
                    )
                )

                if not message:
                    continue

                chat = (
                    message.get(
                        "chat",
                        {}
                    )
                )

                chat_id = str(
                    chat.get(
                        "id",
                        ""
                    )
                )

                text = (
                    message.get(
                        "text",
                        ""
                    )
                    .strip()
                    .lower()
                )

                # Только наш Telegram
                if (
                    TELEGRAM_CHAT_ID
                    and chat_id
                    != str(
                        TELEGRAM_CHAT_ID
                    )
                ):
                    continue

                # ==================================================
                # START
                # ==================================================

                if text in [
                    "/start",
                    "start"
                ]:

                    send_telegram(
                        "🤖 Binance ↔ BingX "
                        "Arbitrage Bot\n\n"

                        "Мониторинг пар:\n"

                        + "\n".join(
                            [
                                f"• {symbol}"
                                for symbol
                                in SYMBOLS
                            ]
                        )

                        + "\n\n"

                        f"Минимальный сырой "
                        f"спред: {MIN_SPREAD}%\n"

                        f"Минимальный чистый "
                        f"спред: {MIN_NET_SPREAD}%\n"

                        f"Проверка каждые: "
                        f"{CHECK_INTERVAL} сек.\n\n"

                        "Команды:\n"

                        "/start — информация\n"

                        "/test — "
                        "проверить все пары"
                    )

                # ==================================================
                # TEST
                # ==================================================

                elif text in [
                    "/test",
                    "test"
                ]:

                    try:

                        test_all_pairs()

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

        def do_GET(
            self
        ):

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
        f"Monitoring "
        f"{len(SYMBOLS)} pairs"
    )

    # Health server
    health_thread = (
        threading.Thread(
            target=run_health_server,
            daemon=True
        )
    )

    health_thread.start()

    # Telegram listener
    telegram_thread = (
        threading.Thread(
            target=telegram_listener,
            daemon=True
        )
    )

    telegram_thread.start()

    # Основной мониторинг
    arbitrage_monitor()
