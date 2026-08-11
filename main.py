import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# НАСТРОЙКИ
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Проверяем каждые 10 секунд
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "10"))

# Комиссии
BINANCE_FEE = float(os.getenv("BINANCE_FEE", "0.10"))
BINGX_FEE = float(os.getenv("BINGX_FEE", "0.10"))

# Дополнительный запас на проскальзывание
SAFETY_MARGIN = float(os.getenv("SAFETY_MARGIN", "0.05"))

# Минимальный чистый спред для уведомления
MIN_NET_SPREAD = float(os.getenv("MIN_NET_SPREAD", "0.30"))

# Не повторять одинаковый сигнал слишком часто
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "30"))

# Сколько потоков одновременно проверяет пары
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))


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

    "DOTUSDT",
    "TRXUSDT",
    "TONUSDT",
    "SUIUSDT",
    "NEARUSDT",
    "APTUSDT",
    "OPUSDT",
    "ARBUSDT",
    "UNIUSDT",
    "SHIBUSDT",

    "PEPEUSDT",
    "FILUSDT",
    "ATOMUSDT",
    "ETCUSDT",
    "BCHUSDT",
    "INJUSDT",
    "SEIUSDT",
    "AAVEUSDT",
    "ALGOUSDT",
    "XLMUSDT",

    "HBARUSDT",
    "ICPUSDT",
    "MATICUSDT",
    "VETUSDT",
    "EOSUSDT"
]


# ============================================================
# API
# ============================================================

BINANCE_URL = "https://api.binance.com/api/v3/ticker/bookTicker"

BINGX_URL = (
    "https://open-api.bingx.com/"
    "openApi/spot/v1/ticker/bookTicker"
)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Binance-BingX-Arbitrage-Bot/1.0"
})


