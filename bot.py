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
# На Vercel файловая система read-only, используем /tmp
# В других окружениях можно использовать обычный путь
_vercel_env = os.environ.get("VERCEL", "0") == "1"
DB_PATH = os.environ.get("DB_PATH") or ("/tmp/db.sqlite3" if _vercel_env else "db.sqlite3")
ORDERS_CHAT = "@KolesaUfa02"  # Куда будут приходить уведомления
# WEBAPP_URL берется из переменной окружения или генерируется автоматически
# Нормализуем URL (убираем слеш в конце)
_webapp_url_raw = os.environ.get("WEBAPP_URL", "https://1b2a4dddb764e0.lhr.life/")   
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


def is_admin(user_id: Optional[int]) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


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
        "vercel": os.environ.get("VERCEL", "0") == "1",
        "db_path": DB_PATH
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
    # 1. Сохраняем в БД
    payload_json = order.model_dump_json()
    payment_method = order.payment_method or "cash"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders(user_id, payload, payment_method) VALUES(?,?,?)",
            (order.user_id, payload_json, payment_method),
        )
        await db.commit()

    # 2. Формируем текст сообщения
    lines = ["🧾 <b>Новый заказ (через API)</b>"]
    if order.full_name:
        user_link = f"<a href='tg://user?id={order.user_id}'>{order.full_name}</a>"
        lines.append(f"👤 Клиент: {user_link} (ID: {order.user_id})")
    if order.username:
        lines.append(f"💬 Комментарий: @{order.username}")

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
    lines.append(f"\n💳 <b>Способ оплаты:</b> {payment_emoji.get(payment_method, '💵')} {payment_name.get(payment_method, 'Наличными')}")

    text = "\n".join(lines)

    # 3. Отправляем в чат заказов
    try:
        await bot.send_message(ORDERS_CHAT, text, parse_mode="HTML")
        return {"status": "ok", "message": "Заказ отправлен"}
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/set-webhook")
async def set_webhook(webhook_url: str = None):
    """Устанавливает webhook для Telegram бота (для Vercel)"""
    try:
        # Если URL не передан, пытаемся получить из переменной окружения
        if not webhook_url:
            vercel_url = os.environ.get("VERCEL_URL")
            if vercel_url:
                webhook_url = f"https://{vercel_url}/api/webhook"
            else:
                return {"status": "error", "message": "Webhook URL не указан"}
        
        # Устанавливаем webhook
        await bot.set_webhook(webhook_url)
        return {"status": "ok", "message": f"Webhook установлен: {webhook_url}"}
    except Exception as e:
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


# --- BOT HANDLERS ---

@dp.message(Command("start"))
async def start(message: Message):
    # Получаем URL WebApp
    webapp_url = WEBAPP_URL if WEBAPP_URL else ""  # URL от localhost.run или другого туннеля
    
    # WebApp кнопки можно использовать только в приватных чатах
    # Проверяем тип чата (в aiogram 3.x это строка: "private", "group", "supergroup", "channel")
    if message.chat.type == "private":
        # В приватном чате показываем WebApp кнопку
        if webapp_url:
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🛞 Открыть магазин", web_app=WebAppInfo(url=webapp_url))]],
                resize_keyboard=True
            )
            await message.answer("Откройте магазин кнопкой ниже:", reply_markup=kb)
        else:
            await message.answer(
                "⚠️ <b>WebApp URL не настроен</b>\n\n"
                "Для работы с localhost.run:\n"
                "1. Запустите туннель: <code>ssh -R 80:localhost:8000 ssh.localhost.run</code>\n"
                "2. Установите переменную окружения WEBAPP_URL с полученным URL\n"
                "3. Или установите WEBAPP_URL вручную в формате: https://xxxxx.localhost.run",
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
    ADMIN_IDS.add(message.from_user.id)
    await message.answer(f"Готово. Добавлен админ: {message.from_user.id}")


@dp.message(Command("products"))
async def cmd_products(message: Message):
    """Показывает список всех товаров с возможностью удаления (только для админов)"""
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав администратора")
    
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
    if not is_admin(callback.from_user.id):
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
            return await message.answer("❌ Цена должна быть положительным числом. Попробуйте снова или /cancel для отмены:")
    except ValueError:
        return await message.answer("❌ Неверный формат цены. Введите только число или /cancel для отмены:")
    
    await state.update_data(price=price)
    await state.set_state(AddProduct.waiting_image)
    await message.answer(
        f"✅ Цена: <b>{price} ₽</b>\n\n"
        "🖼️ <b>Шаг 3/5:</b> Отправьте фото товара, выберите эмодзи или отправьте \"-\" чтобы пропустить:",
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
            f"✅ Фото загружено\n\n"
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
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot():
    """Запускает бота с правильной обработкой webhook и ошибок"""
    try:
        # Отменяем webhook, если он был установлен (важно для предотвращения конфликтов)
        logger.info("Проверяем и отменяем webhook (если был установлен)...")
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook успешно отменен")
            # Небольшая задержка для завершения всех запросов
            await asyncio.sleep(1)
        except Exception as webhook_error:
            logger.warning(f"Ошибка при отмене webhook (возможно, его не было): {webhook_error}")
        
        logger.info("Запускаем polling...")
        
        # Запускаем polling с правильными параметрами
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True  # Игнорируем старые обновления при запуске
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)
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
