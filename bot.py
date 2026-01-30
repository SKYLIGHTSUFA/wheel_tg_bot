import os
import json
import asyncio
import signal
import sys
from typing import List, Optional
import logging
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.filters.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response
from pydantic import BaseModel
import uvicorn
import shutil
import uuid

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8576138519:AAES_lBttGBQ-cvJ_HvcDjTNzYyoGYBOneE")
# Путь к базе данных (локально)
DB_PATH = os.environ.get("DB_PATH", "db.sqlite3")
ORDERS_CHAT = "@KolesaUfa02"  # Куда будут приходить уведомления
# WEBAPP_URL для Tuna туннеля
# Получается из переменной окружения или устанавливается вручную
# После запуска `tuna http 7070` вы получите URL вида: https://xxxxx.tuna.am
_webapp_url_raw = os.environ.get("WEBAPP_URL", "https://wheel.ru.tuna.am")
WEBAPP_URL = _webapp_url_raw.rstrip('/') if _webapp_url_raw else ""
SHOP_ADDRESS = os.environ.get("SHOP_ADDRESS", "г. Уфа, ул. Трамвайная, д. 13/1")
SHOP_PHONE = os.environ.get("SHOP_PHONE", "+79177364777")
SHOP_PHONES = {
    "warehouse_1": "+79613722902",  # Склад, рабочий номер
    "warehouse_2": "+79962853700",  # Склад, рабочий номер
    "consultation": "+79371512083"  # Консультация
}
SHOP_HOURS = "Работаем без выходных с 09:00 до 21:00"
SHOP_DELIVERY = "Отправка транспортной компанией"

# Создаем бота глобально, чтобы к нему был доступ из API
bot = Bot(BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
app = FastAPI(title="KolesaUfa API")

# Флаг для ленивой инициализации БД
_db_initialized = False


# --- MIDDLEWARE для туннелей и WebApp ---
class WebAppMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        # Разрешаем встраивание в iframe (для Telegram WebApp)
        response.headers["X-Frame-Options"] = "ALLOWALL"
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        # Заголовки для различных туннелей (ngrok, cloudflare и т.д.)
        response.headers["ngrok-skip-browser-warning"] = "true"
        return response


app.add_middleware(WebAppMiddleware)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "ngrok-skip-browser-warning"],
    expose_headers=["*"],
)


