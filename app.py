import time
import random
import threading
import os
from flask import Flask, request, redirect, url_for, session, render_template_string
from pymongo import MongoClient
import paho.mqtt.client as mqtt

app = Flask(__name__)
app.secret_key = "super_secret_key_for_sessions"

# ==========================================
# 1. ПОДКЛЮЧЕНИЕ К ОБЛАЧНОЙ БД (MongoDB)
# ==========================================
MONGO_URI = os.environ.get(
    "MONGO_URI", 
    "mongodb+srv://Kayott:163361@promlogix-u.9jbgo7r.mongodb.net/?appName=PromLogix-U"
)

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
ROBOT_ID = "my_unique_robot_id_999"

TOPIC_RFID = f"{ROBOT_ID}/rfid"
TOPIC_CONTROL = f"{ROBOT_ID}/control"

delivery_status = {
    "active": False,
    "sender": None,
    "recipient": None,
    "stage": "idle",
    "eta": 0,
    "scanned_rfid": None
}

# ==========================================
# 3. НАСТРОЙКА MQTT-КЛИЕНТА НА СЕРВЕРЕ
# ==========================================
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print(f"Flask-сервер подключен к MQTT брокеру с кодом: {rc}")
    client.subscribe(TOPIC_RFID)
    print(f"Подписались на топик: {TOPIC_RFID}")

def on_message(client, userdata, msg):
    global delivery_status
    payload = msg.payload.decode('utf-8').strip().upper()
    print(f"MQTT Получено сообщение в топик {msg.topic}: {payload}")
    
    # Физическое прикладывание карты у робота (через ESP)
    if msg.topic == TOPIC_RFID and delivery_status["stage"] == "waiting_card":
        delivery_status["scanned_rfid"] = payload
        
        recipient_name = delivery_status["recipient"]
        recipient_user = users_collection.find_one({"username": recipient_name})
        
        if recipient_user:
            correct_rfid = recipient_user.get("rfid", "").strip().upper()
            if payload == correct_rfid:
                print(">>> Ключ доступа верен! Отправляем команду OPEN роботу...")
                delivery_status["stage"] = "opened"
                mqtt_client.publish(TOPIC_CONTROL, "OPEN")
            else:
                print(f">>> Ключ не совпал. Ожидалось: {correct_rfid}, получено: {payload}")
        else:
            print(f">>> Ошибка: получатель {recipient_name} не найден в БД!")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

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
    
    delivery_status["stage"] = "waiting_card"
    print("Робот прибыл в пункт destination. Ожидание подтверждения доступа...")

