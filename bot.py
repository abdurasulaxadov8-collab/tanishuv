import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite
import json
from datetime import datetime

# ==================== SOZLAMALAR ====================
BOT_TOKEN = "8856638354:AAF8kV9O3nmBM_tQAeCRny_wh48gUcbAImo"
WEBAPP_URL = "https://lambent-profiterole-44d808.netlify.app"  # Mini App URL
ADMIN_ID = 8330377593
ADMIN_CARD = "9860080151682814"
DB_PATH = "tanishuv.db"

# Persanaj limitlari
CHARACTER_LIMITS = {
    "man": float('inf'),
    "black": 20,
    "white": 10,
    "admin_char": 5,
    "atilla": 0  # qulflangan
}

CHARACTER_PRICES = {
    "man": 0,
    "black": 20000,
    "white": 50000,
    "admin_char": 100000,
    "atilla": 999999999
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== FSM HOLATLARI ====================
class Registration(StatesGroup):
    waiting_contact = State()
    waiting_name = State()
    waiting_bio = State()

class AdminState(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()
    waiting_block_id = State()
    waiting_limit_id = State()
    waiting_limit_value = State()

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE NOT NULL,
                phone TEXT NOT NULL,
                name TEXT NOT NULL,
                bio TEXT DEFAULT '',
                photo_url TEXT DEFAULT '',
                character TEXT DEFAULT 'man',
                balance INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                daily_delete_count INTEGER DEFAULT 0,
                last_delete_date TEXT DEFAULT '',
                daily_msg_limit INTEGER DEFAULT -1,
                daily_msg_count INTEGER DEFAULT 0,
                last_msg_date TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                character_effect TEXT DEFAULT 'none',
                is_deleted INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS character_counts (
                character TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Character counts boshlang'ich qiymatlari
        for char in ["black", "white", "admin_char", "atilla"]:
            await db.execute(
                "INSERT OR IGNORE INTO character_counts (character, count) VALUES (?, 0)",
                (char,)
            )
        await db.commit()
    logger.info("✅ Database tayyor")

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            return await cursor.fetchone()

async def create_user(telegram_id: int, phone: str, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (telegram_id, phone, name) VALUES (?, ?, ?)""",
            (telegram_id, phone, name)
        )
        await db.commit()

async def update_user(telegram_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [telegram_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE users SET {fields} WHERE telegram_id = ?", values
        )
        await db.commit()

async def get_character_count(character: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT count FROM character_counts WHERE character = ?", (character,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def increment_character_count(character: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE character_counts SET count = count + 1 WHERE character = ?",
            (character,)
        )
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users") as cursor:
            return await cursor.fetchall()

# ==================== KOMANDALAR ====================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user:
        # Allaqachon ro'yxatdan o'tgan
        await send_main_menu(message, user)
        return

    # Kontakt so'rash
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="📱 Kontaktni yuborish",
                request_contact=True
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "👋 Tanishuv Chat'ga xush kelibsiz!\n\n"
        "Davom etish uchun telefon raqamingizni yuboring:",
        reply_markup=keyboard
    )
    await state.set_state(Registration.waiting_contact)

@dp.message(Registration.waiting_contact, F.contact)
async def process_contact(message: types.Message, state: FSMContext):
    contact = message.contact
    if contact.user_id != message.from_user.id:
        await message.answer("❌ Faqat o'z kontaktingizni yuboring!")
        return

    await state.update_data(phone=contact.phone_number)

    await message.answer(
        "✅ Telefon qabul qilindi!\n\n"
        "👤 Ismingizni kiriting:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(Registration.waiting_name)

@dp.message(Registration.waiting_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("❌ Ism 2-30 ta belgi bo'lishi kerak!")
        return

    data = await state.get_data()
    await create_user(message.from_user.id, data['phone'], name)
    await state.update_data(name=name)

    await message.answer(
        f"🎉 Xush kelibsiz, {name}!\n\n"
        "📝 Bio (o'zingiz haqida qisqacha) kiriting yoki /skip yozing:"
    )
    await state.set_state(Registration.waiting_bio)

@dp.message(Registration.waiting_bio)
async def process_bio(message: types.Message, state: FSMContext):
    if message.text == "/skip":
        bio = ""
    else:
        bio = message.text.strip()[:150]

    await update_user(message.from_user.id, bio=bio)
    user = await get_user(message.from_user.id)
    await state.clear()
    await send_main_menu(message, user)

async def send_main_menu(message: types.Message, user):
    webapp_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💬 Chatga kirish",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/index.html")
        )
    ], [
        InlineKeyboardButton(
            text="👤 Profilim",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/profile.html")
        )
    ], [
        InlineKeyboardButton(
            text="🎭 Persanajlar",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/characters.html")
        )
    ]])

    char_emoji = {"man": "👤", "black": "⬛", "white": "⬜", "admin_char": "💚", "atilla": "🔒"}
    char = user['character'] if user['character'] else 'man'

    await message.answer(
        f"✅ Profil: *{user['name']}*\n"
        f"🎭 Persanaj: {char_emoji.get(char, '👤')} {char.upper()}\n"
        f"💰 Balans: {user['balance']:,} so'm\n\n"
        f"👇 Pastdagi tugmani bosing:",
        reply_markup=webapp_keyboard,
        parse_mode="Markdown"
    )

# ==================== ADMIN PANEL ====================

@dp.message(F.text == "/admin")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return  # Admin bo'lmasa umuman javob berma

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton(text="💰 Pul berish", callback_data="admin_give_money")],
        [InlineKeyboardButton(text="🚫 Bloklash", callback_data="admin_block")],
        [InlineKeyboardButton(text="⚡ Limit qo'yish", callback_data="admin_limit")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💳 Kutayotgan to'lovlar", callback_data="admin_payments")],
    ])
    await message.answer(
        "🔐 *ADMIN PANEL*\n\n"
        f"ID: `{ADMIN_ID}`\n"
        "Nima qilmoqchisiz?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    total = len(users)
    blocked = sum(1 for u in users if u['is_blocked'])
    chars = {}
    for u in users:
        c = u['character'] or 'man'
        chars[c] = chars.get(c, 0) + 1

    black_count = await get_character_count("black")
    white_count = await get_character_count("white")
    admin_count = await get_character_count("admin_char")

    text = (
        f"📊 *STATISTIKA*\n\n"
        f"👥 Jami foydalanuvchilar: {total}\n"
        f"🚫 Bloklangan: {blocked}\n\n"
        f"🎭 *Persanajlar:*\n"
        f"👤 MAN: {chars.get('man', 0)} (∞)\n"
        f"⬛ BLACK: {black_count}/20\n"
        f"⬜ WHITE: {white_count}/10\n"
        f"💚 ADMIN: {admin_count}/5\n"
        f"🔒 ATILLA: 0/0 (qulflangan)\n"
    )
    await callback.message.edit_text(text, parse_mode="Markdown")

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    text = "👥 *FOYDALANUVCHILAR:*\n\n"
    for u in users[:20]:  # Max 20 ko'rsatish
        status = "🚫" if u['is_blocked'] else "✅"
        text += f"{status} `{u['telegram_id']}` — {u['name']} | {u['character']} | {u['balance']}so'm\n"
    if len(users) > 20:
        text += f"\n... va yana {len(users)-20} ta"
    await callback.message.edit_text(text, parse_mode="Markdown")

@dp.callback_query(F.data == "admin_give_money")
async def admin_give_money_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("💰 Pul bermoqchi bo'lgan foydalanuvchi ID sini kiriting:")
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="give_money")

@dp.callback_query(F.data == "admin_block")
async def admin_block_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("🚫 Bloklash uchun foydalanuvchi ID sini kiriting:")
    await state.set_state(AdminState.waiting_block_id)

@dp.callback_query(F.data == "admin_limit")
async def admin_limit_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("⚡ Limit qo'yish uchun foydalanuvchi ID sini kiriting:")
    await state.set_state(AdminState.waiting_limit_id)

@dp.message(AdminState.waiting_block_id)
async def process_block_id(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.strip())
        user = await get_user(user_id)
        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi!")
            await state.clear()
            return
        new_status = 0 if user['is_blocked'] else 1
        await update_user(user_id, is_blocked=new_status)
        action = "blokdan chiqarildi" if new_status == 0 else "bloklandi"
        await message.answer(f"✅ {user['name']} ({user_id}) {action}!")
    except ValueError:
        await message.answer("❌ Noto'g'ri ID!")
    await state.clear()

@dp.message(AdminState.waiting_limit_id)
async def process_limit_id(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.strip())
        user = await get_user(user_id)
        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi!")
            await state.clear()
            return
        await state.update_data(limit_user_id=user_id)
        await message.answer(f"⚡ {user['name']} uchun kunlik xabar limitini kiriting (-1 = cheksiz):")
        await state.set_state(AdminState.waiting_limit_value)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID!")
        await state.clear()

@dp.message(AdminState.waiting_limit_value)
async def process_limit_value(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        limit = int(message.text.strip())
        data = await state.get_data()
        user_id = data['limit_user_id']
        await update_user(user_id, daily_msg_limit=limit)
        await message.answer(f"✅ Limit {limit} ga o'rnatildi!")
    except ValueError:
        await message.answer("❌ Noto'g'ri qiymat!")
    await state.clear()

@dp.message(AdminState.waiting_user_id)
async def process_give_money_id(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.strip())
        user = await get_user(user_id)
        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi!")
            await state.clear()
            return
        await state.update_data(target_user_id=user_id)
        await message.answer(f"💰 {user['name']} ga qancha pul bermoqchisiz?")
        await state.set_state(AdminState.waiting_amount)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID!")
        await state.clear()

@dp.message(AdminState.waiting_amount)
async def process_give_money_amount(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        user_id = data['target_user_id']
        user = await get_user(user_id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
                (amount, user_id)
            )
            await db.commit()
        await message.answer(f"✅ {user['name']} ga {amount:,} so'm berildi!")
        # Foydalanuvchiga xabar yuborish
        try:
            await bot.send_message(
                user_id,
                f"💰 Hisobingizga {amount:,} so'm qo'shildi!\n"
                f"💳 Joriy balans: {(user['balance'] + amount):,} so'm"
            )
        except:
            pass
    except ValueError:
        await message.answer("❌ Noto'g'ri miqdor!")
    await state.clear()

# ==================== TO'LOV XABARI ====================
@dp.message(F.text.startswith("TO'LOV"))
async def payment_notification(message: types.Message):
    """Foydalanuvchi to'lov haqida admin ga xabar beradi"""
    if message.from_user.id == ADMIN_ID:
        return
    user = await get_user(message.from_user.id)
    if not user:
        return
    # Admin ga xabar yuborish
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"✅ Tasdiqlash",
            callback_data=f"confirm_payment_{message.from_user.id}"
        ),
        InlineKeyboardButton(
            text="❌ Rad etish",
            callback_data=f"reject_payment_{message.from_user.id}"
        )
    ]])
    await bot.send_message(
        ADMIN_ID,
        f"💳 *YANGI TO'LOV SO'ROVI*\n\n"
        f"👤 {user['name']}\n"
        f"🆔 `{message.from_user.id}`\n"
        f"📱 {user['phone']}\n\n"
        f"💰 Karta: `{ADMIN_CARD}`\n\n"
        f"Xabar: {message.text}",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await message.answer("✅ To'lov so'rovingiz adminга yuborildi! Admin tasdiqlashini kuting.")

@dp.callback_query(F.data.startswith("confirm_payment_"))
async def confirm_payment(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split("_")[-1])
    await state.update_data(target_user_id=user_id, action="give_money")
    await callback.message.edit_text(f"💰 {user_id} ga qancha pul kiritmoqchisiz?")
    await state.set_state(AdminState.waiting_amount)

# ==================== API ENDPOINT (WebApp uchun) ====================
# Bu qism aiohttp server orqali ishlaydi — server.py ga ajratilgan

async def main():
    await init_db()
    logger.info("🤖 Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