# --- MIDDLEWARE для инициализации БД ---
@app.middleware("http")
async def init_db_middleware(request: Request, call_next):
    """Ленивая инициализация БД при первом запросе"""
    global _db_initialized
    if not _db_initialized:
        try:
            await init_db()
            _db_initialized = True
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
    return await call_next(request)


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
    phone: Optional[str] = None  # для обратной связи, если нет telegram username
    items: List[OrderItem]
    total: int
    comment: Optional[str] = ""
    payment_method: Optional[str] = "cash"  # cash, sbp, qr


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
            payment_method TEXT DEFAULT 'cash',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.commit()

        # Добавляем колонку payment_method, если её нет (для существующих БД)
        try:
            cur = await db.execute("PRAGMA table_info(orders)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]
            if 'payment_method' not in column_names:
                await db.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'cash'")
                await db.commit()
        except Exception as e:
            logger.warning(f"Ошибка при миграции БД (возможно, колонка уже существует): {e}")

        # Загружаем админов из БД в память
        await load_admins_from_db()


async def load_admins_from_db():
    """Загружает список админов из базы данных"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT user_id FROM admins")
            rows = await cur.fetchall()
            ADMIN_IDS.clear()
            for row in rows:
                ADMIN_IDS.add(row[0])
            logger.info(f"Загружено {len(ADMIN_IDS)} администраторов из БД")
    except Exception as e:
        logger.error(f"Ошибка загрузки админов из БД: {e}")


def is_admin(user_id: Optional[int]) -> bool:
    result = user_id is not None and user_id in ADMIN_IDS
    logger.debug(f"Проверка прав админа для user_id={user_id}: {result}, ADMIN_IDS={ADMIN_IDS}")
    return result


# --- API ENDPOINTS ---

def get_webapp_url(request: Request = None) -> str:
    """Получает URL WebApp из переменной окружения или генерирует из запроса"""
    if WEBAPP_URL:
        return WEBAPP_URL
    if request:
        return str(request.url).rstrip('/').replace('/index.html', '')
    return ""


@app.get("/api/health")
async def health_check():
    """Проверка работоспособности API"""
    return {
        "status": "ok",
        "db_path": DB_PATH,
        "webapp_url": WEBAPP_URL
    }


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Возвращает index.html для Telegram WebApp"""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            # Заменяем пустой API_URL на текущий домен
            current_url = str(request.url).rstrip('/')
            html_content = html_content.replace('const API_URL = window.location.origin || "";',
                                                f'const API_URL = "{current_url}";')
            # Добавляем заголовки для WebApp
            response = HTMLResponse(content=html_content)
            response.headers["ngrok-skip-browser-warning"] = "true"
            response.headers["X-Frame-Options"] = "ALLOWALL"
            return response
    except FileNotFoundError:
        return HTMLResponse(content="<h1>WebApp not found</h1>", status_code=404)


@app.get("/index.html", response_class=HTMLResponse)
async def index_html(request: Request):
    """Альтернативный путь к index.html"""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            # Заменяем пустой API_URL на текущий домен
            current_url = str(request.url).rstrip('/').replace('/index.html', '')
            html_content = html_content.replace('const API_URL = window.location.origin || "";',
                                                f'const API_URL = "{current_url}";')
            # Добавляем заголовки для WebApp
            response = HTMLResponse(content=html_content)
            response.headers["ngrok-skip-browser-warning"] = "true"
            response.headers["X-Frame-Options"] = "ALLOWALL"
            return response
    except FileNotFoundError:
        return HTMLResponse(content="<h1>WebApp not found</h1>", status_code=404)


@app.get("/api/products")
async def api_products(admin: bool = False):
    """Возвращает список товаров. Если admin=True, возвращает все товары включая неактивные"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if admin:
            cur = await db.execute("SELECT * FROM products ORDER BY id DESC")
        else:
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
            "active": r["active"] if admin else None,
        })
    return out


@app.delete("/api/products/{product_id}")
async def delete_product(product_id: int):
    """Удаляет товар (помечает как неактивный)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
        await db.commit()
    return {"status": "ok", "message": "Товар удален"}


@app.post("/api/products/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Загружает изображение товара и возвращает путь к нему"""
    # Создаем папку для изображений, если её нет
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    # Генерируем уникальное имя файла
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    file_name = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(upload_dir, file_name)

    # Сохраняем файл
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Возвращаем относительный путь для использования в API
    return {"status": "ok", "image_path": f"/api/uploads/{file_name}"}


@app.get("/api/uploads/{filename}")
async def get_uploaded_image(filename: str):
    """Возвращает загруженное изображение"""
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    file_path = os.path.join(upload_dir, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    else:
        return JSONResponse(status_code=404, content={"error": "File not found"})


@app.get("/api/payment-config")
async def get_payment_config():
    """Возвращает конфигурацию для способов оплаты"""
    return {
        "shop_address": SHOP_ADDRESS,
        "shop_phone": SHOP_PHONE,
        "shop_phones": SHOP_PHONES,
        "shop_hours": SHOP_HOURS,
        "shop_delivery": SHOP_DELIVERY,
        "methods": {
            "cash": {"name": "Наличными", "available": True}
        }
    }


# НОВЫЙ МЕТОД: Принимает заказ напрямую через HTTP
@app.post("/api/order")
async def create_order(order: OrderRequest):
    # 1. Сохраняем в БД и получаем порядковый номер заказа
    payload_json = order.model_dump_json()
    payment_method = order.payment_method or "cash"
    order_number = None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO orders(user_id, payload, payment_method) VALUES(?,?,?)",
            (order.user_id, payload_json, payment_method),
        )
        order_number = cur.lastrowid
        await db.commit()

    # 2. Формируем текст сообщения
    lines = [f"🧾 <b>Новый заказ №{order_number} (через API)</b>"]
    if order.full_name:
        user_link = f"<a href='tg://user?id={order.user_id}'>{order.full_name}</a>"
        lines.append(f"👤 Клиент: {user_link} (ID: {order.user_id})")
    if order.username:
        lines.append(f"👤 Username: @{order.username}")
    if not order.username and order.phone:
        lines.append(f"📞 Телефон для связи: {order.phone}")
    if order.comment:
        lines.append(f"📝 {order.comment}")

    lines.append("\n🛒 <b>Товары:</b>")
    for item in order.items:
        lines.append(f"• {item.name} (x{item.qty}) — {item.price * item.qty} ₽")

    lines.append(f"\n💰 <b>Итого: {order.total} ₽</b>")

    # Добавляем информацию о способе оплаты
    payment_method = order.payment_method or "cash"
    payment_emoji = {
        "cash": "💵",
        "sbp": "📱",
        "qr": "📲"
    }
    payment_name = {
        "cash": "Наличными",
        "sbp": "СБП (Система быстрых платежей)",
        "qr": "QR-код"
    }
    lines.append(
        f"\n💳 <b>Способ оплаты:</b> {payment_emoji.get(payment_method, '💵')} {payment_name.get(payment_method, 'Наличными')}")

    text = "\n".join(lines)

    # 3. Отправляем в чат заказов
    try:
        await bot.send_message(ORDERS_CHAT, text, parse_mode="HTML")
        return {"status": "ok", "message": "Заказ отправлен", "order_number": order_number}
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/set-webhook")
async def set_webhook(webhook_url: str = None):
    """Устанавливает webhook для Telegram бота (для Tuna)"""
    try:
        # Если URL не передан, пытаемся использовать WEBAPP_URL
        if not webhook_url:
            if WEBAPP_URL:
                webhook_url = f"{WEBAPP_URL}/api/webhook"
            else:
                return {"status": "error",
                        "message": "Webhook URL не указан. Установите WEBAPP_URL или передайте webhook_url"}

        # Устанавливаем webhook и удаляем pending updates
        await bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info(f"✅ Webhook установлен: {webhook_url}")
        return {"status": "ok", "message": f"Webhook установлен: {webhook_url}"}
    except Exception as e:
        logger.error(f"❌ Ошибка установки webhook: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/webhook-info")
async def get_webhook_info():
    """Получает информацию о текущем webhook"""
    try:
        webhook_info = await bot.get_webhook_info()
        return {
            "status": "ok",
            "url": webhook_info.url,
            "has_custom_certificate": webhook_info.has_custom_certificate,
            "pending_update_count": webhook_info.pending_update_count
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/webhook")
async def webhook_handler(request: Request):
    """Обработчик webhook от Telegram"""
    try:
        # Получаем тело запроса
        body = await request.body()
        logger.info(f"📥 Получен запрос на /api/webhook, размер: {len(body)} байт")

        # Парсим JSON
        try:
            update_data = await request.json()
        except Exception as json_error:
            # Если не JSON, пытаемся прочитать как строку
            logger.error(f"Ошибка парсинга JSON: {json_error}, body: {body[:500]}")
            return JSONResponse(
                status_code=200,
                content={"status": "error", "message": "Invalid JSON"}
            )

        logger.info(
            f"📨 Обновление получено: update_id={update_data.get('update_id', 'unknown')}, type={list(update_data.keys())[1] if len(update_data) > 1 else 'unknown'}")

        from aiogram.types import Update
        update = Update(**update_data)

        # Обрабатываем обновление асинхронно, чтобы быстро вернуть ответ Telegram
        # Telegram требует ответ в течение 60 секунд
        asyncio.create_task(dp.feed_update(bot, update))
        logger.info(f"🔄 Обновление {update.update_id} поставлено в очередь обработки")

        # Сразу возвращаем успешный ответ Telegram
        return JSONResponse(status_code=200, content={"status": "ok"})
    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {e}", exc_info=True)
        import traceback
        logger.error(traceback.format_exc())
        # Всегда возвращаем 200, чтобы Telegram не считал запрос неудачным
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": str(e)}
        )


# --- BOT HANDLERS ---

@dp.message(Command("start"))
async def start(message: Message):
    logger.info(f"🎯 Получена команда /start от пользователя {message.from_user.id} (@{message.from_user.username})")
    # Получаем URL WebApp
    webapp_url = WEBAPP_URL if WEBAPP_URL else ""  # URL от Tuna туннеля

    # WebApp кнопки можно использовать только в приватных чатах
    # Проверяем тип чата (в aiogram 3.x это строка: "private", "group", "supergroup", "channel")
    if message.chat.type == "private":
        # В приватном чате показываем WebApp кнопку
        if webapp_url:
            # Добавляем параметр версии к URL для предотвращения кэширования старого приложения
            # Это гарантирует, что всегда открывается актуальная версия
            separator = "&" if "?" in webapp_url else "?"
            webapp_url_with_version = f"{webapp_url}{separator}v={int(__import__('time').time())}"
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🛞 Открыть магазин", web_app=WebAppInfo(url=webapp_url_with_version))]],
                resize_keyboard=True
            )
            await message.answer("Откройте магазин кнопкой ниже:", reply_markup=kb)
        else:
            await message.answer(
                "⚠️ <b>WebApp URL не настроен</b>\n\n"
                "Для работы с Tuna туннелем:\n"
                "1. Установите Tuna CLI: <code>curl -sSL https://tuna.am/install.sh | bash</code>\n"
                "2. Запустите туннель: <code>tuna http 8000</code>\n"
                "3. Установите переменную окружения WEBAPP_URL с полученным URL\n"
                "4. Установите USE_WEBHOOK=true для использования webhook\n"
                "5. Или установите WEBAPP_URL вручную в формате: https://xxxxx.tuna.am",
                parse_mode="HTML"
            )
    else:
        # В группах и каналах отправляем просто ссылку без WebApp кнопки
        await message.answer(
            f"🛞 <b>Магазин шин</b>\n\n"
            f"Для работы с магазином перейдите в приватный чат с ботом и используйте команду /start\n\n"
            f"{'Или откройте магазин напрямую: ' + webapp_url if webapp_url else 'WebApp URL не настроен'}",
            parse_mode="HTML"
        )


@dp.message(Command("setadmin"))
async def cmd_setadmin(message: Message):
    """Добавляет пользователя в список администраторов"""
    user_id = message.from_user.id
    username = message.from_user.username or "без username"

    try:
        # Добавляем в память
        ADMIN_IDS.add(user_id)

        # Сохраняем в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO admins (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            await db.commit()

        logger.info(f"✅ Добавлен администратор: user_id={user_id}, username=@{username}")
        await message.answer(
            f"✅ <b>Готово!</b>\n\n"
            f"Добавлен администратор:\n"
            f"ID: <code>{user_id}</code>\n"
            f"Username: @{username}\n\n"
            f"Теперь вы можете использовать административные команды.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка добавления админа: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при добавлении администратора: {e}")


@dp.message(Command("webhook"))
async def cmd_webhook(message: Message):
    """Управление webhook (только для админов)"""
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав администратора")

    try:
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url and webhook_info.url != "":
            await message.answer(
                f"📡 <b>Webhook активен</b>\n\n"
                f"URL: <code>{webhook_info.url}</code>\n"
                f"Pending updates: {webhook_info.pending_update_count}\n\n"
                f"Используйте /deletewebhook для удаления",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "ℹ️ <b>Webhook не установлен</b>\n\n"
                "Используйте polling для получения обновлений.\n"
                "Для установки webhook используйте API endpoint /api/set-webhook",
                parse_mode="HTML"
            )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("deletewebhook"))
