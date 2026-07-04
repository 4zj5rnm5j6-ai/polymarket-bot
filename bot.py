import os
import asyncio
import aiohttp
import time

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Порог изменения цены BTC (%), после которого считаем, что рынок уже "должен был" отреагировать
LAG_THRESHOLD_PCT = float(os.getenv("LAG_THRESHOLD_PCT", "0.05"))
# Если цена на Polymarket ниже этого значения, а движение уже произошло — считаем это лагом
PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD", "0.65"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

# Состояние текущего 15-минутного окна
current_slug = None
window_start_price = None
alerted_directions = set()


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
        p = eval(raw_prices) if isinstance(raw_prices, str) else raw_prices
        return float(p[0]), float(p[1])
    except Exception:
        return None, None


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


async def monitor():
    global current_slug, window_start_price, alerted_directions

    while True:
        try:
            btc = await get_btc_price()
            markets, slug = await get_polymarket_btc()

            # Новое окно — сбрасываем состояние
            if slug != current_slug:
                current_slug = slug
                window_start_price = btc
                alerted_directions = set()

            msg = f"💰 BTC: ${btc:,.0f}\n\n📊 Polymarket BTC 15m:\n"
            up_price, down_price = None, None

            if markets:
                for m in markets[:3]:
                    question = m.get('question', '?')[:60]
                    prices = m.get('outcomePrices', ['?', '?'])
                    up_price, down_price = parse_prices(prices)
                    if up_price is not None:
                        msg += f"• {question}\n ⬆️ UP: {up_price} | ⬇️ DOWN: {down_price}\n"
                    else:
                        msg += f"• {question}\n"
            else:
                msg += f"Рынок не найден: {slug}"

            if window_start_price:
                change_pct = (btc - window_start_price) / window_start_price * 100
                msg += f"\n📈 Изменение от старта окна: {change_pct:+.3f}%"

            await bot.send_message(CHAT_ID, msg)

            # Проверка на лаг — отдельным сообщением, чтобы не потерялось
            alert = check_lag(btc, up_price, down_price)
            if alert:
                await bot.send_message(CHAT_ID, alert)

        except Exception as e:
            print(f"Ошибка: {e}")

        await asyncio.sleep(300)


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🤖 Polymarket BTC монитор запущен!\nОбновление каждые 5 минут.\nЛаг-детект: включён.")
    asyncio.create_task(monitor())


async def main():
    asyncio.create_task(monitor())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

