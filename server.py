"""
API Server — Telegram Mini App bilan ishlash uchun
aiohttp asosida WebSocket + REST API
"""
import asyncio
import json
import logging
import aiosqlite
from datetime import datetime, date
from aiohttp import web
import aiohttp
from aiohttp.web import WebSocketResponse

DB_PATH = "tanishuv.db"
ADMIN_ID = 8330377593

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Barcha ulangan WebSocket clientlar
connected_clients = {}  # {user_id: ws}

# ==================== HELPERS ====================

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_messages(limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT m.*, u.name, u.character, u.photo_url
            FROM messages m
            JOIN users u ON m.user_id = u.telegram_id
            WHERE m.is_deleted = 0
            ORDER BY m.created_at DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in reversed(rows)]

async def save_message(user_id: int, content: str, effect: str = "none"):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO messages (user_id, content, character_effect) VALUES (?, ?, ?)",
            (user_id, content, effect)
        )
        await db.commit()
        msg_id = cursor.lastrowid

    # Barcha clientlarga yuborish
    user = await get_user(user_id)
    message_data = {
        "type": "new_message",
        "data": {
            "id": msg_id,
            "user_id": user_id,
            "content": content,
            "character_effect": effect,
            "name": user['name'],
            "character": user['character'],
            "photo_url": user.get('photo_url', ''),
            "created_at": datetime.now().isoformat()
        }
    }
    await broadcast(message_data)
    return msg_id

async def broadcast(data: dict, exclude_id: int = None):
    """Barcha ulangan foydalanuvchilarga xabar yuborish"""
    message = json.dumps(data)
    disconnected = []
    for uid, ws in connected_clients.items():
        if uid == exclude_id:
            continue
        try:
            await ws.send_str(message)
        except Exception:
            disconnected.append(uid)
    for uid in disconnected:
        connected_clients.pop(uid, None)

async def check_can_send(user_id: int) -> tuple[bool, str]:
    """Xabar yuborish mumkinligini tekshirish"""
    user = await get_user(user_id)
    if not user:
        return False, "Foydalanuvchi topilmadi"
    if user['is_blocked']:
        return False, "Siz bloklangansiz"

    today = date.today().isoformat()
    if user['daily_msg_limit'] != -1:
        if user['last_msg_date'] != today:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE users SET daily_msg_count=0, last_msg_date=? WHERE telegram_id=?",
                    (today, user_id)
                )
                await db.commit()
            user['daily_msg_count'] = 0

        if user['daily_msg_count'] >= user['daily_msg_limit']:
            return False, f"Kunlik limit ({user['daily_msg_limit']}) tugadi"

    return True, "ok"

# ==================== REST API ====================

async def api_get_messages(request):
    msgs = await get_messages(50)
    return web.json_response({"ok": True, "messages": msgs})

async def api_get_user(request):
    user_id = int(request.match_info['user_id'])
    user = await get_user(user_id)
    if not user:
        return web.json_response({"ok": False, "error": "Not found"}, status=404)
    user.pop('phone', None)  # Telefon raqamni yashirish
    return web.json_response({"ok": True, "user": user})

async def api_update_profile(request):
    data = await request.json()
    user_id = data.get('user_id')
    if not user_id:
        return web.json_response({"ok": False, "error": "user_id required"}, status=400)

    allowed = ['name', 'bio', 'photo_url']
    updates = {k: v for k, v in data.items() if k in allowed}

    async with aiosqlite.connect(DB_PATH) as db:
        if updates:
            fields = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [user_id]
            await db.execute(f"UPDATE users SET {fields} WHERE telegram_id = ?", values)
            await db.commit()

    return web.json_response({"ok": True})

async def api_buy_character(request):
    data = await request.json()
    user_id = data.get('user_id')
    character = data.get('character')

    CHARACTER_PRICES = {"man": 0, "black": 20000, "white": 50000, "admin_char": 100000}
    CHARACTER_LIMITS = {"black": 20, "white": 10, "admin_char": 5}

    if character not in CHARACTER_PRICES:
        return web.json_response({"ok": False, "error": "Noto'g'ri persanaj"})

    user = await get_user(user_id)
    if not user:
        return web.json_response({"ok": False, "error": "Foydalanuvchi topilmadi"})

    price = CHARACTER_PRICES[character]
    if user['balance'] < price:
        return web.json_response({"ok": False, "error": f"Balans yetarli emas. Kerak: {price:,}"})

    # Limit tekshirish
    if character in CHARACTER_LIMITS:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT count FROM character_counts WHERE character = ?", (character,)
            ) as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0
        if count >= CHARACTER_LIMITS[character]:
            return web.json_response({"ok": False, "error": f"Bu persanaj limitga yetdi ({CHARACTER_LIMITS[character]} ta)"})

    # Sotib olish
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = balance - ?, character = ? WHERE telegram_id = ?",
            (price, character, user_id)
        )
        if character in CHARACTER_LIMITS:
            await db.execute(
                "UPDATE character_counts SET count = count + 1 WHERE character = ?",
                (character,)
            )
        await db.commit()

    return web.json_response({"ok": True, "message": f"{character.upper()} persanaji sotib olindi!"})