async def cmd_delete_webhook(message: Message):
    """Удаляет webhook (только для админов)"""
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав администратора")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await message.answer(
            "✅ <b>Webhook удален</b>\n\n"
            "Теперь можно использовать polling. Перезапустите приложение.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при удалении webhook: {e}")


@dp.message(Command("products"))
async def cmd_products(message: Message):
    """Показывает список всех товаров с возможностью удаления (только для админов)"""
    user_id = message.from_user.id
    logger.info(f"Команда /products от user_id={user_id}, is_admin={is_admin(user_id)}, ADMIN_IDS={ADMIN_IDS}")

    if not is_admin(user_id):
        await message.answer(
            "❌ <b>У вас нет прав администратора</b>\n\n"
            "Используйте команду /setadmin для получения прав администратора.",
            parse_mode="HTML"
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM products ORDER BY id DESC LIMIT 20")
        rows = await cur.fetchall()

    if not rows:
        return await message.answer("📦 Товаров пока нет. Используйте /add для добавления.")

    text_lines = ["📦 <b>Список товаров:</b>\n"]
    buttons = []

    for r in rows:
        status = "✅" if r["active"] else "❌"
        text_lines.append(f"{status} <b>{r['name']}</b> — {r['price']} ₽ (ID: {r['id']})")
        buttons.append([InlineKeyboardButton(
            text=f"{'❌ Удалить' if r['active'] else '✅ Восстановить'} {r['name']}",
            callback_data=f"toggle_product_{r['id']}"
        )])

    text = "\n".join(text_lines)
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("toggle_product_"))
async def toggle_product(callback: CallbackQuery):
    """Переключает статус товара (активный/неактивный)"""
    user_id = callback.from_user.id
    logger.info(f"Callback toggle_product от user_id={user_id}, is_admin={is_admin(user_id)}, ADMIN_IDS={ADMIN_IDS}")

    if not is_admin(user_id):
        await callback.answer("❌ У вас нет прав администратора", show_alert=True)
        return

    product_id = int(callback.data.replace("toggle_product_", ""))

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем текущий статус
        cur = await db.execute("SELECT active FROM products WHERE id=?", (product_id,))
        row = await cur.fetchone()
        if not row:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return

        new_status = 0 if row[0] else 1
        await db.execute("UPDATE products SET active=? WHERE id=?", (new_status, product_id))
        await db.commit()

    action = "удален" if new_status == 0 else "восстановлен"
    await callback.answer(f"✅ Товар {action}")

    # Обновляем сообщение
    await cmd_products(callback.message)


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
            return await message.answer(
                "❌ Цена должна быть положительным числом. Попробуйте снова или /cancel для отмены:")
    except ValueError:
        return await message.answer("❌ Неверный формат цены. Введите только число или /cancel для отмены:")

    await state.update_data(price=price)
    await state.set_state(AddProduct.waiting_image)
    await message.answer(
        f"✅ Цена: <b>{price} ₽</b>\n\n"
        "🖼️ <b>Шаг 3/5:</b> Добавьте изображение товара:\n\n"
        "📸 <b>Варианты:</b>\n"
        "• Отправьте <b>фото</b> товара (просто отправьте изображение)\n"
        "• Выберите <b>эмодзи</b> из кнопок ниже\n"
        "• Отправьте <b>\"-\"</b> чтобы пропустить (будет использован эмодзи 🛞)\n\n"
        "💡 <i>Рекомендуется отправлять фото товара для лучшего отображения в магазине</i>",
        reply_markup=get_image_keyboard(),
        parse_mode="HTML"
    )


