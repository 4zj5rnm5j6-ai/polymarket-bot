import os
import asyncio
import aiohttp
import time
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=TOKEN)
dp = Dispatcher()

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

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

async def monitor():
    while True:
        try:
            btc = await get_btc_price()
            markets, slug = await get_polymarket_btc()
            msg = f"💰 BTC: ${btc:,.0f}\n\n📊 Polymarket BTC 15m:\n"
            if markets:
                for m in markets[:3]:
                    question = m.get('question', '?')[:60]
                    prices = m.get('outcomePrices', ['?', '?'])
                    try:
                        p = eval(prices) if isinstance(prices, str) else prices
                        msg += f"• {question}\n  ⬆️ UP: {p[0]} | ⬇️ DOWN: {p[1]}\n"
                    except:
                        msg += f"• {question}\n"
            else:
                msg += f"Рынок не найден: {slug}"
            await bot.send_message(CHAT_ID, msg)
        except Exception as e:
            print(f"Ошибка: {e}")
        await asyncio.sleep(300)

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🤖 Polymarket BTC монитор запущен!\nОбновление каждые 5 минут.")
    asyncio.create_task(monitor())

async def main():
    asyncio.create_task(monitor())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
