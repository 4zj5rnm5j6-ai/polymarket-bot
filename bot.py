import os
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=TOKEN)
dp = Dispatcher()

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
GAMMA_URL = "https://gamma-api.polymarket.com/markets?tag_slug=crypto&limit=5&active=true"

async def get_btc_price():
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_URL) as r:
            data = await r.json()
            return float(data["price"])

async def get_polymarket():
    async with aiohttp.ClientSession() as session:
        async with session.get(GAMMA_URL) as r:
            return await r.json()

async def monitor():
    while True:
        try:
            btc = await get_btc_price()
            markets = await get_polymarket()
            msg = f"💰 BTC: ${btc:,.0f}\n\n📊 Polymarket крипто:\n"
            for m in markets[:5]:
                question = m.get('question', '?')[:60]
                price = m.get('outcomePrices', ['?'])[0]
                msg += f"• {question}\n  Цена: {price}\n"
            await bot.send_message(CHAT_ID, msg)
        except Exception as e:
            print(f"Ошибка: {e}")
        await asyncio.sleep(300)

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🤖 Polymarket монитор запущен!\nОбновление каждые 5 минут.")
    asyncio.create_task(monitor())

async def main():
    asyncio.create_task(monitor())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