@dp.message(AddProduct.waiting_image)
async def process_image(message: Message, state: FSMContext):
    """Обрабатывает изображение товара (фото или эмодзи)"""
    # Проверяем, не отмена ли это
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        return await message.answer("✅ Операция отменена")

    image = "🛞"  # Значение по умолчанию

    # Если отправлено фото
    if message.photo:
        # Берем самое большое фото
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        file_path = file_info.file_path

        # Сохраняем фото локально
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        file_ext = os.path.splitext(file_path)[1] or ".jpg"
        file_name = f"{uuid.uuid4()}{file_ext}"
        local_path = os.path.join(upload_dir, file_name)

        # Скачиваем файл
        await bot.download_file(file_path, local_path)

        # Сохраняем путь к изображению
        image = f"/api/uploads/{file_name}"
        await state.update_data(image=image)
        await state.set_state(AddProduct.waiting_description)
        await message.answer(
            f"✅ <b>Фото успешно загружено!</b>\n\n"
            f"📸 Изображение сохранено и будет отображаться в карточке товара\n\n"
            "📄 <b>Шаг 4/5:</b> Введите описание товара (или отправьте \"-\" чтобы пропустить):",
            parse_mode="HTML"
        )
    elif message.text:
        # Если текст, используем как эмодзи или URL
        text = message.text.strip()
        if text == "-":
            image = "🛞"
        # Если это URL или путь, используем его
        elif text.startswith("http") or text.startswith("/api/"):
            image = text
        else:
            # Иначе используем как эмодзи
            image = text[:1] if len(text) > 0 else "🛞"

        await state.update_data(image=image)
        await state.set_state(AddProduct.waiting_description)
        await message.answer(
            f"✅ Изображение: <b>{image}</b>\n\n"
            "📄 <b>Шаг 4/5:</b> Введите описание товара (или отправьте \"-\" чтобы пропустить):",
            parse_mode="HTML"
        )


