import os
import json
import asyncio
from typing import List, Optional
import logging
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "7854473349:AAEImt52KG7VHaaKzBXwHhEAuB2t94Onukw"
DB_PATH = os.environ.get("DB_PATH", "db.sqlite3")
ORDERS_CHAT = "@KolesaUfa02"  # Куда будут приходить уведомления
WEBAPP_URL = "https://wheel-tg-bot.onrender.com"  # ВАЖНО: Укажите здесь ваш актуальный 

# Создаем бота глобально, чтобы к нему был доступ из API
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
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


@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not is_admin(message.from_user.id): return
    text = message.text or ""
    payload = text.removeprefix("/add").strip()
    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 2:
        return await message.answer("Формат: /add Название | Цена | Эмодзи")

    name = parts[0]
    price = int(parts[1])
    image = parts[2] if len(parts) >= 3 and parts[2] else "🛞"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products(name, price, image, description, specs) VALUES(?,?,?,?,?)",
            (name, price, image, "", "[]"),
        )
        await db.commit()
    await message.answer(f"✅ Товар добавлен: {name}")


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
