from flask import Flask, render_template_string, request, redirect, url_for, session
import paho.mqtt.client as mqtt
import json
import os
import threading
import time
import random

app = Flask(__name__)
app.secret_key = 'super_secret_key'

# --- НАСТРОЙКИ MQTT ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
ROBOT_ID = "my_unique_robot_id_999"  # Измени на свой уникальный ID!

TOPIC_CONTROL = f"{ROBOT_ID}/control"
TOPIC_RFID = f"{ROBOT_ID}/rfid"

mqtt_client = mqtt.Client()

def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print("Успешно подключились к MQTT Брокеру!")
    except Exception as e:
        print(f"Ошибка подключения к MQTT: {e}")

connect_mqtt()

# --- РАБОТА С ПОЛЬЗОВАТЕЛЯМИ (JSON БД) ---
DB_FILE = "users.json"

def load_users():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(users):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ СОСТОЯНИЯ ---
robot_status = "Ожидает заказ"
current_delivery_recipient = None  # Кому едет робот

# --- ФУНКЦИЯ ДЛЯ СИМУЛЯЦИИ ДОСТАВКИ ---
def simulate_delivery_travel():
    global robot_status
    robot_status = "Робот в пути..."
    mqtt_client.publish(TOPIC_CONTROL, "GO")
    print("Робот поехал к получателю...")
    
    time.sleep(10) # Имитируем время поездки 10 секунд
    
    robot_status = "Робот прибыл. Ожидание карты..."
    print("Робот прибыл в точку назначения.")

# --- HTML ШАБЛОНЫ ---

COMMON_STYLE = """
<style>
    body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; background: #f0f2f5; }
    .card { background: white; padding: 30px; display: inline-block; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); width: 360px; text-align: left; }
    h2, h3 { text-align: center; color: #2c3e50; margin-bottom: 20px; }
    hr { border: 0; height: 1px; background: #ddd; margin: 25px 0; }
    input, select { display: block; margin: 15px 0; padding: 12px; width: 100%; box-sizing: border-box; border: 1px solid #ccc; border-radius: 5px; font-size: 14px; }
    button, .btn { display: block; width: 100%; padding: 12px; color: white; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; text-align: center; font-size: 16px; font-weight: bold; margin-top: 15px; }
    .btn-blue { background: #3498db; }
    .btn-green { background: #2ecc71; }
    .btn-gray { background: #95a5a6; }
    .status-box { background: #ffeaa7; padding: 12px; border-radius: 5px; font-weight: bold; margin: 20px 0; text-align: center; color: #2d3436; }
    .link-center { display: block; text-align: center; margin-top: 15px; color: #7f8c8d; text-decoration: none; }
</style>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Вход</title>
    <!-- STYLES -->
</head>
<body>
    <div class="card">
        <h2>Вход в RoboDelivery 🤖</h2>
        {% if error %} <p style="color: red; text-align: center;">{{ error }}</p> {% endif %}
        {% if success_msg %} <p style="color: green; text-align: center; font-weight: bold;">{{ success_msg }}</p> {% endif %}
        <!-- ЯВНО НАПРАВЛЯЕМ POST-ЗАПРОС НА ВХОД -->
        <form action="/login" method="POST">
            <input type="text" name="username" placeholder="Логин" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit" class="btn btn-blue">Войти</button>
        </form>
        <a href="/register" class="link-center">Создать новый аккаунт</a>
    </div>
</body>
</html>
"""

REGISTER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Регистрация</title>
    <!-- STYLES -->
</head>
<body>
    <div class="card">
        <h2>Регистрация профиля</h2>
        {% if error %} <p style="color: red; text-align: center;">{{ error }}</p> {% endif %}
        <!-- ЯВНО НАПРАВЛЯЕМ POST-ЗАПРОС НА РЕГИСТРАЦИЮ -->
        <form action="/register" method="POST">
            <input type="text" name="username" placeholder="Придумайте логин" required>
            <input type="password" name="password" placeholder="Придумайте пароль" required>
            
            <input type="text" name="rfid" placeholder="UID вашей RFID-карты (например, A3 B2 C5 D9)">
            <p style="font-size: 12px; color: #7f8c8d; margin-top: -10px;">
                * Можно оставить пустым. Система <b>автоматически сгенерирует</b> уникальный UID карты для вашего профиля!
            </p>
            
            <button type="submit" class="btn btn-green">Зарегистрироваться</button>
        </form>
        <a href="/login" class="link-center">Уже есть аккаунт? Войти</a>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Личный кабинет</title>
    <!-- STYLES -->
    <meta http-equiv="refresh" content="3">
