import os
import json
import asyncio
from typing import List, Optional
import logging
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.filters.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "7854473349:AAEImt52KG7VHaaKzBXwHhEAuB2t94Onukw"
DB_PATH = os.environ.get("DB_PATH", "db.sqlite3")
ORDERS_CHAT = "@KolesaUfa02"  # Куда будут приходить уведомления
WEBAPP_URL = "https://skylightsufa.github.io/wheel_tg_bot/"  # URL WebApp на GitHub Pages 

# Создаем бота глобально, чтобы к нему был доступ из API
bot = Bot(BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
app = FastAPI(title="KolesaUfa API")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_IDS = set()

# --- FSM STATES ---
class AddProduct(StatesGroup):
    waiting_name = State()
    waiting_price = State()
    waiting_image = State()
    waiting_description = State()
    waiting_specs = State()
    confirming = State()


# --- MODEL (Схема данных заказа) ---
class OrderItem(BaseModel):
    id: int
    name: str
    price: int
    qty: int


class OrderRequest(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    items: List[OrderItem]
    total: int
    comment: Optional[str] = ""


# --- DATABASE ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            image TEXT DEFAULT '🛞',
            description TEXT DEFAULT '',
            specs TEXT DEFAULT '[]',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.commit()


def is_admin(user_id: Optional[int]) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


# --- API ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def root():
    """Возвращает index.html для Telegram WebApp"""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(content="<h1>WebApp not found</h1>", status_code=404)


@app.get("/index.html", response_class=HTMLResponse)
async def index_html():
    """Альтернативный путь к index.html"""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(content="<h1>WebApp not found</h1>", status_code=404)


@app.get("/api/products")
async def api_products():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM products WHERE active=1 ORDER BY id DESC")
        rows = await cur.fetchall()

    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "name": r["name"],
            "price": r["price"],
            "image": r["image"],
            "description": r["description"],
            "specs": json.loads(r["specs"] or "[]"),
        })
    return out


# НОВЫЙ МЕТОД: Принимает заказ напрямую через HTTP
@app.post("/api/order")
async def create_order(order: OrderRequest):
    # 1. Сохраняем в БД
    payload_json = order.model_dump_json()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders(user_id, payload) VALUES(?,?)",
            (order.user_id, payload_json),
        )
        await db.commit()

    # 2. Формируем текст сообщения
    lines = ["🧾 <b>Новый заказ (через API)</b>"]
    if order.full_name:
        user_link = f"<a href='tg://user?id={order.user_id}'>{order.full_name}</a>"
        lines.append(f"👤 Клиент: {user_link} (ID: {order.user_id})")
    if order.username:
        lines.append(f"🔗 @{order.username}")

    if order.comment:
        lines.append(f"💬 Комментарий: <i>{order.comment}</i>")

    lines.append("\n🛒 <b>Товары:</b>")
    for item in order.items:
        lines.append(f"• {item.name} (x{item.qty}) — {item.price * item.qty} ₽")

    lines.append(f"\n💰 <b>Итого: {order.total} ₽</b>")

    text = "\n".join(lines)

    # 3. Отправляем в чат заказов
    try:
        await bot.send_message(ORDERS_CHAT, text, parse_mode="HTML")
        return {"status": "ok", "message": "Заказ отправлен"}
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
        return {"status": "error", "message": str(e)}


# --- BOT HANDLERS ---

@dp.message(Command("start"))
async def start(message: Message):
    # Убедитесь, что url ведет на HTTPS версию
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🛞 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer("Откройте магазин кнопкой ниже:", reply_markup=kb)


