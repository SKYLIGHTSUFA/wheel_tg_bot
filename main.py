#!/usr/bin/env python3
"""
TireShop Telegram Mini App Backend
Flask API для сохранения заказов и бронирований
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
from datetime import datetime
import hashlib
import hmac
import json
import os

app = Flask(__name__)
CORS(app)

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7854473349:AAEImt52KG7VHaaKzBXwHhEAuB2t94Onukw')
DATABASE = 'tire_shop.db'


# ============ Database ============

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Таблица заказов
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        user_name TEXT,
        phone TEXT,
        products TEXT,
        total_price REAL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Таблица бронирований
    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT,
        user_name TEXT,
        phone TEXT,
        quantity INTEGER,
        comment TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Таблица товаров (для управления через админ-панель)
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        description TEXT,
        specs TEXT,
        stock INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    conn.commit()
    conn.close()


def get_db():
    """Получить подключение к БД"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ============ Telegram Verification ============

def verify_telegram_data(init_data, token=TELEGRAM_BOT_TOKEN):
    """Проверить подлинность данных от Telegram"""
    try:
        if not init_data:
            return False

        # Парсим строку
        data_dict = {}
        for pair in init_data.split('&'):
            if '=' in pair:
                key, value = pair.split('=', 1)
                data_dict[key] = value

        # Извлекаем hash
        hash_received = data_dict.pop('hash', None)
        if not hash_received:
            return False

        # Создаем check string
        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(data_dict.items())
        )

        # Вычисляем хеш
        secret_key = hashlib.sha256(token.encode()).digest()
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        return computed_hash == hash_received
    except Exception as e:
        print(f"Verification error: {e}")
        return False


# ============ API Routes ============

@app.route('/api/products', methods=['GET'])
def get_products():
    """Получить список товаров"""
    products = [
        {
            "id": 1,
            "name": "Michelin Latitude",
            "price": 5200,
            "image": "🛞",
            "description": "Универсальная летняя шина для внедорожников",
            "specs": ["Summer", "245/60R18", "All-Terrain", "Speed H"]
        },
        {
            "id": 2,
            "name": "Continental WinterContact",
            "price": 4800,
            "image": "❄️",
            "description": "Зимняя шина с улучшенным сцеплением на льду",
            "specs": ["Winter", "205/55R16", "Ice Grip", "Speed T"]
        },
        {
            "id": 3,
            "name": "Pirelli Cinturato",
            "price": 3900,
            "image": "🎯",
            "description": "Экономичная летняя шина для легковых автомобилей",
            "specs": ["Summer", "195/65R15", "Eco", "Speed V"]
        },
        {
            "id": 4,
            "name": "Goodyear Assurance",
            "price": 4500,
            "image": "⭐",
            "description": "Премиальная зимняя шина с долгим сроком службы",
            "specs": ["Winter", "215/60R17", "Long Life", "Speed H"]
        },
        {
            "id": 5,
            "name": "Dunlop SP Sport",
            "price": 3600,
            "image": "🏁",
            "description": "Спортивная шина для динамичного вождения",
            "specs": ["Summer", "225/45R17", "Performance", "Speed W"]
        },
        {
            "id": 6,
            "name": "Bridgestone Blizzak",
            "price": 5100,
            "image": "🌨️",
            "description": "Премиальная зимняя шина японского производства",
            "specs": ["Winter", "225/50R17", "Super Grip", "Speed T"]
        }
    ]
    return jsonify(products)


@app.route('/api/orders', methods=['POST'])
def create_order():
    """Создать новый заказ"""
    data = request.get_json()

    # Валидация
    if not data.get('name') or not data.get('phone'):
        return jsonify({"error": "Name and phone are required"}), 400

    if not data.get('products'):
        return jsonify({"error": "Products list is required"}), 400

    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('''INSERT INTO orders 
                     (user_id, user_name, phone, products, total_price, status)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (
                      data.get('user_id', 'unknown'),
                      data.get('name'),
                      data.get('phone'),
                      json.dumps(data.get('products')),
                      data.get('total', 0),
                      'pending'
                  ))

        order_id = c.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Order created successfully",
            "order_id": order_id
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/bookings', methods=['POST'])
def create_booking():
    """Забронировать товар"""
    data = request.get_json()

    # Валидация
    required_fields = ['product_name', 'name', 'phone']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('''INSERT INTO bookings 
                     (product_name, user_name, phone, quantity, comment, status)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (
                      data.get('product_name'),
                      data.get('name'),
                      data.get('phone'),
                      data.get('qty', 1),
                      data.get('comment', ''),
                      'pending'
                  ))

        booking_id = c.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Booking created successfully",
            "booking_id": booking_id
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Получить все заказы (для админ-панели)"""
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT 100')
        orders = [dict(row) for row in c.fetchall()]
        conn.close()

        return jsonify(orders)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/bookings', methods=['GET'])
def get_bookings():
    """Получить все бронирования (для админ-панели)"""
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('SELECT * FROM bookings ORDER BY created_at DESC LIMIT 100')
        bookings = [dict(row) for row in c.fetchall()]
        conn.close()

        return jsonify(bookings)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order(order_id):
    """Получить конкретный заказ"""
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
        order = c.fetchone()
        conn.close()

        if not order:
            return jsonify({"error": "Order not found"}), 404

        return jsonify(dict(order))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orders/<int:order_id>', methods=['PUT'])
def update_order(order_id):
    """Обновить статус заказа"""
    data = request.get_json()
    status = data.get('status', 'pending')

    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Order updated"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({"status": "OK", "message": "TireShop API is running"})


# ============ Error Handlers ============

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal server error"}), 500


# ============ Main ============

if __name__ == '__main__':
    # Инициализация БД
    init_db()

    # Запуск сервера
    print("🚀 TireShop API started on http://localhost:5000")
    print("📚 API Documentation:")
    print("  GET  /api/products     - Get all products")
    print("  GET  /api/orders       - Get all orders")
    print("  POST /api/orders       - Create new order")
    print("  GET  /api/bookings     - Get all bookings")
    print("  POST /api/bookings     - Create new booking")
    print("  GET  /api/health       - Health check")

    app.run(debug=True, host='0.0.0.0', port=5000)