</head>
<body>
    <div class="card">
        <h2>Кабинет: {{ username }}</h2>
        <p>Ваша карта RFID: <b style="color: #2980b9;">{{ rfid }}</b></p>
        
        <div class="status-box">Статус робота: {{ status }}</div>

        <!-- СЕКЦИЯ ПОЛУЧЕНИЯ -->
        {% if recipient_match %}
            <h3>📥 Вам едет деталь!</h3>
            {% if status == 'Робот в пути...' %}
                <p style="color: #3498db; text-align: center; font-weight: bold;">🚚 Робот везет деталь к вам. Ожидайте...</p>
            {% elif status == 'Робот прибыл. Ожидание карты...' %}
                <p style="color: #d35400;">ℹ️ Робот у двери! Приложите вашу карту <b>(ID: {{ rfid }})</b> или нажмите кнопку:</p>
                <form action="/open_robot" method="POST">
                    <button type="submit" class="btn btn-green">Открыть робота удаленно</button>
                </form>
            {% elif status == 'Робот открыт! Деталь забрали.' %}
                <p style="color: #2ecc71; text-align: center; font-weight: bold;">✅ Заказ успешно завершен! Спасибо.</p>
                <form action="/reset_robot" method="POST">
                    <button type="submit" class="btn btn-gray">Вернуть робота на базу</button>
                </form>
            {% endif %}
            <hr>
        {% endif %}

        <!-- СЕКЦИЯ ОТПРАВКИ -->
        <h3>📤 Отправить деталь</h3>
        {% if status == 'Ожидает заказ' or status == 'Робот открыт! Деталь забрали.' %}
            <form action="/send_robot" method="POST">
                <label for="recipient">Выберите получателя детали:</label>
                <select name="recipient" id="recipient">
                    {% for user, info in all_users.items() %}
                        {% if user != username %}
                            <option value="{{ user }}">{{ user }} (RFID: {{ info.rfid }})</option>
                        {% endif %}
                    {% endfor %}
                </select>
                <button type="submit" class="btn btn-blue">Отправить робота</button>
            </form>
        {% else %}
            {% if not recipient_match %}
                <p style="color: #e67e22; text-align: center;">Робот сейчас занят выполнением другого заказа.</p>
            {% endif %}
        {% endif %}

        <hr>
        <a href="/logout" class="link-center">Выйти из аккаунта</a>
    </div>
</body>
</html>
"""

# Внедряем стили
LOGIN_HTML = LOGIN_HTML.replace("<!-- STYLES -->", COMMON_STYLE)
REGISTER_HTML = REGISTER_HTML.replace("<!-- STYLES -->", COMMON_STYLE)
DASHBOARD_HTML = DASHBOARD_HTML.replace("<!-- STYLES -->", COMMON_STYLE)


# --- МАРШРУТЫ ФЛАСКА ---

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# Регистрация
@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        
        # Безопасное получение поля rfid (не вызовет ошибку, если поля нет)
        rfid = request.form.get('rfid', '').strip().upper()
        
        users = load_users()
        
        if username in users:
            error = "Этот логин уже занят!"
        else:
            # --- АВТОГЕНЕРАЦИЯ RFID ---
            if not rfid or rfid == "00 00 00 00":
                bytes_list = []
                for _ in range(4):
                    random_byte = random.randint(0, 255)
                    hex_byte = f"{random_byte:02X}"
                    bytes_list.append(hex_byte)
                rfid = " ".join(bytes_list)

            # Сохраняем нового юзера в БД
            users[username] = {
                "password": password,
                "rfid": rfid
            }
            save_users(users)
            
            success_msg = f"Регистрация успешна! Ваша RFID карта: {rfid}"
            return render_template_string(LOGIN_HTML, success_msg=success_msg)
            
    return render_template_string(REGISTER_HTML, error=error)

# Авторизация (Вход)
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        
        users = load_users()
        
        if username in users and users[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            error = "Неверный логин или пароль!"
            
    return render_template_string(LOGIN_HTML, error=error)

# Личный кабинет
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    username = session['username']
    users = load_users()
    user_info = users[username]
    
    recipient_match = (username == current_delivery_recipient)
    
    return render_template_string(
        DASHBOARD_HTML, 
        username=username, 
        rfid=user_info['rfid'],
        status=robot_status,
        all_users=users,
        recipient_match=recipient_match
    )

@app.route('/send_robot', methods=['POST'])
def send_robot():
    global current_delivery_recipient
    recipient = request.form.get('recipient')
    current_delivery_recipient = recipient
    
    threading.Thread(target=simulate_delivery_travel).start()
    
    return redirect(url_for('dashboard'))

@app.route('/open_robot', methods=['POST'])
def open_robot():
    global robot_status
    robot_status = "Робот открыт! Деталь забрали."
    
    mqtt_client.publish(TOPIC_CONTROL, "OPEN")
    print("Отправлена команда OPEN")
    return redirect(url_for('dashboard'))

@app.route('/reset_robot', methods=['POST'])
def reset_robot():
    global robot_status, current_delivery_recipient
    robot_status = "Ожидает заказ"
    current_delivery_recipient = None
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)