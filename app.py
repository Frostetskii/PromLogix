import time
import random
import threading
from flask import Flask, request, redirect, url_for, session, render_template_string
from pymongo import MongoClient
import paho.mqtt.client as mqtt

app = Flask(__name__)
app.secret_key = "super_secret_key_for_sessions"

# ==========================================
# 1. ПОДКЛЮЧЕНИЕ К ОБЛАЧНОЙ БД (MongoDB)
# ==========================================
# Вставь сюда скопированную строку подключения из MongoDB Atlas!
MONGO_URI = "mongodb+srv://Kayott:<163361>@promlogix-u.9jbgo7r.mongodb.net/?appName=PromLogix-U"

try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["robo_delivery_db"]
    users_collection = db["users"]
    print("Успешно подключились к облачной базе данных MongoDB!")
except Exception as e:
    print(f"Ошибка подключения к MongoDB: {e}")

# ==========================================
# 2. НАСТРОЙКИ MQTT И СТАТУС РОБОТА
# ==========================================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
ROBOT_ID = "my_unique_robot_id_999"  # Должен быть одинаковым во Flask и на ESP!

# Входящий топик: ESP отправляет сюда UID считанной карты
TOPIC_RFID = f"{ROBOT_ID}/rfid"
# Исходящий топик: Flask отправляет сюда команды ("GO", "OPEN")
TOPIC_CONTROL = f"{ROBOT_ID}/control"

# Глобальное состояние доставки в памяти сервера
delivery_status = {
    "active": False,        # Идет ли сейчас доставка?
    "sender": None,         # Кто отправил деталь
    "recipient": None,      # Кому отправили деталь
    "stage": "idle",        # Стадии: idle, moving, waiting_card, opened
    "eta": 0,               # Оставшееся время симуляции поездки (в секундах)
    "scanned_rfid": None    # UID последней приложенной карты
}

# ==========================================
# 3. НАСТРОЙКА MQTT-КЛИЕНТА НА СЕРВЕРЕ
# ==========================================
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print(f"Flask-сервер подключен к MQTT брокеру с кодом: {rc}")
    # Подписываемся на топик от ESP, чтобы слушать прикладывание карт
    client.subscribe(TOPIC_RFID)
    print(f"Подписались на топик: {TOPIC_RFID}")

def on_message(client, userdata, msg):
    global delivery_status
    payload = msg.payload.decode('utf-8').strip().upper()
    print(f"MQTT Получено сообщение в топик {msg.topic}: {payload}")
    
    # Если пришла RFID карта и робот ждет получателя
    if msg.topic == TOPIC_RFID and delivery_status["stage"] == "waiting_card":
        delivery_status["scanned_rfid"] = payload
        
        # Ищем получателя в базе данных MongoDB
        recipient_name = delivery_status["recipient"]
        recipient_user = users_collection.find_one({"username": recipient_name})
        
        if recipient_user:
            # Сверяем RFID получателя из БД с присланной картой
            correct_rfid = recipient_user.get("rfid", "").strip().upper()
            if payload == correct_rfid:
                print(">>> RFID карта верна! Отправляем команду OPEN роботу...")
                delivery_status["stage"] = "opened"
                # Отправляем физическую команду на ESP открыть замок
                mqtt_client.publish(TOPIC_CONTROL, "OPEN")
            else:
                print(f">>> Карта не совпала. Ждали: {correct_rfid}, получили: {payload}")
        else:
            print(f">>> Ошибка: получатель {recipient_name} не найден в БД!")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# Запускаем MQTT клиент в отдельном фоновом потоке, чтобы он не блокировал Flask-сайт
def start_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"Не удалось подключиться к MQTT: {e}")

mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
mqtt_thread.start()

# ==========================================
# 4. СИМУЛЯЦИЯ ПОЕЗДКИ РОБОТА В ФОНЕ
# ==========================================
def simulate_travel():
    global delivery_status
    while delivery_status["eta"] > 0:
        time.sleep(1)
        delivery_status["eta"] -= 1
    
    # Когда время таймера вышло, робот "прибыл" и ждет карту на ESP
    delivery_status["stage"] = "waiting_card"
    print("Робот прибыл в пункт назначения. Ожидание RFID карты...")