# ==========================================
# 5. HTML ШАБЛОНЫ ИНТЕРФЕЙСА
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
        h2 { margin-top: 0; color: #333; text-align: center; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; font-size: 16px; }
        button { width: 100%; padding: 12px; background: #007bff; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; font-weight: bold; }
        button:hover { background: #0056b3; }
        .error { color: red; text-align: center; margin-bottom: 15px; font-weight: bold; }
        .success { color: green; text-align: center; margin-bottom: 15px; font-weight: bold; }
        .link { text-align: center; margin-top: 15px; font-size: 14px; }
        .link a { color: #007bff; text-decoration: none; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Вход в систему</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        {% if success_msg %}<div class="success">{{ success_msg }}</div>{% endif %}
        <form method="POST" action="/login">
            <input type="text" name="username" placeholder="Логин" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit">Войти</button>
        </form>
        <div class="link">Нет аккаунта? <a href="/register">Зарегистрироваться</a></div>
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
        h2 { margin-top: 0; color: #333; text-align: center; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; font-size: 16px; }
        button { width: 100%; padding: 12px; background: #28a745; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; font-weight: bold; }
        button:hover { background: #218838; }
        .error { color: red; text-align: center; margin-bottom: 15px; font-weight: bold; }
        .link { text-align: center; margin-top: 15px; font-size: 14px; }
        .link a { color: #007bff; text-decoration: none; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Регистрация пользователя</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST" action="/register">
            <input type="text" name="username" placeholder="Придумайте логин" required>
            <input type="password" name="password" placeholder="Придумайте пароль" required>
            <input type="text" name="rfid" placeholder="ID RFID-карты (необязательно)">
            <button type="submit">Создать аккаунт</button>
        </form>
        <div class="link">Уже есть аккаунт? <a href="/login">Войти</a></div>
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
    {% if delivery_active and (stage == 'moving' or stage == 'waiting_card' or stage == 'opened') %}
    <meta http-equiv="refresh" content="2">
    {% endif %}
    <style>
        body { font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 15px; }
        .container { max-width: 800px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; background: white; padding: 15px 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; gap: 15px; flex-wrap: wrap; }
        .header h1 { margin: 0; font-size: 22px; color: #333; }
        .header-user-block { display: flex; align-items: center; gap: 15px; flex-wrap: wrap; }
        .logout-btn { background: #dc3545; color: white; padding: 8px 15px; text-decoration: none; border-radius: 4px; white-space: nowrap; font-size: 14px; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; }
        h3 { margin-top: 0; color: #007bff; border-bottom: 2px solid #eee; padding-bottom: 10px; font-size: 18px; }
        .info-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-size: 15px; gap: 10px; flex-wrap: wrap; }
        .info-label { font-weight: bold; color: #555; }
        .rfid-badge { font-family: monospace; font-size: 16px; background: #eee; padding: 4px 10px; border-radius: 4px; white-space: nowrap; }
        select, button { width: 100%; padding: 12px; margin-top: 10px; border-radius: 4px; box-sizing: border-box; }
        select { border: 1px solid #ccc; font-size: 16px; background-color: white; }
        .btn-send { background: #007bff; color: white; border: none; font-size: 16px; cursor: pointer; }
        .btn-send:hover { background: #0056b3; }
        .btn-claim { background: #28a745; color: white; border: none; font-size: 16px; cursor: pointer; margin-top: 15px; font-weight: bold; }
        .btn-claim:hover { background: #218838; }
        .btn-reset { background: #ffc107; color: #212529; border: none; font-size: 16px; cursor: pointer; margin-top: 15px; }
        .status-box { padding: 15px; border-radius: 6px; font-weight: bold; text-align: center; font-size: 16px; margin-top: 15px; }
        .status-idle { background: #e2e3e5; color: #383d41; }
        .status-moving { background: #cce5ff; color: #004085; }
        .status-waiting { background: #fff3cd; color: #856404; }
        .status-opened { background: #d4edda; color: #155724; }
        @media (max-width: 480px) {
            .header { flex-direction: column; align-items: flex-start; padding: 15px; }
            .header-user-block { width: 100%; justify-content: space-between; align-items: center; }
            .info-row { flex-direction: column; align-items: flex-start; gap: 5px; }
            .rfid-badge { width: 100%; box-sizing: border-box; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Личный кабинет</h1>
            <div class="header-user-block">
                <span>Привет, <strong>{{ username }}</strong>!</span>
                <a href="/logout" class="logout-btn">Выйти</a>
            </div>
        </div>

        <div class="card">
            <h3>Ваши данные</h3>
            <div class="info-row">
                <span class="info-label">Ваш уникальный ключ доступа:</span>
                <span class="rfid-badge">{{ user_rfid }}</span>
            </div>
        </div>

        <div class="card">
            <h3>Отправить деталь</h3>
            {% if not delivery_active %}
                <form method="POST" action="/send_robot">
                    <label for="recipient">Выберите получателя из списка:</label>
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
                        📍 Робот прибыл в пункт назначения! Ожидание подтверждения.
                    </div>
                    <form method="POST" action="/web_claim_order">
                        <button type="submit" class="btn-claim">Забрать заказ (Имитировать RFID/Кнопку)</button>
                    </form>
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
        
        existing_user = users_collection.find_one({"username": username})
        if existing_user:
            error = "Этот логин уже занят!"
        else:
            if not rfid or rfid == "00 00 00 00":
                bytes_list = [f"{random.randint(0, 255):02X}" for _ in range(4)]
                rfid = " ".join(bytes_list)

            users_collection.insert_one({
                "username": username,
                "password": password,
                "rfid": rfid
            })
            success_msg = f"Регистрация успешна! Ваш ключ доступа: {rfid}"
            return render_template_string(LOGIN_HTML, success_msg=success_msg)
    return render_template_string(REGISTER_HTML, error=error)

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    username = session['username']
    current_user_doc = users_collection.find_one({"username": username})
    user_rfid = current_user_doc.get("rfid", "Не назначен") if current_user_doc else "Не назначен"
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
            delivery_status["active"] = True
            delivery_status["sender"] = sender
            delivery_status["recipient"] = recipient
            delivery_status["stage"] = "moving"
            delivery_status["eta"] = 10  
            delivery_status["scanned_rfid"] = None
            
            recipient_user = users_collection.find_one({"username": recipient})
            recipient_rfid = recipient_user.get("rfid", "").strip().upper() if recipient_user else ""

            try:
                if recipient_rfid:
                    # Отправляем UID
                    mqtt_client.publish(TOPIC_CONTROL, f"UID:{recipient_rfid}")
                    print(f">>> Отправлен UID получателя: {recipient_rfid}")
                    # Задержка 0.5 секунды, чтобы ESP успел обработать сообщение
                    time.sleep(0.5)
                
                # Даем команду ехать
                mqtt_client.publish(TOPIC_CONTROL, "GO")
                print(">>> Отправлена команда GO")
            except Exception as e:
                print(f"Ошибка отправки MQTT: {e}")
            
            travel_thread = threading.Thread(target=simulate_travel)
            travel_thread.start()
            
    return redirect(url_for('dashboard'))

@app.route('/web_claim_order', methods=['POST'])
def web_claim_order():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    global delivery_status
    if delivery_status["active"] and delivery_status["stage"] == "waiting_card":
        recipient_name = delivery_status["recipient"]
        recipient_user = users_collection.find_one({"username": recipient_name})
        
        if recipient_user:
            correct_rfid = recipient_user.get("rfid", "").strip().upper()
            
            delivery_status["stage"] = "opened"
            delivery_status["scanned_rfid"] = correct_rfid
            
            try:
                mqtt_client.publish(TOPIC_CONTROL, "OPEN")
                print(f">>> WEB-Тест: Статус изменен на OPENED. Команда OPEN отправлена роботу.")
            except Exception as e:
                print(f"Ошибка веб-эмуляции MQTT: {e}")
                
    return redirect(url_for('dashboard'))

@app.route('/reset_robot', methods=['POST'])
def reset_robot():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    global delivery_status
    delivery_status = {
        "active": False,
        "sender": None,
        "recipient": None,
        "stage": "idle",
        "eta": 0,
        "scanned_rfid": None
    }
    
    # Отправляем сигнал сброса на ESP, чтобы очистить кэш RFID
    try:
        mqtt_client.publish(TOPIC_CONTROL, "RESET")
        print(">>> Отправлена команда RESET на робота")
    except Exception as e:
        print(f"Ошибка отправки MQTT RESET: {e}")
        
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)