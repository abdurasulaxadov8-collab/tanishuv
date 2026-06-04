"""
Ikkalasini bir vaqtda ishga tushirish
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)

async def main():
    from bot.server import create_app, init_db
    from bot.bot import dp, bot
    from aiohttp import web

    # Database ni ishga tushirish
    await init_db()

    # Server va bot ni parallel ishga tushirish
    port = int(os.environ.get('PORT', 8080))

    # aiohttp server
    app = create_app()
    app.on_startup.append(lambda a: asyncio.create_task(asyncio.sleep(0)))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🚀 Server port {port} da ishga tushdi")

    # Bot polling
    logger.info("🤖 Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
