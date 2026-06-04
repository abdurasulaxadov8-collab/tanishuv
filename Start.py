"""
server.py va bot.py ni bir vaqtda ishga tushirish
"""
import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # server.py dan import
    import server
    import bot as bot_module
    from aiohttp import web

    # Database
    await server.init_db()

    # HTTP server
    port = int(os.environ.get('PORT', 8080))
    app = server.create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🚀 Server port {port} da ishga tushdi")

    # Bot polling
    logger.info("🤖 Bot ishga tushdi!")
    await bot_module.dp.start_polling(bot_module.bot)

if __name__ == '__main__':
    asyncio.run(main())
