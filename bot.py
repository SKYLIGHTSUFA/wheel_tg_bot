import os
import json
import asyncio
from typing import List, Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

BOT_TOKEN = "7854473349:AAEImt52KG7VHaaKzBXwHhEAuB2t94Onukw"  # задайте переменную окружения
DB_PATH = os.environ.get("DB_PATH", "db.sqlite3")

# ВАЖНО: сюда добавим id админов (числа).
ADMIN_IDS = set()  # например {123456789}

# Куда слать заказы (ваша группа):
ORDERS_CHAT = "@KolesaUfa02"

app = FastAPI(title="KolesaUfa API")

# CORS, чтобы GitHub Pages мог дергать API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # потом можно ужесточить
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

dp = Dispatcher()


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


@app.get("/api/products")
async def api_products():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, price, image, description, specs FROM products WHERE active=1 ORDER BY id DESC"
        )
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


@dp.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await message.answer(f"Ваш user_id: {message.from_user.id}")


@dp.message(Command("setadmin"))
async def cmd_setadmin(message: Message):
    # Временно: первый, кто выполнит /setadmin, становится админом.
    # Потом можно убрать.
    ADMIN_IDS.add(message.from_user.id)
    await message.answer(f"Готово. Добавлен админ: {message.from_user.id}")


@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Нет доступа.")

    # Формат:
    # /add Название | 5200 | 🛞 | Описание | spec1,spec2,spec3
    text = message.text or ""
    payload = text.removeprefix("/add").strip()
    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 2:
        return await message.answer(
            "Формат:\n/add Название | Цена | (эмодзи) | (описание) | (spec1,spec2,...)"
        )

    name = parts[0]
    price = int(parts[1])
    image = parts[2] if len(parts) >= 3 and parts[2] else "🛞"
    description = parts[3] if len(parts) >= 4 else ""
    specs = []
    if len(parts) >= 5 and parts[4]:
        specs = [s.strip() for s in parts[4].split(",") if s.strip()]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products(name, price, image, description, specs) VALUES(?,?,?,?,?)",
            (name, price, image, description, json.dumps(specs, ensure_ascii=False)),
        )
        await db.commit()

    await message.answer(f"✅ Товар добавлен: {name} — {price} ₽")


@dp.message(Command("list"))
async def cmd_list(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Нет доступа.")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, price, active FROM products ORDER BY id DESC LIMIT 50"
        )
        rows = await cur.fetchall()

    if not rows:
        return await message.answer("Товаров нет. Добавьте через /add")

    lines = ["Список товаров:"]
    for r in rows:
        st = "✅" if r["active"] == 1 else "⛔"
        lines.append(f"{st} #{r['id']} — {r['name']} — {r['price']} ₽")
    await message.answer("\n".join(lines))


@dp.message(Command("del"))
async def cmd_del(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Нет доступа.")

    parts = (message.text or "").split()
    if len(parts) != 2:
        return await message.answer("Формат: /del ID")

    pid = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        await db.commit()

    await message.answer(f"🗑️ Скрыт товар #{pid}")


# Получение заказов из WebApp:
# Приходит как Message.web_app_data.data (строка)
@dp.message(F.web_app_data)
async def webapp_order(message: Message):
    data = message.web_app_data.data  # строка [web:110]
    user = message.from_user

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders(user_id, payload) VALUES(?,?)",
            (user.id if user else None, data),
        )
        await db.commit()

    # Отправим в группу заказов
    try:
        payload = json.loads(data)
    except Exception:
        payload = {"raw": data}

    # Красивый текст
    lines = ["🧾 Новый заказ из Mini App"]
    if user:
        lines.append(f"Пользователь: {user.full_name} (id={user.id})")
        if user.username:
            lines.append(f"Username: @{user.username}")

    if payload.get("type") == "order":
        lines.append("Товары:")
        for it in payload.get("items", []):
            lines.append(f"• {it.get('name')} — {it.get('qty')} шт × {it.get('price')} ₽")
        lines.append(f"Итого: {payload.get('total')} ₽")
    else:
        lines.append(f"Данные: {data}")

    await message.bot.send_message(ORDERS_CHAT, "\n".join(lines))  # можно @username группы [web:106]
    await message.answer("✅ Заказ отправлен менеджеру.")


async def run_bot(bot: Bot):
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def run_api():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await init_db()
    bot = Bot(BOT_TOKEN)
    await asyncio.gather(run_api(), run_bot(bot))


if __name__ == "__main__":
    asyncio.run(main())
