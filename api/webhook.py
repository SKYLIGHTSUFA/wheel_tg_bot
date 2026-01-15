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

from bot import bot, dp
from aiogram.types import Update

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
        # Vercel для Python передает request как dict с полями body, headers, method и т.д.
        body = {}
        
        # Получаем body из request
        if isinstance(request, dict):
            # Vercel формат
            body_str = request.get('body', '{}')
            if isinstance(body_str, str):
                body = json.loads(body_str)
            else:
                body = body_str
        elif hasattr(request, 'body'):
            # Если это объект с атрибутом body
            if isinstance(request.body, str):
                body = json.loads(request.body)
            elif isinstance(request.body, dict):
                body = request.body
            elif hasattr(request.body, 'read'):
                body = json.loads(request.body.read())
        elif hasattr(request, 'get_json'):
            body = request.get_json(force=True)
        elif hasattr(request, 'json'):
            body = request.json()
        
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
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