async def api_delete_message(request):
    data = await request.json()
    user_id = data.get('user_id')
    msg_id = data.get('msg_id')

    user = await get_user(user_id)
    if not user or user['character'] != 'admin_char':
        return web.json_response({"ok": False, "error": "Ruxsat yo'q"})

    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # Kunlik ochirish limitini tekshirish
        if user['last_delete_date'] != today:
            await db.execute(
                "UPDATE users SET daily_delete_count=0, last_delete_date=? WHERE telegram_id=?",
                (today, user_id)
            )
            await db.commit()
            user = await get_user(user_id)

        if user['daily_delete_count'] >= 5:
            return web.json_response({"ok": False, "error": "Kunlik 5 ta ochirish limiti tugadi"})

        await db.execute(
            "UPDATE messages SET is_deleted=1 WHERE id=?", (msg_id,)
        )
        await db.execute(
            "UPDATE users SET daily_delete_count=daily_delete_count+1 WHERE telegram_id=?",
            (user_id,)
        )
        await db.commit()

    # Barcha clientlarga o'chirilganini aytish
    await broadcast({"type": "delete_message", "msg_id": msg_id})
    return web.json_response({"ok": True})

async def api_character_counts(request):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM character_counts") as cursor:
            rows = await cursor.fetchall()
    counts = {row[0]: row[1] for row in rows}
    limits = {"black": 20, "white": 10, "admin_char": 5, "atilla": 0}
    return web.json_response({"ok": True, "counts": counts, "limits": limits})

# ==================== WEBSOCKET ====================

async def websocket_handler(request):
    ws = WebSocketResponse()
    await ws.prepare(request)

    user_id = None
    logger.info("WebSocket ulanish...")

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                action = data.get('action')

                if action == 'auth':
                    user_id = data.get('user_id')
                    user = await get_user(user_id)
                    if user and not user['is_blocked']:
                        connected_clients[user_id] = ws
                        # Oxirgi xabarlarni yuborish
                        msgs = await get_messages(50)
                        await ws.send_str(json.dumps({
                            "type": "init",
                            "messages": msgs,
                            "user": {k: v for k, v in user.items() if k != 'phone'}
                        }))
                        # Boshqalarga "kirdi" deb xabar
                        await broadcast({
                            "type": "user_join",
                            "user": {"id": user_id, "name": user['name'], "character": user['character']}
                        }, exclude_id=user_id)
                        logger.info(f"✅ {user['name']} ({user_id}) ulandi")
                    else:
                        await ws.send_str(json.dumps({"type": "error", "message": "Auth failed"}))
                        await ws.close()
                        break

                elif action == 'send_message':
                    if not user_id:
                        continue
                    can_send, reason = await check_can_send(user_id)
                    if not can_send:
                        await ws.send_str(json.dumps({"type": "error", "message": reason}))
                        continue

                    content = data.get('content', '').strip()
                    effect = data.get('effect', 'none')
                    if not content or len(content) > 1000:
                        continue

                    user = await get_user(user_id)
                    # Effect faqat to'g'ri persanajda
                    valid_effects = {
                        "man": ["none"],
                        "black": ["none", "black_smoke"],
                        "white": ["none", "white_lightning"],
                        "admin_char": ["none", "hacker"],
                        "atilla": ["none"]
                    }
                    char = user.get('character', 'man')
                    if effect not in valid_effects.get(char, ["none"]):
                        effect = "none"

                    await save_message(user_id, content, effect)

                    # Kunlik count oshirish
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE users SET daily_msg_count=daily_msg_count+1, last_msg_date=? WHERE telegram_id=?",
                            (date.today().isoformat(), user_id)
                        )
                        await db.commit()

                elif action == 'typing':
                    if not user_id:
                        continue
                    user = await get_user(user_id)
                    await broadcast({
                        "type": "typing",
                        "user_id": user_id,
                        "name": user['name']
                    }, exclude_id=user_id)

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"WS error: {e}")

        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f"WS error: {ws.exception()}")
            break

    # Disconnect
    if user_id and user_id in connected_clients:
        connected_clients.pop(user_id)
        user = await get_user(user_id)
        if user:
            await broadcast({
                "type": "user_leave",
                "user_id": user_id,
                "name": user['name']
            })
        logger.info(f"❌ {user_id} chiqdi")

    return ws

# ==================== CORS ====================
async def cors_middleware(app, handler):
    async def middleware(request):
        if request.method == 'OPTIONS':
            response = web.Response()
        else:
            response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        return response
    return middleware

# ==================== APP ====================
def create_app():
    app = web.Application(middlewares=[])

    app.router.add_get('/ws', websocket_handler)
    app.router.add_get('/api/messages', api_get_messages)
    app.router.add_get('/api/user/{user_id}', api_get_user)
    app.router.add_post('/api/profile', api_update_profile)
    app.router.add_post('/api/buy-character', api_buy_character)
    app.router.add_post('/api/delete-message', api_delete_message)
    app.router.add_get('/api/character-counts', api_character_counts)

    # Static fayllar (webapp)
    app.router.add_static('/', path='../webapp', name='webapp')

    return app

if __name__ == '__main__':
    app = create_app()
    logger.info("🚀 API Server port 8080 da ishga tushdi")
    web.run_app(app, host='0.0.0.0', port=8080)