@dp.message(Command("setadmin"))
async def cmd_setadmin(message: Message):
    ADMIN_IDS.add(message.from_user.id)
    await message.answer(f"Готово. Добавлен админ: {message.from_user.id}")


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отменяет текущую операцию"""
    current_state = await state.get_state()
    if current_state is None:
        return await message.answer("❌ Нет активных операций для отмены")
    
    await state.clear()
    await message.answer("✅ Операция отменена")


def get_image_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с популярными эмодзи для товаров"""
    emojis = ["🛞", "🚗", "🚙", "🏎️", "🛻", "🚛", "🚚", "🏍️", "🛵", "🚲", "⚙️", "🔧", "💎", "⭐", "🔥"]
    buttons = []
    row = []
    for i, emoji in enumerate(emojis):
        row.append(InlineKeyboardButton(text=emoji, callback_data=f"img_{emoji}"))
        if (i + 1) % 3 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Пропустить", callback_data="img_skip")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    """Начинает процесс добавления товара"""
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав администратора")
    
    await state.set_state(AddProduct.waiting_name)
    await message.answer(
        "➕ <b>Добавление нового товара</b>\n\n"
        "📝 <b>Шаг 1/5:</b> Введите название товара:",
        parse_mode="HTML"
    )


@dp.message(AddProduct.waiting_name)
async def process_name(message: Message, state: FSMContext):
    """Обрабатывает название товара"""
    # Проверяем, не отмена ли это
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        return await message.answer("✅ Операция отменена")
    
    name = message.text.strip()
    if not name:
        return await message.answer("❌ Название не может быть пустым. Попробуйте снова или /cancel для отмены:")
    
    await state.update_data(name=name)
    await state.set_state(AddProduct.waiting_price)
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "💰 <b>Шаг 2/5:</b> Введите цену товара (только число, без символов):\n"
        "💡 Или отправьте /cancel для отмены",
        parse_mode="HTML"
    )


@dp.message(AddProduct.waiting_price)
async def process_price(message: Message, state: FSMContext):
    """Обрабатывает цену товара"""
    # Проверяем, не отмена ли это
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        return await message.answer("✅ Операция отменена")
    
    try:
        price = int(message.text.strip())
        if price <= 0:
            return await message.answer("❌ Цена должна быть положительным числом. Попробуйте снова или /cancel для отмены:")
    except ValueError:
        return await message.answer("❌ Неверный формат цены. Введите только число или /cancel для отмены:")
    
    await state.update_data(price=price)
    await state.set_state(AddProduct.waiting_image)
    await message.answer(
        f"✅ Цена: <b>{price} ₽</b>\n\n"
        "🖼️ <b>Шаг 3/5:</b> Выберите эмодзи для товара:",
        reply_markup=get_image_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("img_"), AddProduct.waiting_image)
async def process_image(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор эмодзи"""
    image = callback.data.replace("img_", "")
    
    if image == "skip":
        image = "🛞"  # Значение по умолчанию
    
    await state.update_data(image=image)
    await state.set_state(AddProduct.waiting_description)
    await callback.message.edit_text(
        f"✅ Эмодзи: <b>{image}</b>\n\n"
        "📄 <b>Шаг 4/5:</b> Введите описание товара (или отправьте \"-\" чтобы пропустить):",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddProduct.waiting_description)
async def process_description(message: Message, state: FSMContext):
    """Обрабатывает описание товара"""
    # Проверяем, не отмена ли это
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        return await message.answer("✅ Операция отменена")
    
    description = message.text.strip()
    if description == "-":
        description = ""
    
    await state.update_data(description=description)
    await state.set_state(AddProduct.waiting_specs)
    await message.answer(
        f"✅ Описание: <b>{description or 'не указано'}</b>\n\n"
        "🏷️ <b>Шаг 5/5:</b> Введите характеристики товара через запятую\n"
        "(например: Летняя, 245/60R18, All-Terrain, Speed H)\n"
        "Или отправьте \"-\" чтобы пропустить, или /cancel для отмены:",
        parse_mode="HTML"
    )


@dp.message(AddProduct.waiting_specs)
async def process_specs(message: Message, state: FSMContext):
    """Обрабатывает характеристики и показывает превью для подтверждения"""
    # Проверяем, не отмена ли это
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        return await message.answer("✅ Операция отменена")
    
    specs_text = message.text.strip()
    
    if specs_text == "-":
        specs = []
    else:
        specs = [s.strip() for s in specs_text.split(",") if s.strip()]
    
    await state.update_data(specs=specs)
    await state.set_state(AddProduct.confirming)
    
    data = await state.get_data()
    
    preview = (
        "📋 <b>Превью товара:</b>\n\n"
        f"📝 <b>Название:</b> {data['name']}\n"
        f"💰 <b>Цена:</b> {data['price']} ₽\n"
        f"🖼️ <b>Эмодзи:</b> {data['image']}\n"
        f"📄 <b>Описание:</b> {data.get('description', 'не указано') or 'не указано'}\n"
        f"🏷️ <b>Характеристики:</b> {', '.join(specs) if specs else 'не указано'}\n\n"
        "✅ Сохранить товар?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, сохранить", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_no")
        ]
    ])
    
    await message.answer(preview, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "confirm_yes", AddProduct.confirming)
async def confirm_add(callback: CallbackQuery, state: FSMContext):
    """Сохраняет товар в базу данных"""
    data = await state.get_data()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products(name, price, image, description, specs) VALUES(?,?,?,?,?)",
            (
                data['name'],
                data['price'],
                data['image'],
                data.get('description', ''),
                json.dumps(data.get('specs', []), ensure_ascii=False)
            ),
        )
        await db.commit()
    
    await callback.message.edit_text(
        f"✅ <b>Товар успешно добавлен!</b>\n\n"
        f"📝 {data['name']}\n"
        f"💰 {data['price']} ₽\n"
        f"🖼️ {data['image']}",
        parse_mode="HTML"
    )
    await callback.answer("Товар добавлен!")
    await state.clear()


@dp.callback_query(F.data == "confirm_no", AddProduct.confirming)
async def cancel_add(callback: CallbackQuery, state: FSMContext):
    """Отменяет добавление товара"""
    await callback.message.edit_text("❌ Добавление товара отменено")
    await callback.answer()
    await state.clear()


# --- RUNNERS ---

async def run_api():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await init_db()
    # Запускаем и API и Бота параллельно
    await asyncio.gather(run_api(), dp.start_polling(bot))


if __name__ == "__main__":
    asyncio.run(main())