# ============================================================
# BINGX SYMBOL
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
    Получает BID и ASK Binance.
    """

    response = session.get(
        BINANCE_URL,
        params={
            "symbol": symbol
        },
        timeout=8
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Binance returned unexpected data: {data}"
        )

    if "bidPrice" not in data or "askPrice" not in data:
        raise RuntimeError(
            f"Binance missing price data: {data}"
        )

    bid = float(data["bidPrice"])
    ask = float(data["askPrice"])

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            f"Invalid Binance prices: {data}"
        )

    return bid, ask


# ============================================================
# BINGX
# ============================================================

def get_bingx_price(symbol):
    """
    Получает BID и ASK BingX.

    BingX иногда возвращает data как список:
    [
        {
            "symbol": "BTC-USDT",
            "bidPrice": "...",
            "askPrice": "..."
        }
    ]

    Поэтому здесь специально обработаны оба варианта.
    """

    bingx_symbol = get_bingx_symbol(symbol)

    response = session.get(
        BINGX_URL,
        params={
            "symbol": bingx_symbol
        },
        timeout=8
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            f"BingX returned unexpected data: {data}"
        )

    code = str(data.get("code", "0"))

    if code != "0":
        raise RuntimeError(
            f"BingX API error: {data}"
        )

    result = data.get("data")

    if not result:
        raise RuntimeError(
            f"BingX returned empty data: {data}"
        )

    # --------------------------------------------------------
    # ВАЖНО:
    # BingX может вернуть список
    # --------------------------------------------------------

    if isinstance(result, list):

        if len(result) == 0:
            raise RuntimeError(
                f"BingX returned empty list: {data}"
            )

        result = result[0]

    # Иногда data может быть словарём
    elif isinstance(result, dict):

        # Если внутри есть список
        if "data" in result and isinstance(
            result["data"],
            list
        ):

            if len(result["data"]) == 0:
                raise RuntimeError(
                    f"BingX returned empty nested list: {data}"
                )

            result = result["data"][0]

    else:

        raise RuntimeError(
            f"Unknown BingX data format: {data}"
        )

    if not isinstance(result, dict):
        raise RuntimeError(
            f"BingX invalid result: {result}"
        )

    if (
        "bidPrice" not in result
        or "askPrice" not in result
    ):
        raise RuntimeError(
            f"BingX missing bid/ask: {result}"
        )

    bid = float(result["bidPrice"])
    ask = float(result["askPrice"])

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            f"Invalid BingX prices: {result}"
        )

    return bid, ask


# ============================================================
# ПОЛУЧЕНИЕ ЦЕН
# ============================================================

def get_prices(symbol):

    binance_bid, binance_ask = (
        get_binance_price(symbol)
    )

    bingx_bid, bingx_ask = (
        get_bingx_price(symbol)
    )

    return (
        binance_bid,
        binance_ask,
        bingx_bid,
        bingx_ask
    )


# ============================================================
# РАСЧЁТ СПРЕДОВ
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

    spread_binance_to_bingx = (
        (
            bingx_bid - binance_ask
        )
        / binance_ask
        * 100
    )

    # --------------------------------------------------------
    # BingX -> Binance
    # --------------------------------------------------------

    spread_bingx_to_binance = (
        (
            binance_bid - bingx_ask
        )
        / bingx_ask
        * 100
    )

    # --------------------------------------------------------
    # Общие расходы
    # --------------------------------------------------------

    total_cost = (
        BINANCE_FEE
        + BINGX_FEE
        + SAFETY_MARGIN
    )

    # --------------------------------------------------------
    # Чистые спреды
    # --------------------------------------------------------

    net_1 = (
        spread_binance_to_bingx
        - total_cost
    )

    net_2 = (
        spread_bingx_to_binance
        - total_cost
    )

    return {
        "spread_1": spread_binance_to_bingx,
        "spread_2": spread_bingx_to_binance,
        "net_1": net_1,
        "net_2": net_2,
        "total_cost": total_cost
    }


# ============================================================
# ПРОВЕРКА ОДНОЙ ПАРЫ
# ============================================================

def check_symbol(symbol):

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

        spread_1 = result["spread_1"]
        spread_2 = result["spread_2"]

        net_1 = result["net_1"]
        net_2 = result["net_2"]

        # ----------------------------------------------------
        # Лучшее направление
        # ----------------------------------------------------

        if net_1 >= net_2:

            direction = (
                "Купить Binance → "
                "продать BingX"
            )

            best_raw = spread_1
            best_net = net_1

            buy_exchange = "Binance"
            sell_exchange = "BingX"

        else:

            direction = (
                "Купить BingX → "
                "продать Binance"
            )

            best_raw = spread_2
            best_net = net_2

            buy_exchange = "BingX"
            sell_exchange = "Binance"

        return {
            "symbol": symbol,

            "binance_bid": binance_bid,
            "binance_ask": binance_ask,

            "bingx_bid": bingx_bid,
            "bingx_ask": bingx_ask,

            "spread_1": spread_1,
            "spread_2": spread_2,

            "net_1": net_1,
            "net_2": net_2,

            "best_raw": best_raw,
            "best_net": best_net,

            "direction": direction,

            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,

            "error": None
        }

    except Exception as e:

        return {
            "symbol": symbol,
            "error": str(e)
        }


# ============================================================
# ПРОВЕРКА ВСЕХ ПАР
# ============================================================

def scan_all_pairs():

    results = []

    print(
        f"Scanning {len(SYMBOLS)} pairs..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                check_symbol,
                symbol
            ): symbol

            for symbol in SYMBOLS
        }

        for future in as_completed(futures):

            symbol = futures[future]

            try:

                result = future.result()

                if result.get("error") is None:

                    results.append(result)

            except Exception as e:

                print(
                    f"{symbol} future error: {e}"
                )

    return results


# ============================================================
# ЛУЧШАЯ ВОЗМОЖНОСТЬ
# ============================================================

def get_best_opportunity(results):

    if not results:
        return None

    return max(
        results,
        key=lambda x: x["best_net"]
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN is not set"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_CHAT_ID is not set"
        )
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=10
        )

        response.raise_for_status()

        return True

    except Exception as e:

        print(
            "Telegram send error:",
            repr(e)
        )

        return False


# ============================================================
# ФОРМАТИРОВАНИЕ СИГНАЛА
# ============================================================

def format_opportunity(
    opportunity,
    is_alert=False
):

    symbol = opportunity["symbol"]

    direction = opportunity["direction"]

    raw = opportunity["best_raw"]

    net = opportunity["best_net"]

    buy_exchange = (
        opportunity["buy_exchange"]
    )

    sell_exchange = (
        opportunity["sell_exchange"]
    )

    binance_bid = (
        opportunity["binance_bid"]
    )

    binance_ask = (
        opportunity["binance_ask"]
    )

    bingx_bid = (
        opportunity["bingx_bid"]
    )

    bingx_ask = (
        opportunity["bingx_ask"]
    )

    if is_alert:

        title = "🚨 ВЫГОДНЫЙ АРБИТРАЖ"

    else:

        title = "🧪 ТЕКУЩАЯ ЛУЧШАЯ ВОЗМОЖНОСТЬ"

    message = (
        f"{title}\n\n"

        f"💎 Пара: {symbol}\n\n"

        f"➡️ {direction}\n\n"

        f"🟡 Купить: {buy_exchange}\n"
        f"🔵 Продать: {sell_exchange}\n\n"

        f"Binance BID: {binance_bid}\n"
        f"Binance ASK: {binance_ask}\n\n"

        f"BingX BID: {bingx_bid}\n"
        f"BingX ASK: {bingx_ask}\n\n"

        f"📊 Сырой спред: "
        f"{raw:+.4f}%\n"

        f"💸 Binance комиссия: "
        f"{BINANCE_FEE:.4f}%\n"

        f"💸 BingX комиссия: "
        f"{BINGX_FEE:.4f}%\n"

        f"🛡 Запас: "
        f"{SAFETY_MARGIN:.4f}%\n\n"

        f"💰 ЧИСТЫЙ СПРЕД: "
        f"{net:+.4f}%"
    )

    return message


# ============================================================
# /TEST
# ============================================================

def create_test_message():

    results = scan_all_pairs()

    if not results:

        return (
            "❌ Не удалось получить цены "
            "ни по одной паре."
        )

    best = get_best_opportunity(
        results
    )

    message = format_opportunity(
        best,
        is_alert=False
    )

    message += (
        "\n\n"
        f"🔎 Проверено пар: "
        f"{len(results)}\n"
        f"🎯 Порог сигнала: "
        f"+{MIN_NET_SPREAD:.2f}%"
    )

    if best["best_net"] >= MIN_NET_SPREAD:

        message += (
            "\n\n"
            "🟢 Возможность соответствует "
            "пороговому значению."
        )

    else:

        message += (
            "\n\n"
            "⚪ Сейчас выгодной возможности "
            "нет."
        )

    return message


# ============================================================
# АВТОМАТИЧЕСКИЙ МОНИТОРИНГ
# ============================================================

def arbitrage_monitor():

    last_alert_time = 0

    last_alert_symbol = None

    print(
        "=========================================="
    )

    print(
        "ARBITRAGE MONITOR STARTED"
    )

    print(
        f"Pairs: {len(SYMBOLS)}"
    )

    print(
        f"Check interval: "
        f"{CHECK_INTERVAL} sec"
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
        "=========================================="
    )

    while True:

        cycle_start = time.time()

        try:

            results = scan_all_pairs()

            if results:

                best = get_best_opportunity(
                    results
                )

                print(
                    f"BEST | "
                    f"{best['symbol']} | "
                    f"RAW={best['best_raw']:+.4f}% | "
                    f"NET={best['best_net']:+.4f}% | "
                    f"{best['direction']}"
                )

                # ------------------------------------------------
                # Если чистый спред достаточно большой
                # ------------------------------------------------

                if (
                    best["best_net"]
                    >= MIN_NET_SPREAD
                ):

                    now = time.time()

                    can_alert = (
                        now - last_alert_time
                        >= ALERT_COOLDOWN
                    )

                    # Не спамим одинаковым сигналом
                    same_symbol = (
                        best["symbol"]
                        == last_alert_symbol
                    )

                    if can_alert or not same_symbol:

                        message = (
                            format_opportunity(
                                best,
                                is_alert=True
                            )
                        )

                        send_telegram(
                            message
                        )

                        last_alert_time = now

                        last_alert_symbol = (
                            best["symbol"]
                        )

                        print(
                            "🚨 ALERT SENT:"
                            f" {best['symbol']} "
                            f"NET="
                            f"{best['best_net']:.4f}%"
                        )

                else:

                    print(
                        "No profitable "
                        "opportunity."
                    )

            else:

                print(
                    "No valid pairs "
                    "returned."
                )

        except Exception as e:

            print(
                "Monitor error:",
                repr(e)
            )

        # --------------------------------------------------------
        # Сохраняем примерно заданный интервал
        # --------------------------------------------------------

        elapsed = (
            time.time()
            - cycle_start
        )

        sleep_time = max(
            1,
            CHECK_INTERVAL - elapsed
        )

        time.sleep(
            sleep_time
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
                "timeout": 30
            }

            if offset is not None:

                params["offset"] = offset

            response = session.get(
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
                    message.get(
                        "text",
                        ""
                    )
                    .strip()
                    .lower()
                )

                # ------------------------------------------------
                # Только наш Telegram
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

                        f"🔎 Мониторинг: "
                        f"{len(SYMBOLS)} пар\n\n"

                        f"⏱ Проверка каждые: "
                        f"{CHECK_INTERVAL} сек.\n\n"

                        f"💸 Binance fee: "
                        f"{BINANCE_FEE:.2f}%\n"

                        f"💸 BingX fee: "
                        f"{BINGX_FEE:.2f}%\n"

                        f"🛡 Запас: "
                        f"{SAFETY_MARGIN:.2f}%\n\n"

                        f"🎯 Сигнал от: "
                        f"+{MIN_NET_SPREAD:.2f}% "
                        "чистыми\n\n"

                        "Команды:\n"
                        "/start — настройки бота\n"
                        "/test — проверить все пары сейчас"
                    )

                # ------------------------------------------------
                # /test
                # ------------------------------------------------

                elif text in [
                    "/test",
                    "test"
                ]:

                    send_telegram(
                        "🔎 Проверяю все пары...\n"
                        "Это может занять несколько секунд."
                    )

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

    try:

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

    except Exception as e:

        print(
            "Health server error:",
            repr(e)
        )


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "=========================================="
    )

    print(
        "BINANCE ↔ BINGX ARBITRAGE BOT"
    )

    print(
        "=========================================="
    )

    print(
        f"Pairs: {len(SYMBOLS)}"
    )

    print(
        f"Interval: "
        f"{CHECK_INTERVAL} sec"
    )

    print(
        f"Minimum NET: "
        f"{MIN_NET_SPREAD}%"
    )

    print(
        "=========================================="
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