# ==========================================
# 5. HTML ШАБЛОНЫ (ВСТРОЕННЫЕ)
# ==========================================

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Вход - PromLogix</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background-color: #f4f6f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); width: 100%; max-width: 400px; box-sizing: border-box; }
        h2 { text-align: center; color: #333; margin-bottom: 20px; }
        input[type="text"], input[type="password"] { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background: #007bff; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .error { color: red; text-align: center; margin-bottom: 10px; }
        .success { color: green; text-align: center; margin-bottom: 10px; font-weight: bold; }
        .footer { text-align: center; margin-top: 15px; font-size: 14px; }
        .footer a { color: #007bff; text-decoration: none; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Войти в личный кабинет</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        {% if success_msg %}<div class="success">{{ success_msg }}</div>{% endif %}
        <form method="POST" action="/login">
            <input type="text" name="username" placeholder="Логин (Имя)" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit">Войти</button>
        </form>
        <div class="footer">
            Нет аккаунта? <a href="/register">Зарегистрироваться</a>
        </div>
    </div>
</body>
</html>
"""

REGISTER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Регистрация - PromLogix</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background-color: #f4f6f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); width: 100%; max-width: 400px; box-sizing: border-box; }
        h2 { text-align: center; color: #333; margin-bottom: 20px; }
        input[type="text"], input[type="password"] { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background: #28a745; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; }
        button:hover { background: #218838; }
        .error { color: red; text-align: center; margin-bottom: 10px; }
        .hint { font-size: 12px; color: #666; margin-top: -5px; margin-bottom: 10px; display: block; }
        .footer { text-align: center; margin-top: 15px; font-size: 14px; }
        .footer a { color: #007bff; text-decoration: none; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Регистрация</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST" action="/register">
            <input type="text" name="username" placeholder="Придумайте логин" required>
            <input type="password" name="password" placeholder="Придумайте пароль" required>
            <input type="text" name="rfid" placeholder="UID RFID карты (необязательно)">
            <span class="hint">Оставьте пустым для автогенерации карты!</span>
            <button type="submit">Зарегистрироваться</button>
        </form>
        <div class="footer">
            Уже есть аккаунт? <a href="/login">Войти</a>
        </div>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Панель управления - PromLogix</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {% if delivery_active and (stage == 'moving' or stage == 'waiting_card') %}
    <!-- Если идет доставка, страница автоматически обновляется каждые 3 секунды -->
    <meta http-equiv="refresh" content="3">
    {% endif %}
    <style>
        body { font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; background: white; padding: 15px 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; }
        .header h1 { margin: 0; font-size: 24px; color: #333; }
        .logout-btn { background: #dc3545; color: white; padding: 8px 15px; text-decoration: none; border-radius: 4px; }
        .card { background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; }
        h3 { margin-top: 0; color: #007bff; border-bottom: 2px solid #eee; padding-bottom: 10px; }
        .info-row { display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 16px; }
        .info-label { font-weight: bold; color: #555; }
        select, button { width: 100%; padding: 12px; margin-top: 10px; border-radius: 4px; box-sizing: border-box; }
        select { border: 1px solid #ccc; font-size: 16px; }
        .btn-send { background: #007bff; color: white; border: none; font-size: 16px; cursor: pointer; }
        .btn-send:hover { background: #0056b3; }
        .btn-reset { background: #ffc107; color: #212529; border: none; font-size: 16px; cursor: pointer; margin-top: 15px; }
        .status-box { padding: 15px; border-radius: 6px; font-weight: bold; text-align: center; font-size: 18px; margin-top: 15px; }
        .status-idle { background: #e2e3e5; color: #383d41; }
        .status-moving { background: #cce5ff; color: #004085; }
        .status-waiting { background: #fff3cd; color: #856404; }
        .status-opened { background: #d4edda; color: #155724; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Личный кабинет</h1>
            <div>
                <span style="margin-right: 15px;">Привет, <strong>{{ username }}</strong>!</span>
                <a href="/logout" class="logout-btn">Выйти</a>
            </div>
        </div>

        <!-- КАРТОЧКА ПРОФИЛЯ -->
        <div class="card">
            <h3>Ваши данные</h3>
            <div class="info-row">
                <span class="info-label">Ваш RFID UID карты:</span>
                <span style="font-family: monospace; font-size: 18px; background: #eee; padding: 2px 8px; border-radius: 4px;">{{ user_rfid }}</span>
            </div>
            <p style="font-size: 13px; color: #666; margin-bottom: 0;">* Эту карту вы должны прикладывать к ESP, чтобы забрать предназначенную вам деталь.</p>
        </div>

        <!-- КАРТОЧКА ОТПРАВКИ -->
        <div class="card">
            <h3>Отправить деталь</h3>
            
            {% if not delivery_active %}
                <form method="POST" action="/send_robot">
                    <label for="recipient">Выберите получателя из списка зарегистрированных в системе:</label>
                    <select name="recipient" id="recipient" required>
                        <option value="" disabled selected>-- Выберите пользователя --</option>
                        {% for user in all_users %}
                            {% if user != username %}
                                <option value="{{ user }}">{{ user }}</option>
                            {% endif %}
                        {% endfor %}
                    </select>
                    <button type="submit" class="btn-send">Отправить робота 🚀</button>
                </form>
            {% else %}
                <p>Сейчас робот выполняет доставку. Управление временно заблокировано.</p>
            {% endif %}
        </div>

        <!-- КАРТОЧКА СТАТУСА ТЕКУЩЕЙ ДОСТАВКИ -->
        <div class="card">
            <h3>Статус робота-доставщика</h3>
            
            {% if not delivery_active %}
                <div class="status-box status-idle">Робот свободен и стоит на базе. Ожидание заказа.</div>
            {% else %}
                <div class="info-row">
                    <span class="info-label">Отправитель:</span>
                    <span>{{ sender }}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Получатель (владелец ключа):</span>
                    <span>{{ recipient }}</span>
                </div>

                {% if stage == 'moving' %}
                    <div class="status-box status-moving">
                        🚚 Робот едет к получателю... Осталось времени: {{ eta }} сек.
                    </div>
                {% elif stage == 'waiting_card' %}
                    <div class="status-box status-waiting">
                        📍 Робот прибыл в пункт назначения! Приложите RFID карту для открытия ячейки.
                    </div>
                {% elif stage == 'opened' %}
                    <div class="status-box status-opened">
                        🔓 Доступ разрешен! Ячейка открыта, заберите деталь.
                    </div>
                    <form method="POST" action="/reset_robot">
                        <button type="submit" class="btn-reset">Вернуть робота на базу (Очистить статус)</button>
                    </form>
                {% endif %}
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

# ==========================================
# 6. ВЕБ-МАРШРУТЫ (FLASK ROUTING)
# ==========================================

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        
        # Поиск пользователя в MongoDB Atlas
        user_doc = users_collection.find_one({"username": username})
        
        if user_doc and user_doc["password"] == password:
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            error = "Неверный логин или пароль!"
            
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        rfid = request.form.get('rfid', '').strip().upper()
        
        # Проверка, существует ли пользователь в MongoDB
        existing_user = users_collection.find_one({"username": username})
        
        if existing_user:
            error = "Этот логин уже занят!"
        else:
            # Если RFID не введен, генерируем случайный
            if not rfid or rfid == "00 00 00 00":
                bytes_list = []
                for _ in range(4):
                    random_byte = random.randint(0, 255)
                    hex_byte = f"{random_byte:02X}"
                    bytes_list.append(hex_byte)
                rfid = " ".join(bytes_list)

            # Сохраняем нового юзера в MongoDB
            users_collection.insert_one({
                "username": username,
                "password": password,
                "rfid": rfid
            })
            
            success_msg = f"Регистрация успешна! Ваша RFID карта: {rfid}"
            return render_template_string(LOGIN_HTML, success_msg=success_msg)
            
    return render_template_string(REGISTER_HTML, error=error)

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    username = session['username']
    
    # Получаем данные текущего пользователя из MongoDB
    current_user_doc = users_collection.find_one({"username": username})
    user_rfid = current_user_doc.get("rfid", "Не назначен") if current_user_doc else "Не назначен"
    
    # Получаем список ВСЕХ пользователей из MongoDB для формы отправки
    all_users = [doc["username"] for doc in users_collection.find()]
    
    return render_template_string(
        DASHBOARD_HTML,
        username=username,
        user_rfid=user_rfid,
        all_users=all_users,
        delivery_active=delivery_status["active"],
        sender=delivery_status["sender"],
        recipient=delivery_status["recipient"],
        stage=delivery_status["stage"],
        eta=delivery_status["eta"]
    )

@app.route('/send_robot', methods=['POST'])
def send_robot():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    global delivery_status
    if not delivery_status["active"]:
        recipient = request.form.get('recipient')
        sender = session['username']
        
        if recipient:
            # 1. Задаем параметры новой доставки
            delivery_status["active"] = True
            delivery_status["sender"] = sender
            delivery_status["recipient"] = recipient
            delivery_status["stage"] = "moving"
            delivery_status["eta"] = 10  # 10 секунд на симуляцию пути до получателя
            delivery_status["scanned_rfid"] = None
            
            # 2. Публикуем команду "GO" для ESP-платы
            try:
                mqtt_client.publish(TOPIC_CONTROL, "GO")
                print(f">>> MQTT Команда 'GO' отправлена в топик {TOPIC_CONTROL}")
            except Exception as e:
                print(f"Ошибка отправки MQTT: {e}")
            
            # 3. Запускаем таймер поездки в фоне
            travel_thread = threading.Thread(target=simulate_travel)
            travel_thread.start()
            
    return redirect(url_for('dashboard'))

@app.route('/reset_robot', methods=['POST'])
def reset_robot():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    global delivery_status
    # Сбрасываем статус робота в исходное состояние свободы
    delivery_status = {
        "active": False,
        "sender": None,
        "recipient": None,
        "stage": "idle",
        "eta": 0,
        "scanned_rfid": None
    }
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

# ==========================================
# 7. ЗАПУСК
# ==========================================
if __name__ == '__main__':
    # На Render порт задается переменной окружения PORT, по умолчанию используем 5000
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)