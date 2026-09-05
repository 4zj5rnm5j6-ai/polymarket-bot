import os
import asyncio
import aiohttp
import time
import json

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Порог изменения цены BTC (%), после которого считаем, что рынок уже "должен был" отреагировать
LAG_THRESHOLD_PCT = float(os.getenv("LAG_THRESHOLD_PCT", "0.10"))
# Если цена на Polymarket ниже этого значения, а движение уже произошло — считаем это лагом
PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD", "0.65"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Флаг, чтобы /start не плодил параллельные копии monitor()
monitor_task = None

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

# Состояние текущего 15-минутного окна
current_slug = None
window_start_price = None
alerted_directions = set()
# Чтобы не спамить «Polymarket молчит» каждые 5 минут в одном окне
poly_down_alerted = False


def get_btc_slug(interval_minutes=15):
    now = int(time.time())
    rounded = (now // (interval_minutes * 60)) * (interval_minutes * 60)
    return f"btc-updown-{interval_minutes}m-{rounded}"


async def get_btc_price():
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_URL) as r:
            data = await r.json()
            return float(data["price"])


async def get_polymarket_btc():
    slug = get_btc_slug(15)
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            data = await r.json()
            return data, slug


def parse_prices(raw_prices):
    """Безопасно парсим outcomePrices в список float"""
    try:
        if isinstance(raw_prices, str):
            p = json.loads(raw_prices)
        else:
            p = raw_prices
        return float(p[0]), float(p[1])
    except Exception:
        return None, None


def btc_moved_enough(btc_price):
    """BTC уже заметно уехал от старта 15m-окна?"""
    if window_start_price is None:
        return False, 0.0
    change_pct = (btc_price - window_start_price) / window_start_price * 100
    return abs(change_pct) >= LAG_THRESHOLD_PCT, change_pct


def check_lag(btc_price, up_price, down_price):
    """
    Возвращает текст алерта, если обнаружен лаг между реальным движением цены
    и тем, как это отражено в цене Polymarket. Иначе None.
    """
    global window_start_price, alerted_directions

    if window_start_price is None:
        return None

    change_pct = (btc_price - window_start_price) / window_start_price * 100

    if change_pct >= LAG_THRESHOLD_PCT and up_price is not None and up_price < PRICE_THRESHOLD:
        if "up" not in alerted_directions:
            alerted_directions.add("up")
            return (
                f"⚡️ ЛАГ ОБНАРУЖЕН!\n"
                f"BTC уже вырос на {change_pct:.3f}% от старта окна, "
                f"а Polymarket UP всё ещё стоит {up_price:.2f}\n"
                f"Возможна возможность на UP"
            )

    if change_pct <= -LAG_THRESHOLD_PCT and down_price is not None and down_price < PRICE_THRESHOLD:
        if "down" not in alerted_directions:
            alerted_directions.add("down")
            return (
                f"⚡️ ЛАГ ОБНАРУЖЕН!\n"
                f"BTC уже упал на {abs(change_pct):.3f}% от старта окна, "
                f"а Polymarket DOWN всё ещё стоит {down_price:.2f}\n"
                f"Возможна возможность на DOWN"
            )

    return None


def check_poly_unavailable(btc_price, reason):
    """
    Алерт, если Polymarket молчит/сломался, а BTC уже двинулся.
    Один раз за 15-минутное окно.
    """
    global poly_down_alerted

    if poly_down_alerted:
        return None

    moved, change_pct = btc_moved_enough(btc_price)
    if not moved:
        return None

    poly_down_alerted = True
    direction = "вверх" if change_pct > 0 else "вниз"
    return (
        f"⚠️ POLYMARKET МОЛЧИТ!\n"
        f"BTC уже уехал {direction} на {abs(change_pct):.3f}% от старта окна,\n"
        f"а Polymarket недоступен: {reason}\n"
        f"Проверь рынок вручную — цены могли уже уехать."
    )


async def monitor():
    global current_slug, window_start_price, alerted_directions, poly_down_alerted

    while True:
        try:
            btc = await get_btc_price()
            markets = None
            slug = get_btc_slug(15)
            poly_error = None

            try:
                markets, slug = await get_polymarket_btc()
            except Exception as e:
                poly_error = f"ошибка запроса ({e})"

            # Новое окно — сбрасываем состояние
            if slug != current_slug:
                current_slug = slug
                window_start_price = btc
                alerted_directions = set()
                poly_down_alerted = False

            msg = f"💰 BTC: ${btc:,.0f}\n\n📊 Polymarket BTC 15m:\n"
            up_price, down_price = None, None

            if poly_error:
                msg += f"⚠️ Не удалось получить рынок: {poly_error}\n"
                alert = check_poly_unavailable(btc, poly_error)
                if alert:
                    await bot.send_message(CHAT_ID, alert)
            elif markets:
                for m in markets[:3]:
                    question = m.get("question", "?")[:60]
                    prices = m.get("outcomePrices", ["?", "?"])
                    up_price, down_price = parse_prices(prices)
                    if up_price is not None:
                        msg += f"• {question}\n ⬆️ UP: {up_price} | ⬇️ DOWN: {down_price}\n"
                    else:
                        msg += f"• {question}\n (цены не прочитались)\n"
                        alert = check_poly_unavailable(btc, "цены рынка не прочитались")
                        if alert:
                            await bot.send_message(CHAT_ID, alert)
            else:
                msg += f"Рынок не найден: {slug}\n"
                alert = check_poly_unavailable(btc, f"рынок не найден ({slug})")
                if alert:
                    await bot.send_message(CHAT_ID, alert)

            if window_start_price:
                change_pct = (btc - window_start_price) / window_start_price * 100
                msg += f"\n📈 Изменение от старта окна: {change_pct:+.3f}%"

            await bot.send_message(CHAT_ID, msg)

            # Проверка на лаг — только когда цены есть
            alert = check_lag(btc, up_price, down_price)
            if alert:
                await bot.send_message(CHAT_ID, alert)

        except Exception as e:
            print(f"Ошибка: {e}")
            # Если упало что-то общее, а BTC уже двинулся — тоже скажем один раз за окно
            try:
                btc = await get_btc_price()
                slug = get_btc_slug(15)
                if slug != current_slug:
                    current_slug = slug
                    window_start_price = btc
                    alerted_directions = set()
                    poly_down_alerted = False
                alert = check_poly_unavailable(btc, f"сбой монитора ({e})")
                if alert:
                    await bot.send_message(CHAT_ID, alert)
            except Exception as e2:
                print(f"Не удалось отправить аварийный алерт: {e2}")

        await asyncio.sleep(300)


@dp.message(Command("start"))
async def start(message: Message):
    global monitor_task
    if monitor_task is not None and not monitor_task.done():
        await message.answer("🤖 Монитор уже запущен, всё в порядке — новую копию не создаю.")
        return
    monitor_task = asyncio.create_task(monitor())
    await message.answer(
        "🤖 Polymarket BTC монитор запущен!\n"
        "Обновление каждые 5 минут.\n"
        "Лаг-детект: включён.\n"
        "Алерт «Polymarket молчит»: включён."
    )


async def main():
    global monitor_task
    monitor_task = asyncio.create_task(monitor())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
