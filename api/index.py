"""
Vercel serverless function для обработки всех API запросов
"""
import sys
import os
import traceback

# Добавляем корневую директорию в путь для импорта bot.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Устанавливаем переменную окружения для Vercel
os.environ["VERCEL"] = "1"

# Импортируем с обработкой ошибок
try:
    from mangum import Mangum
    from bot import app
    
    # Создаем handler для Vercel
    # Vercel автоматически ищет переменную handler
    handler = Mangum(app, lifespan="off")
except Exception as e:
    # Логируем ошибку при импорте для отладки
    error_msg = f"Ошибка при импорте: {e}"
    print(error_msg)
    traceback.print_exc()
    
    # Создаем простой handler для отображения ошибки
    def handler(event, context):
        import json
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": error_msg, "type": type(e).__name__})
        }
