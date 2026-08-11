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

# Пары для мониторинга
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

# Как часто проверять пары
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))

# Комиссия Binance, %
# При необходимости поменяем после проверки твоего аккаунта
BINANCE_FEE = float(os.getenv("BINANCE_FEE", "0.10"))

# Комиссия BingX, %
BINGX_FEE = float(os.getenv("BINGX_FEE", "0.10"))

# Запас на проскальзывание / задержку, %
SAFETY_MARGIN = float(os.getenv("SAFETY_MARGIN", "0.05"))

# Минимальный ЧИСТЫЙ спред,
# при котором отправляем автоматический сигнал
MIN_NET_SPREAD = float(os.getenv("MIN_NET_SPREAD", "0.05"))

# Не присылать один и тот же сигнал слишком часто
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "60"))


# ============================================================
# API
# ============================================================

BINANCE_URL = "https://api.binance.com/api/v3/ticker/bookTicker"

BINGX_URL = (
    "https://open-api.bingx.com/"
    "openApi/spot/v1/ticker/bookTicker"
)


# ============================================================
# ПОЛУЧЕНИЕ СИМВОЛА BINGX
# ============================================================

def get_bingx_symbol(symbol):
    """
    BTCUSDT -> BTC-USDT
    ETHUSDT -> ETH-USDT
    SOLUSDT -> SOL-USDT
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

def get_binance_price(symbol):
    """
    Получает лучший BID и ASK Binance.
    """

    response = requests.get(
        BINANCE_URL,
        params={"symbol": symbol},
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    bid = float(data["bidPrice"])
    ask = float(data["askPrice"])

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            f"Binance returned invalid prices for {symbol}"
        )

    return bid, ask


# ============================================================
# BINGX
# ============================================================

def get_bingx_price(symbol):
    """
    Получает лучший BID и ASK BingX.
    """

    bingx_symbol = get_bingx_symbol(symbol)

    response = requests.get(
        BINGX_URL,
        params={"symbol": bingx_symbol},
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if str(data.get("code", "0")) != "0":
        raise RuntimeError(
            f"BingX API error for {symbol}: {data}"
        )

    result = data.get("data")

    if not result:
        raise RuntimeError(
            f"BingX returned empty data for {symbol}: {data}"
        )

    # BingX иногда возвращает список
    if isinstance(result, list):
        result = result[0]

    bid = float(result["bidPrice"])
    ask = float(result["askPrice"])

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            f"BingX returned invalid prices for {symbol}"
        )

    return bid, ask


# ============================================================
# ПОЛУЧЕНИЕ ВСЕХ ЦЕН
# ============================================================

def get_prices(symbol):
    """
    Получает цены Binance и BingX.
    """

    binance_bid, binance_ask = get_binance_price(symbol)
    bingx_bid, bingx_ask = get_bingx_price(symbol)

    return (
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    )


# ============================================================
# РАСЧЁТ АРБИТРАЖА
# ============================================================

def calculate_arbitrage(
    binance_bid,
    binance_ask,
    bingx_bid,
    bingx_ask
):
    """
    Направление 1:

    Купить Binance ASK
    Продать BingX BID

    Направление 2:

    Купить BingX ASK
    Продать Binance BID
    """

    # --------------------------------------------------------
    # Binance -> BingX
    # --------------------------------------------------------

    gross_1 = (
        (bingx_bid - binance_ask)
        / binance_ask
        * 100
    )

    fees_1 = BINANCE_FEE + BINGX_FEE

    net_1 = (
        gross_1
        - fees_1
        - SAFETY_MARGIN
    )

    # --------------------------------------------------------
    # BingX -> Binance
    # --------------------------------------------------------

    gross_2 = (
        (binance_bid - bingx_ask)
        / bingx_ask
        * 100
    )

    fees_2 = BINANCE_FEE + BINGX_FEE

    net_2 = (
        gross_2
        - fees_2
        - SAFETY_MARGIN
    )

    return {
        "gross_1": gross_1,
        "net_1": net_1,
        "gross_2": gross_2,
        "net_2": net_2,
    }


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
# ФОРМАТ ТЕСТОВОГО СООБЩЕНИЯ
# ============================================================

def format_test_message(
    symbol,
    binance_bid,
    binance_ask,
    bingx_bid,
    bingx_ask,
    result
):
    """
    Формирует подробное сообщение для /test.
    """

    gross_1 = result["gross_1"]
    net_1 = result["net_1"]

    gross_2 = result["gross_2"]
    net_2 = result["net_2"]

    if net_1 >= net_2:
        best_direction = (
            "➡️ Купить Binance → продать BingX"
        )
        best_gross = gross_1
        best_net = net_1
    else:
        best_direction = (
            "➡️ Купить BingX → продать Binance"
        )
        best_gross = gross_2
        best_net = net_2

    if best_net >= MIN_NET_SPREAD:
        status = "🟢 ВЫГОДНЫЙ АРБИТРАЖ"
    else:
        status = "⚪ Возможности нет"

    message = (
        "🧪 ТЕСТ АРБИТРАЖА\n\n"

        f"Пара: {symbol}\n\n"

        f"Binance BID: {binance_bid}\n"
        f"Binance ASK: {binance_ask}\n\n"

        f"BingX BID: {bingx_bid}\n"
        f"BingX ASK: {bingx_ask}\n\n"

        f"Binance → BingX:\n"
        f"Сырой спред: {gross_1:.4f}%\n"
        f"Чистый спред: {net_1:.4f}%\n\n"

        f"BingX → Binance:\n"
        f"Сырой спред: {gross_2:.4f}%\n"
        f"Чистый спред: {net_2:.4f}%\n\n"

        f"Комиссии: {BINANCE_FEE + BINGX_FEE:.4f}%\n"
        f"Запас: {SAFETY_MARGIN:.4f}%\n\n"

        f"{status}\n"
        f"Лучшее направление:\n"
        f"{best_direction}\n"
        f"Сырой спред: {best_gross:.4f}%\n"
        f"Чистый спред: {best_net:.4f}%"
    )

    return message


# ============================================================
# /TEST
# ============================================================

def test_all_pairs():
    """
    Проверяет все пары и отправляет результаты.
    """

    send_telegram(
        "🔎 Проверяю все пары...\n"
        "Это может занять несколько секунд."
    )

    best_opportunity = None

    for symbol in SYMBOLS:

        try:

            (
                binance_bid,
                binance_ask,
                bingx_bid,
                bingx_ask
            ) = get_prices(symbol)

            result = calculate_arbitrage(
                binance_bid,
                binance_ask,
                bingx_bid,
                bingx_ask
            )

            net_1 = result["net_1"]
            net_2 = result["net_2"]

            best_net = max(
                net_1,
                net_2
            )

            if (
                best_opportunity is None
                or best_net > best_opportunity["net"]
            ):
                best_opportunity = {
                    "symbol": symbol,
                    "net": best_net
                }

            message = format_test_message(
                symbol,
                binance_bid,
                binance_ask,
                bingx_bid,
                bingx_ask,
                result
            )

            send_telegram(message)

        except Exception as e:

            send_telegram(
                f"❌ {symbol}\n"
                f"Ошибка: {e}"
            )

    if best_opportunity:

        send_telegram(
            "📊 ИТОГ ПРОВЕРКИ\n\n"
            f"Лучшая пара: "
            f"{best_opportunity['symbol']}\n"
            f"Лучший чистый спред: "
            f"{best_opportunity['net']:.4f}%\n\n"
            f"Минимальный для сигнала: "
            f"{MIN_NET_SPREAD:.4f}%"
        )


# ============================================================
# АВТОМАТИЧЕСКИЙ МОНИТОРИНГ
# ============================================================

def arbitrage_monitor():
    """
    Постоянно проверяет все пары.
    """

    last_alerts = {}

    print("=" * 60)
    print("ARBITRAGE MONITOR STARTED")
    print("=" * 60)

    print(
        "Pairs:",
        ", ".join(SYMBOLS)
    )

    print(
        f"Binance fee: {BINANCE_FEE}%"
    )

    print(
        f"BingX fee: {BINGX_FEE}%"
    )

    print(
        f"Safety margin: {SAFETY_MARGIN}%"
    )

    print(
        f"Minimum NET spread: {MIN_NET_SPREAD}%"
    )

    print(
        f"Check interval: {CHECK_INTERVAL} sec"
    )

    print("=" * 60)

    while True:

        cycle_start = time.time()

        best_symbol = None
        best_net = -999

        for symbol in SYMBOLS:

            try:

                (
                    binance_bid,
                    binance_ask,
                    bingx_bid,
                    bingx_ask
                ) = get_prices(symbol)

                result = calculate_arbitrage(
                    binance_bid,
                    binance_ask,
                    bingx_bid,
                    bingx_ask
                )

                gross_1 = result["gross_1"]
                net_1 = result["net_1"]

                gross_2 = result["gross_2"]
                net_2 = result["net_2"]

                # ------------------------------------------------
                # Ищем лучшую возможность
                # ------------------------------------------------

                if net_1 > best_net:

                    best_net = net_1
                    best_symbol = symbol

                if net_2 > best_net:

                    best_net = net_2
                    best_symbol = symbol

                print(
                    f"{symbol} | "
                    f"S1={gross_1:.4f}% "
                    f"NET1={net_1:.4f}% | "
                    f"S2={gross_2:.4f}% "
                    f"NET2={net_2:.4f}%"
                )

                now = time.time()

                # ------------------------------------------------
                # BINANCE -> BINGX
                # ------------------------------------------------

                if net_1 >= MIN_NET_SPREAD:

                    alert_key = (
                        f"{symbol}_BINANCE_BINGX"
                    )

                    last_time = last_alerts.get(
                        alert_key,
                        0
                    )

                    if (
                        now - last_time
                        >= ALERT_COOLDOWN
                    ):

                        message = (
                            "🚨 ВЫГОДНЫЙ АРБИТРАЖ\n\n"

                            f"Пара: {symbol}\n\n"

                            "➡️ Купить Binance "
                            "→ продать BingX\n\n"

                            f"Binance ASK: "
                            f"{binance_ask}\n"

                            f"BingX BID: "
                            f"{bingx_bid}\n\n"

                            f"Сырой спред: "
                            f"{gross_1:.4f}%\n"

                            f"Комиссии: "
                            f"{BINANCE_FEE + BINGX_FEE:.4f}%\n"

                            f"Запас: "
                            f"{SAFETY_MARGIN:.4f}%\n\n"

                            f"💰 ЧИСТЫЙ СПРЕД: "
                            f"{net_1:.4f}%"
                        )

                        send_telegram(message)

                        last_alerts[
                            alert_key
                        ] = now

                # ------------------------------------------------
                # BINGX -> BINANCE
                # ------------------------------------------------

                if net_2 >= MIN_NET_SPREAD:

                    alert_key = (
                        f"{symbol}_BINGX_BINANCE"
                    )

                    last_time = last_alerts.get(
                        alert_key,
                        0
                    )

                    if (
                        now - last_time
                        >= ALERT_COOLDOWN
                    ):

                        message = (
                            "🚨 ВЫГОДНЫЙ АРБИТРАЖ\n\n"

                            f"Пара: {symbol}\n\n"

                            "➡️ Купить BingX "
                            "→ продать Binance\n\n"

                            f"BingX ASK: "
                            f"{bingx_ask}\n"

                            f"Binance BID: "
                            f"{binance_bid}\n\n"

                            f"Сырой спред: "
                            f"{gross_2:.4f}%\n"

                            f"Комиссии: "
                            f"{BINANCE_FEE + BINGX_FEE:.4f}%\n"

                            f"Запас: "
                            f"{SAFETY_MARGIN:.4f}%\n\n"

                            f"💰 ЧИСТЫЙ СПРЕД: "
                            f"{net_2:.4f}%"
                        )

                        send_telegram(message)

                        last_alerts[
                            alert_key
                        ] = now

            except Exception as e:

                print(
                    f"{symbol} ERROR:",
                    repr(e)
                )

        # --------------------------------------------------------
        # Итог цикла
        # --------------------------------------------------------

        if best_symbol is not None:

            print(
                f"BEST: {best_symbol} "
                f"NET={best_net:.4f}%"
            )

        elapsed = time.time() - cycle_start

        sleep_time = max(
            1,
            CHECK_INTERVAL - elapsed
        )

        time.sleep(sleep_time)


# ============================================================
# TELEGRAM LISTENER
# ============================================================

def telegram_listener():
    """
    Слушает команды Telegram.

    /start
    /test
    """

    if not TELEGRAM_BOT_TOKEN:

        print(
            "TELEGRAM_BOT_TOKEN is not set"
        )

        return

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
                    chat.get(
                        "id",
                        ""
                    )
                )

                text = message.get(
                    "text",
                    ""
                ).strip().lower()

                # ------------------------------------------------
                # Разрешаем команды только своему Telegram
                # ------------------------------------------------

                if (
                    TELEGRAM_CHAT_ID
                    and chat_id
                    != str(TELEGRAM_CHAT_ID)
                ):

                    continue

                # ------------------------------------------------
                # /start
                # ------------------------------------------------

                if text in [
                    "/start",
                    "start"
                ]:

                    send_telegram(
                        "🤖 Binance ↔ BingX "
                        "Arbitrage Bot\n\n"

                        "Мониторинг пар:\n"
                        + "\n".join(
                            f"• {symbol}"
                            for symbol in SYMBOLS
                        )
                        + "\n\n"

                        f"Binance комиссия: "
                        f"{BINANCE_FEE}%\n"

                        f"BingX комиссия: "
                        f"{BINGX_FEE}%\n"

                        f"Запас: "
                        f"{SAFETY_MARGIN}%\n"

                        f"Минимальный чистый "
                        f"спред: "
                        f"{MIN_NET_SPREAD}%\n"

                        f"Проверка каждые: "
                        f"{CHECK_INTERVAL} сек.\n\n"

                        "Команды:\n"
                        "/start — информация\n"
                        "/test — проверить все пары"
                    )

                # ------------------------------------------------
                # /test
                # ------------------------------------------------

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

    print("=" * 60)
    print(
        "BINANCE ↔ BINGX "
        "ARBITRAGE BOT"
    )
    print("=" * 60)

    print(
        "Monitoring:",
        ", ".join(SYMBOLS)
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
        f"Safety margin: "
        f"{SAFETY_MARGIN}%"
    )

    print(
        f"Minimum NET spread: "
        f"{MIN_NET_SPREAD}%"
    )

    print(
        f"Check interval: "
        f"{CHECK_INTERVAL} sec"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # Render Health Server
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