@dp.callback_query(F.data.startswith("img_"), StateFilter(AddProduct.waiting_image))
async def process_image_emoji(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор эмодзи через кнопку"""
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
        return await message.answer("✅ Операция отменена    ")

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


@dp.callback_query(F.data == "confirm_yes")
async def confirm_add(callback: CallbackQuery, state: FSMContext):
    """Сохраняет товар в базу данных"""
    try:
        data = await state.get_data()
        logger.info(f"Получены данные для сохранения: {data}")

        # Проверяем наличие необходимых данных
        if not data or 'name' not in data or 'price' not in data:
            logger.warning(f"Недостаточно данных для сохранения: {data}")
            await callback.answer("❌ Ошибка: данные не найдены. Начните добавление товара заново.", show_alert=True)
            await state.clear()
            return

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
            logger.info(f"Товар сохранен в БД: {data['name']}")

        await callback.answer("Товар добавлен!")
        await callback.message.edit_text(
            f"✅ <b>Товар успешно добавлен!</b>\n\n"
            f"📝 {data['name']}\n"
            f"💰 {data['price']} ₽\n"
            f"🖼️ {data['image']}",
            parse_mode="HTML"
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при сохранении товара: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при сохранении товара", show_alert=True)
        try:
            await callback.message.edit_text("❌ Произошла ошибка при сохранении товара. Попробуйте снова.")
        except:
            pass


@dp.callback_query(F.data == "confirm_no")
async def cancel_add(callback: CallbackQuery, state: FSMContext):
    """Отменяет добавление товара"""
    await callback.answer("Операция отменена")
    await callback.message.edit_text("❌ Добавление товара отменено")
    await state.clear()


# --- RUNNERS ---

async def run_api():
    port = int(os.environ.get("PORT", "7070"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    logger.info(f"🌐 API сервер запущен на порту {port}")
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot():
    """Запускает бота с правильной обработкой webhook и ошибок"""
    try:
        # Проверяем текущий статус webhook
        webhook_info = await bot.get_webhook_info()
        has_active_webhook = webhook_info.url and webhook_info.url != ""

        # Проверяем, нужно ли использовать webhook или polling
        use_webhook = os.environ.get("USE_WEBHOOK", "false").lower() == "true"

        # Если USE_WEBHOOK=true и есть WEBAPP_URL, используем webhook
        if use_webhook and WEBAPP_URL:
            webhook_url = f"{WEBAPP_URL}/api/webhook"
            logger.info(f"Устанавливаем webhook: {webhook_url}")
            await bot.set_webhook(webhook_url, drop_pending_updates=True)
            logger.info("✅ Webhook установлен. Бот работает через Tuna туннель.")
            logger.info("📡 Обновления будут приходить через /api/webhook endpoint")
            # При использовании webhook бот обрабатывается через API endpoint
            # Не запускаем polling, просто ждем
            while True:
                await asyncio.sleep(3600)  # Ждем час, чтобы не завершать задачу
        else:
            # Используем polling (по умолчанию)
            if has_active_webhook:
                logger.warning(f"⚠️  Обнаружен активный webhook: {webhook_info.url}")
                logger.info("Удаляем webhook для использования polling...")

            # ВСЕГДА отменяем webhook перед запуском polling
            try:
                await bot.delete_webhook(drop_pending_updates=True)
                logger.info("✅ Webhook удален. Запускаем polling...")
                await asyncio.sleep(2)  # Даем время для завершения операций
            except Exception as webhook_error:
                logger.warning(f"⚠️  Ошибка при удалении webhook: {webhook_error}")
                # Пытаемся продолжить, возможно webhook уже удален

            # Запускаем polling
            logger.info("🔄 Запуск polling...")
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=True
            )
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}", exc_info=True)
        raise


async def shutdown_bot():
    """Корректно завершает работу бота"""
    logger.info("Завершение работы бота...")
    await bot.session.close()
    logger.info("Бот остановлен")


async def main():
    """Главная функция запуска приложения"""
    try:
        logger.info("Инициализация базы данных...")
        await init_db()
        logger.info("База данных инициализирована")
        logger.info(f"Загружено администраторов: {len(ADMIN_IDS)} - {ADMIN_IDS}")

        logger.info("Запуск API сервера и бота...")

        # Создаем задачи для параллельного запуска
        api_task = asyncio.create_task(run_api())
        bot_task = asyncio.create_task(run_bot())

        # Запускаем обе задачи параллельно
        # Если одна из них упадет, другая продолжит работать
        results = await asyncio.gather(
            api_task,
            bot_task,
            return_exceptions=True
        )

        # Проверяем результаты
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                task_name = "API" if i == 0 else "Bot"
                logger.error(f"Задача {task_name} завершилась с ошибкой: {result}", exc_info=True)
            else:
                task_name = "API" if i == 0 else "Bot"
                logger.info(f"Задача {task_name} завершена")

    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt. Завершение работы...")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        logger.info("Очистка ресурсов...")
        await shutdown_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем")
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}", exc_info=True)
        sys.exit(1)