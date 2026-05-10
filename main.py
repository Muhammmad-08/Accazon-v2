import telebot
from telebot import types
import psycopg2
from datetime import datetime, timezone
import os
import requests

TOKEN = os.environ.get("BOT_TOKEN")
CRYPTO_TOKEN = os.environ.get("CRYPTO_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not TOKEN:
    raise ValueError("BOT_TOKEN не задан!")
if not CRYPTO_TOKEN:
    raise ValueError("CRYPTO_TOKEN не задан!")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не задан!")

bot = telebot.TeleBot(TOKEN)

CRYPTO_API = "https://pay.crypt.bot/api"
OWNER_ID = 5703356053
ADMIN_ID = 8492482404
ADMIN_USERNAME = "accazonadmin"
REVIEW_CHAT_ID = -1003887182798
LOG_CHAT_ID = -1003907035139

def is_owner(user_id):
    return user_id == OWNER_ID

def is_admin(user_id, username):
    return user_id == OWNER_ID or user_id == ADMIN_ID or (username == ADMIN_USERNAME if username else False)

def get_full_name(user):
    name = user.first_name or ""
    if user.last_name:
        name += f" {user.last_name}"
    return name.strip() or "Без имени"

def user_info(user):
    name = get_full_name(user)
    username = f"@{user.username}" if user.username else "без username"
    return f"<b>{name}</b> ({username}, ID: {user.id})"

def now():
    return datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

def log(text):
    try:
        bot.send_message(LOG_CHAT_ID, text, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка логирования: {e}")

# ================= БАЗА ДАННЫХ =================
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0.0,
        total_spent REAL DEFAULT 0.0,
        purchases INTEGER DEFAULT 0,
        pending INTEGER DEFAULT 0,
        reg_date TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS invoices (
        invoice_id BIGINT PRIMARY KEY,
        user_id BIGINT,
        amount REAL,
        status TEXT DEFAULT 'pending'
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        country TEXT,
        price REAL,
        description TEXT,
        quantity INTEGER
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        order_num INTEGER,
        user_id BIGINT,
        product_id INTEGER,
        country TEXT,
        price REAL,
        username TEXT,
        full_name TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS order_counter (
        id INTEGER PRIMARY KEY,
        value INTEGER DEFAULT 0
    )''')
    cur.execute("INSERT INTO order_counter (id, value) VALUES (1, 0) ON CONFLICT DO NOTHING")
    conn.commit()
    cur.close()
    conn.close()

def get_next_order_number():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE order_counter SET value = value + 1 WHERE id = 1")
    conn.commit()
    cur.execute("SELECT value FROM order_counter WHERE id = 1")
    num = cur.fetchone()[0]
    cur.close()
    conn.close()
    return num

def reset_order_counter():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE order_counter SET value = 0 WHERE id = 1")
    conn.commit()
    cur.close()
    conn.close()

def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def add_new_user(user_id, username):
    conn = get_conn()
    cur = conn.cursor()
    reg_date = datetime.now().strftime("%d.%m.%Y")
    cur.execute("INSERT INTO users (user_id, username, reg_date) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (user_id, username, reg_date))
    conn.commit()
    cur.close()
    conn.close()

def update_balance(user_id, amount):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    cur.close()
    conn.close()

def save_invoice(invoice_id, user_id, amount):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO invoices (invoice_id, user_id, amount) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (invoice_id, user_id, amount))
    conn.commit()
    cur.close()
    conn.close()

def get_invoice(invoice_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE invoice_id = %s", (invoice_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def mark_invoice_paid(invoice_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = %s", (invoice_id,))
    conn.commit()
    cur.close()
    conn.close()

def get_products():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE quantity > 0")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_product(product_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def add_product(country, price, description, quantity):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (country, price, description, quantity) VALUES (%s, %s, %s, %s)",
                (country, price, description, quantity))
    conn.commit()
    cur.close()
    conn.close()

def create_order(order_num, user_id, product_id, country, price, username, full_name):
    conn = get_conn()
    cur = conn.cursor()
    created_at = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    cur.execute('''INSERT INTO orders (order_num, user_id, product_id, country, price, username, full_name, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                (order_num, user_id, product_id, country, price, username, full_name, created_at))
    order_id = cur.fetchone()[0]
    cur.execute("UPDATE products SET quantity = quantity - 1 WHERE id = %s", (product_id,))
    cur.execute('''UPDATE users SET balance = balance - %s, total_spent = total_spent + %s,
                   pending = pending + 1 WHERE user_id = %s''', (price, price, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return order_id

def complete_order(order_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM orders WHERE id = %s", (order_id,))
    row = cur.fetchone()
    if row:
        user_id = row[0]
        cur.execute("UPDATE orders SET status = 'completed' WHERE id = %s", (order_id,))
        cur.execute("UPDATE users SET purchases = purchases + 1, pending = GREATEST(0, pending - 1) WHERE user_id = %s", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        return user_id
    cur.close()
    conn.close()
    return None

def get_order(order_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

init_db()

# ================= CRYPTOBOT =================
def create_invoice(amount):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {"asset": "USDT", "amount": str(amount),
            "description": "Пополнение баланса Accazon", "expires_in": 3600}
    r = requests.post(f"{CRYPTO_API}/createInvoice", json=data, headers=headers)
    result = r.json()
    return result["result"] if result.get("ok") else None

def check_invoice_crypto(invoice_id):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    r = requests.get(f"{CRYPTO_API}/getInvoices", headers=headers,
                     params={"invoice_ids": str(invoice_id)})
    result = r.json()
    if result.get("ok") and result["result"]["items"]:
        return result["result"]["items"][0]
    return None

# ================= МЕНЮ =================
def set_bot_commands():
    bot.set_my_commands([
        types.BotCommand("start", "Запустить бота"),
        types.BotCommand("buy", "Купить товары"),
        types.BotCommand("profile", "Мой профиль"),
        types.BotCommand("help", "Техподдержка"),
    ])

def main_markup():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("👤 Профиль", "🛒 Купить")
    m.row("🛠 Техподдержка")
    return m

# ================= СТАРТ =================
@bot.message_handler(commands=['start'])
def start(message):
    user = get_user(message.from_user.id)
    is_new = user is None
    add_new_user(message.from_user.id, message.from_user.username)
    bot.send_message(message.chat.id,
        "👋 Приветствую тебя в магазине аккаунтов <b>Accazon</b>.\n\nПо вопросам писать — @m_muhammad_o8",
        parse_mode='HTML', reply_markup=main_markup())
    if is_new:
        log(f"👤 <b>Новый пользователь</b>\n{user_info(message.from_user)}\n🕐 {now()}")
    else:
        log(f"▶️ <b>Пользователь запустил бота</b>\n{user_info(message.from_user)}\n🕐 {now()}")

# ================= ПРОФИЛЬ =================
@bot.message_handler(commands=['profile'])
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(message):
    user = get_user(message.from_user.id)
    if not user:
        add_new_user(message.from_user.id, message.from_user.username)
        user = get_user(message.from_user.id)
    pending_text = f"\n⏳ В ожидании: <b>{user[5]} шт.</b>" if user[5] > 0 else ""
    text = (f"👤 <b>Ваш профиль</b>\n\n"
            f"💰 Баланс: <b>{user[2]:.2f} USD</b>\n"
            f"🛒 Куплено: <b>{user[4]} шт.</b>{pending_text}\n"
            f"💸 Потрачено: <b>{user[3]:.2f} USD</b>\n"
            f"📅 Регистрация: <b>{user[6]}</b>")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💰 Пополнить баланс", callback_data="topup"))
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)
    log(f"👤 <b>Открыл профиль</b>\n{user_info(message.from_user)}\n🕐 {now()}")

# ================= КУПИТЬ =================
@bot.message_handler(commands=['buy'])
@bot.message_handler(func=lambda m: m.text == "🛒 Купить")
def buy(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📱 Аккаунты Telegram", callback_data="cat_tg"))
    bot.send_message(message.chat.id, "🛒 Выберите категорию товаров:", reply_markup=markup)
    log(f"🛒 <b>Открыл магазин</b>\n{user_info(message.from_user)}\n🕐 {now()}")

@bot.callback_query_handler(func=lambda c: c.data == "cat_tg")
def show_tg(call):
    products = get_products()
    if not products:
        return bot.answer_callback_query(call.id, "😔 Товары пока отсутствуют", show_alert=True)
    markup = types.InlineKeyboardMarkup()
    for p in products:
        markup.add(types.InlineKeyboardButton(f"🌍 {p[1]} — {p[2]:.2f}$", callback_data=f"product_{p[0]}"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_buy"))
    bot.edit_message_text("📱 <b>Аккаунты Telegram</b>\n\nВыберите страну:",
                          call.message.chat.id, call.message.message_id,
                          parse_mode='HTML', reply_markup=markup)
    log(f"📱 <b>Открыл список товаров</b>\n{user_info(call.from_user)}\n🕐 {now()}")

@bot.callback_query_handler(func=lambda c: c.data == "back_buy")
def back_buy(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📱 Аккаунты Telegram", callback_data="cat_tg"))
    bot.edit_message_text("🛒 Выберите категорию товаров:",
                          call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("product_"))
def show_product(call):
    p = get_product(int(call.data.split("_")[1]))
    if not p:
        return bot.answer_callback_query(call.id, "❌ Товар не найден")
    text = (f"📦 <b>Информация о товаре</b>\n\n"
            f"🌍 Страна: <b>{p[1]}</b>\n"
            f"💰 Цена: <b>{p[2]:.2f}$</b>\n"
            f"📝 Описание: {p[3]}\n"
            f"📦 В наличии: <b>{p[4]} шт.</b>\n\n"
            f"<i>P.S. После покупки на товар есть гарантия 24 часа</i>")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🛒 Заказать", callback_data=f"order_{p[0]}"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="cat_tg"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                          parse_mode='HTML', reply_markup=markup)
    log(f"🔍 <b>Просмотрел товар</b>\n{user_info(call.from_user)}\n🌍 Страна: {p[1]} — {p[2]:.2f}$\n🕐 {now()}")

# ================= ЗАКАЗ =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("order_"))
def make_order(call):
    product_id = int(call.data.split("_")[1])
    p = get_product(product_id)
    if not p:
        return bot.answer_callback_query(call.id, "❌ Товар не найден")
    user = get_user(call.from_user.id)
    if not user or user[2] < p[2]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Пополнить баланс", callback_data="topup"))
        balance = user[2] if user else 0
        bot.send_message(call.message.chat.id,
            f"❌ <b>Недостаточно средств!</b>\n\n"
            f"💰 Ваш баланс: <b>{balance:.2f}$</b>\n"
            f"💸 Цена товара: <b>{p[2]:.2f}$</b>",
            parse_mode='HTML', reply_markup=markup)
        log(f"❌ <b>Недостаточно средств</b>\n{user_info(call.from_user)}\n"
            f"💰 Баланс: {balance:.2f}$ | Цена: {p[2]:.2f}$\n🕐 {now()}")
        return bot.answer_callback_query(call.id)

    full_name = get_full_name(call.from_user)
    username = call.from_user.username or "—"
    order_num = get_next_order_number()
    order_id = create_order(order_num, call.from_user.id, product_id, p[1], p[2], username, full_name)

    bot.send_message(call.message.chat.id,
        f"✅ <b>Заказ #{order_num} оформлен!</b>\n\n"
        f"⏳ Ожидайте выполнения.\n"
        f"👤 Ваш заказ выполнит: @m_muhammad_o8",
        parse_mode='HTML', reply_markup=main_markup())

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Выполнил заказ", callback_data=f"done_{order_id}"))
    bot.send_message(OWNER_ID,
        f"🔔 <b>Новый заказ #{order_num}</b>\n\n"
        f"🌍 Страна: <b>{p[1]}</b>\n"
        f"💰 Цена: <b>{p[2]:.2f}$</b>\n"
        f"👤 Покупатель: @{username}\n"
        f"🕐 Время: {now()}",
        parse_mode='HTML', reply_markup=markup)

    log(f"📦 <b>Новый заказ #{order_num}</b>\n{user_info(call.from_user)}\n"
        f"🌍 Страна: {p[1]} | 💰 Цена: {p[2]:.2f}$\n🕐 {now()}")
    bot.answer_callback_query(call.id)

# ================= ВЫПОЛНЕНИЕ =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("done_"))
def done_order(call):
    if not is_admin(call.from_user.id, call.from_user.username):
        return bot.answer_callback_query(call.id, "❌ Нет доступа")
    order_id = int(call.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        return bot.answer_callback_query(call.id, "❌ Заказ не найден")
    if order[8] == 'completed':
        return bot.answer_callback_query(call.id, "✅ Уже выполнен")
    user_id = complete_order(order_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✍️ Написать отзыв", callback_data=f"review_{order_id}"))
    bot.send_message(user_id,
        f"✅ <b>Ваш заказ #{order[1]} выполнен!</b>\n\n"
        f"Спасибо, что выбрали <b>Accazon</b>!\n"
        f"Будем рады вашему отзыву 🙏",
        parse_mode='HTML', reply_markup=markup)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.answer_callback_query(call.id, "✅ Заказ выполнен!")
    log(f"✅ <b>Заказ #{order[1]} выполнен</b>\n"
        f"👤 Покупатель: @{order[6]}\n"
        f"🌍 Страна: {order[4]} | 💰 Цена: {order[5]:.2f}$\n🕐 {now()}")

# ================= ОТЗЫВ =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("review_"))
def ask_stars(call):
    order_id = call.data.split("_")[1]
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("⭐1", callback_data=f"stars_{order_id}_1"),
        types.InlineKeyboardButton("⭐2", callback_data=f"stars_{order_id}_2"),
        types.InlineKeyboardButton("⭐3", callback_data=f"stars_{order_id}_3"),
        types.InlineKeyboardButton("⭐4", callback_data=f"stars_{order_id}_4"),
        types.InlineKeyboardButton("⭐5", callback_data=f"stars_{order_id}_5"),
    )
    bot.send_message(call.message.chat.id, "⭐ Оцените ваш заказ:", reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("stars_"))
def ask_review_text(call):
    parts = call.data.split("_")
    order_id, stars = parts[1], parts[2]
    stars_text = "⭐" * int(stars)
    bot.send_message(call.message.chat.id,
        f"Вы поставили: <b>{stars_text}</b>\n\nНапишите текст отзыва:", parse_mode='HTML')
    bot.register_next_step_handler_by_chat_id(call.message.chat.id,
        lambda m: ask_review_photo(m, order_id, stars, stars_text))
    bot.answer_callback_query(call.id)

def ask_review_photo(message, order_id, stars, stars_text):
    review_text = message.text
    bot.send_message(message.chat.id, "📸 Отправьте скриншот/фото где виден выполненный заказ:")
    bot.register_next_step_handler_by_chat_id(message.chat.id,
        lambda m: send_review(m, order_id, stars, stars_text, review_text))

def send_review(message, order_id, stars, stars_text, review_text):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ Пожалуйста, отправьте именно фото!")
        bot.register_next_step_handler_by_chat_id(message.chat.id,
            lambda m: send_review(m, order_id, stars, stars_text, review_text))
        return

    full_name = get_full_name(message.from_user)
    username = message.from_user.username or "—"
    photo_id = message.photo[-1].file_id

    caption_owner = (f"📝 <b>Отзыв на заказ #{order_id}</b>\n\n"
                     f"👤 Покупатель: @{username}\n"
                     f"⭐ Оценка: {stars_text} ({stars}/5)\n"
                     f"💬 Отзыв: {review_text}")

    caption_chat = (f"📝 <b>Отзыв на заказ #{order_id}</b>\n\n"
                    f"👤 Покупатель: <b>{full_name}</b>\n"
                    f"⭐ Оценка: {stars_text} ({stars}/5)\n"
                    f"💬 Отзыв: {review_text}")

    bot.send_message(message.chat.id, "✅ <b>Спасибо за отзыв!</b>",
                     parse_mode='HTML', reply_markup=main_markup())
    bot.send_photo(OWNER_ID, photo_id, caption=caption_owner, parse_mode='HTML')
    try:
        bot.send_photo(REVIEW_CHAT_ID, photo_id, caption=caption_chat, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка отправки в чат отзывов: {e}")

    log(f"📝 <b>Новый отзыв на заказ #{order_id}</b>\n{user_info(message.from_user)}\n"
        f"⭐ Оценка: {stars}/5\n💬 {review_text}\n🕐 {now()}")

# ================= ADD_NUMBER =================
@bot.message_handler(commands=['add_number'])
def add_number(message):
    if not is_admin(message.from_user.id, message.from_user.username):
        return
    bot.send_message(message.chat.id, "🌍 Введите страну товара (например: США):")
    bot.register_next_step_handler(message, get_country)
    log(f"➕ <b>Добавление товара начато</b>\n{user_info(message.from_user)}\n🕐 {now()}")

def get_country(message):
    country = message.text.strip()
    bot.send_message(message.chat.id, f"✅ Страна: {country}\n\n💰 Введите цену в USD:")
    bot.register_next_step_handler(message, get_price, country)

def get_price(message, country):
    try:
        price = float(message.text.replace(',', '.').strip())
        bot.send_message(message.chat.id, f"✅ Цена: {price}$\n\n📝 Введите описание товара:")
        bot.register_next_step_handler(message, get_description, country, price)
    except Exception:
        bot.send_message(message.chat.id, "❌ Введите цену цифрами. Попробуйте /add_number снова.")

def get_description(message, country, price):
    description = message.text.strip()
    bot.send_message(message.chat.id, f"✅ Описание: {description}\n\n📦 Введите количество товара:")
    bot.register_next_step_handler(message, get_quantity, country, price, description)

def get_quantity(message, country, price, description):
    try:
        quantity = int(message.text.strip())
        add_product(country, price, description, quantity)
        bot.send_message(message.chat.id,
            f"✅ <b>Товар добавлен!</b>\n\n"
            f"🌍 Страна: {country}\n💰 Цена: {price}$\n"
            f"📝 Описание: {description}\n📦 Количество: {quantity} шт.",
            parse_mode='HTML')
        log(f"✅ <b>Товар добавлен</b>\n{user_info(message.from_user)}\n"
            f"🌍 {country} | 💰 {price}$ | 📦 {quantity} шт.\n🕐 {now()}")
    except Exception:
        bot.send_message(message.chat.id, "❌ Введите количество цифрами. Попробуйте /add_number снова.")

# ================= ADD_BALANCE =================
@bot.message_handler(commands=['add_balance'])
def add_balance_cmd(message):
    if not is_owner(message.from_user.id):
        return
    try:
        parts = message.text.split()
        amount = float(parts[1])
        target_id = int(parts[2]) if len(parts) == 3 else OWNER_ID
        update_balance(target_id, amount)
        bot.send_message(message.chat.id,
            f"✅ Пользователю <b>{target_id}</b> зачислено <b>{amount:.2f} USD</b>",
            parse_mode='HTML')
        log(f"💸 <b>Ручное пополнение баланса</b>\nВладелец → ID: {target_id}\n"
            f"💰 Сумма: {amount:.2f} USD\n🕐 {now()}")
    except Exception:
        bot.send_message(message.chat.id,
            "❌ Использование:\n/add_balance 10 — себе\n/add_balance 10 123456789 — другому")

# ================= NULL_ZAKAZ =================
@bot.message_handler(commands=['null_zakaz'])
def null_zakaz(message):
    if not is_owner(message.from_user.id):
        return
    reset_order_counter()
    bot.send_message(message.chat.id, "✅ Счётчик заказов обнулён. Следующий заказ будет #1.")
    log(f"🔄 <b>Счётчик заказов обнулён</b>\n{user_info(message.from_user)}\n🕐 {now()}")

# ================= ПОДДЕРЖКА =================
@bot.message_handler(commands=['help'])
@bot.message_handler(func=lambda m: m.text == "🛠 Техподдержка")
def support(message):
    bot.send_message(message.chat.id, "🛠 При проблемах пишите @m_muhammad_o8",
                     reply_markup=main_markup())
    log(f"🛠 <b>Обратился в поддержку</b>\n{user_info(message.from_user)}\n🕐 {now()}")

# ================= ПОПОЛНЕНИЕ =================
@bot.callback_query_handler(func=lambda c: c.data == "topup")
def topup(call):
    bot.send_message(call.message.chat.id, "💵 Введите сумму пополнения в USD (минимум 0.5):")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, get_amount)
    log(f"💰 <b>Начал пополнение баланса</b>\n{user_info(call.from_user)}\n🕐 {now()}")

def get_amount(message):
    try:
        amount = float(message.text.replace(',', '.').strip())
        if amount < 0.5:
            return bot.send_message(message.chat.id, "❌ Минимум 0.5 USD")
        invoice = create_invoice(amount)
        if not invoice:
            return bot.send_message(message.chat.id, "❌ Ошибка создания счёта. Попробуйте позже.")
        save_invoice(invoice["invoice_id"], message.from_user.id, amount)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Оплатить", url=invoice["pay_url"]))
        markup.add(types.InlineKeyboardButton("✅ Я оплатил", callback_data=f"check_{invoice['invoice_id']}"))
        bot.send_message(message.chat.id,
            f"🧾 <b>Счёт на оплату</b>\n\n"
            f"💰 Сумма: <b>{amount:.2f} USDT</b>\n"
            f"⏳ Счёт действителен 1 час\n\n"
            f"Нажми <b>«Оплатить»</b>, затем вернись и нажми <b>«Я оплатил»</b>",
            parse_mode='HTML', reply_markup=markup)
        log(f"🧾 <b>Создан счёт на оплату</b>\n{user_info(message.from_user)}\n"
            f"💰 Сумма: {amount:.2f} USDT\n🕐 {now()}")
    except Exception:
        bot.send_message(message.chat.id, "❌ Введите сумму цифрами (например: 10)")

@bot.callback_query_handler(func=lambda c: c.data.startswith("check_"))
def check_payment(call):
    invoice_id = int(call.data.split("_")[1])
    inv_db = get_invoice(invoice_id)
    if not inv_db:
        return bot.answer_callback_query(call.id, "❌ Счёт не найден")
    if inv_db[3] == 'paid':
        return bot.answer_callback_query(call.id, "✅ Уже зачислено!")
    invoice = check_invoice_crypto(invoice_id)
    if not invoice:
        return bot.answer_callback_query(call.id, "❌ Ошибка проверки. Попробуйте позже.")
    if invoice["status"] == "paid":
        amount = inv_db[2]
        update_balance(call.from_user.id, amount)
        mark_invoice_paid(invoice_id)
        bot.answer_callback_query(call.id, "✅ Оплата получена!")
        bot.send_message(call.message.chat.id,
            f"✅ <b>Баланс пополнен!</b>\n\n💰 Зачислено: <b>{amount:.2f} USD</b>",
            parse_mode='HTML', reply_markup=main_markup())
        log(f"✅ <b>Баланс пополнен</b>\n{user_info(call.from_user)}\n"
            f"💰 Сумма: {amount:.2f} USD\n🕐 {now()}")
    else:
        bot.answer_callback_query(call.id, "⏳ Оплата ещё не поступила. Попробуйте через минуту.")

# ================= ЗАПУСК =================
if __name__ == "__main__":
    set_bot_commands()
    print("✅ Бот успешно запущен!")
    bot.infinity_polling()
