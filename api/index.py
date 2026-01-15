"""
Vercel serverless function для обработки всех API запросов
"""
import sys
import os
import asyncio

# Добавляем корневую директорию в путь для импорта bot.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Устанавливаем переменную окружения для Vercel
os.environ["VERCEL"] = "1"

from mangum import Mangum
from bot import app, init_db

# Инициализируем БД при первом импорте
# Используем asyncio для инициализации
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

if not loop.is_running():
    loop.run_until_complete(init_db())

# Создаем handler для Vercel
handler = Mangum(app, lifespan="off")

def lambda_handler(event, context):
    """Vercel serverless function handler"""
    return handler(event, context)
