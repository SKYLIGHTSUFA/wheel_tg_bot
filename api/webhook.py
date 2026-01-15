"""
Vercel serverless function для обработки webhook от Telegram
"""
import sys
import os
import json
import asyncio

# Добавляем корневую директорию в путь для импорта bot.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Устанавливаем переменную окружения для Vercel
os.environ["VERCEL"] = "1"

from bot import bot, dp, init_db
from aiogram.types import Update

# Инициализируем БД при первом импорте
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

if not loop.is_running():
    loop.run_until_complete(init_db())

async def process_update(update_data):
    """Обрабатывает обновление от Telegram"""
    try:
        # Создаем объект Update из данных
        update = Update(**update_data)
        
        # Обрабатываем обновление через dispatcher
        await dp.feed_update(bot, update)
        
        return {"statusCode": 200, "body": "ok"}
    except Exception as e:
        print(f"Ошибка обработки webhook: {e}")
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": str(e)}


def handler(request):
    """Vercel serverless function handler"""
    try:
        # Vercel передает данные в request.body как строку или dict
        body = {}
        
        if hasattr(request, 'body'):
            # Если body - строка, парсим JSON
            if isinstance(request.body, str):
                body = json.loads(request.body)
            elif isinstance(request.body, dict):
                body = request.body
            elif hasattr(request.body, 'read'):
                # Если это file-like объект
                body = json.loads(request.body.read())
        elif isinstance(request, dict):
            # Если request - это dict (Vercel формат)
            body = request.get('body', {})
            if isinstance(body, str):
                body = json.loads(body)
        elif hasattr(request, 'json'):
            body = request.json()
        elif hasattr(request, 'get_json'):
            body = request.get_json(force=True)
        
        # Запускаем async обработку
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_update(body))
            return result
        finally:
            loop.close()
    except Exception as e:
        print(f"Ошибка в handler: {e}")
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": str(e)}
