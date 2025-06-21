import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Updater, CommandHandler, CallbackQueryHandler,
                          MessageHandler, Filters, CallbackContext, ConversationHandler)
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
from data import token, adminId, bd_password
from dotenv import load_dotenv
import os

load_dotenv()  # Загружает переменные из .env
# Настройки базы данных
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': bd_password,
    'database': 'freelance_bot'
}

ADMIN_ID = adminId

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger('mysql.connector').setLevel(logging.WARNING)

# Состояния для ConversationHandler
ENTER_AMOUNT, SELECT_METHOD, ENTER_DETAILS = range(3)
DEPOSIT_FIO, DEPOSIT_PHONE, DEPOSIT_BANK, DEPOSIT_AMOUNT = range(4, 8)


# ========== ФУНКЦИИ РАБОТЫ С БАЗОЙ ДАННЫХ ==========

def create_connection():
    """Создает соединение с базой данных"""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return None


def init_db():
    """Инициализирует таблицы в базе данных"""
    connection = create_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor()

        # Таблица пользователей
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            balance DECIMAL(10, 2) DEFAULT 0,
            client_balance DECIMAL(10, 2) DEFAULT 0,
            status ENUM('verified', 'suspicious', 'banned') DEFAULT 'verified'
        )
        """)

        # Таблица заказов
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            title VARCHAR(100),
            price DECIMAL(10, 2),
            quantity INT,
            description TEXT,
            deadline INT COMMENT 'Время на выполнение в часах',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status ENUM('active', 'completed', 'rejected') DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """)

        # Таблица принятых заказов
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS accepted_orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT,
            worker_id BIGINT,
            status ENUM('in_progress', 'waiting_review', 'under_review', 'completed', 'rejected', 'canceled') DEFAULT 'in_progress',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (worker_id) REFERENCES users(user_id),
            UNIQUE KEY unique_order_worker (order_id, worker_id)
        )
        """)

        # Таблица платежей
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            amount DECIMAL(10, 2),
            payment_method VARCHAR(50),
            details VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status ENUM('pending', 'completed', 'rejected') DEFAULT 'pending',
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """)

        # Таблица пополнений
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            deposit_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            amount DECIMAL(10, 2),
            fio VARCHAR(100),
            phone VARCHAR(20),
            bank VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status ENUM('pending', 'completed', 'rejected') DEFAULT 'pending',
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """)

        connection.commit()
    except Error as e:
        logger.error(f"Ошибка инициализации БД: {e}")
    finally:
        if connection.is_connected():
            connection.close()


def add_user(user_id):
    """Добавляет нового пользователя в БД"""
    connection = create_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor()
        cursor.execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (user_id,))
        connection.commit()
    except Error as e:
        logger.error(f"Ошибка добавления пользователя: {e}")
    finally:
        if connection.is_connected():
            connection.close()


def get_user_status(user_id):
    """Возвращает статус пользователя"""
    connection = create_connection()
    if not connection:
        return 'verified'

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT status FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 'verified'
    except Error as e:
        logger.error(f"Ошибка получения статуса: {e}")
        return 'verified'
    finally:
        if connection.is_connected():
            connection.close()


def update_user_status(user_id, status):
    """Обновляет статус пользователя"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET status = %s WHERE user_id = %s", (status, user_id))
        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка обновления статуса пользователя: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def get_user_balance(user_id):
    """Возвращает баланс пользователя"""
    connection = create_connection()
    if not connection:
        return 0

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        return float(result[0]) if result else 0
    except Error as e:
        logger.error(f"Ошибка получения баланса: {e}")
        return 0
    finally:
        if connection.is_connected():
            connection.close()


def get_client_balance(user_id):
    """Возвращает баланс заказчика"""
    connection = create_connection()
    if not connection:
        return 0

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT client_balance FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        return float(result[0]) if result else 0
    except Error as e:
        logger.error(f"Ошибка получения баланса заказчика: {e}")
        return 0
    finally:
        if connection.is_connected():
            connection.close()


def update_user_balance(user_id, amount):
    """Обновляет баланс пользователя"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка обновления баланса: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def update_client_balance(user_id, amount):
    """Обновляет баланс заказчика"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET client_balance = client_balance + %s WHERE user_id = %s", (amount, user_id))
        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка обновления баланса заказчика: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def get_active_orders(sort_by='newest'):
    connection = create_connection()
    if not connection:
        return []

    try:


        cursor = connection.cursor(dictionary=True)

        base_query = """
        SELECT 
            order_id, title, price, description, 
            quantity, deadline, created_at,
            (SELECT COUNT(*) FROM accepted_orders 
             WHERE order_id = o.order_id AND status != 'canceled') as accepted_count
        FROM orders o
        WHERE status = 'active'
        AND (SELECT COUNT(*) FROM accepted_orders 
             WHERE order_id = o.order_id AND status != 'canceled') < quantity
        """

        # Добавляем сортировку один раз перед выполнением запроса
        if sort_by == 'price_high':
            base_query += " ORDER BY price DESC"
        elif sort_by == 'price_low':
            base_query += " ORDER BY price ASC"

        elif sort_by == 'newest':
            base_query += " ORDER BY created_at DESC"

        elif sort_by == 'oldest':
            base_query += " ORDER BY created_at ASC"


        cursor.execute(base_query)
        orders = cursor.fetchall()

        # Логируем первые 3 результата для проверки

        return orders

    except Exception as e:
        logger.error(f"Ошибка в get_active_orders: {e}")
        return []
    finally:
        if connection.is_connected():
            connection.close()


def get_order_details(order_id):
    """Возвращает детали заказа"""
    connection = create_connection()
    if not connection:
        return None

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,))
        return cursor.fetchone()
    except Error as e:
        logger.error(f"Ошибка получения заказа: {e}")
        return None
    finally:
        if connection.is_connected():
            connection.close()


def accept_order(order_id, worker_id):
    """Принимает заказ исполнителем"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()

        # 1. Проверяем, не взял ли уже этот исполнитель данный заказ
        cursor.execute("""
        SELECT 1 
        FROM accepted_orders 
        WHERE order_id = %s AND worker_id = %s AND status NOT IN ('canceled', 'rejected')
        """, (order_id, worker_id))
        if cursor.fetchone():
            return False  # Исполнитель уже взял этот заказ

        # 2. Проверяем лимит принятых заказов у исполнителя (не более 5)
        cursor.execute("""
        SELECT COUNT(*) 
        FROM accepted_orders 
        WHERE worker_id = %s AND status IN ('in_progress', 'waiting_review', 'under_review')
        """, (worker_id,))
        if cursor.fetchone()[0] >= 5:
            return False

        # 3. Проверяем доступность заказа
        cursor.execute("""
        SELECT o.quantity, 
               (SELECT COUNT(*) 
                FROM accepted_orders 
                WHERE order_id = o.order_id AND status NOT IN ('canceled', 'rejected')) as accepted_count
        FROM orders o 
        WHERE o.order_id = %s AND o.status = 'active'
        FOR UPDATE
        """, (order_id,))
        result = cursor.fetchone()

        if not result or result[0] <= result[1]:
            return False

        # 4. Принимаем заказ
        cursor.execute("""
        INSERT INTO accepted_orders (order_id, worker_id, status) 
        VALUES (%s, %s, 'in_progress')
        """, (order_id, worker_id))

        connection.commit()
        return True

    except Error as e:
        logger.error(f"Ошибка принятия заказа: {e}")
        connection.rollback()
        return False
    finally:
        if connection.is_connected():
            connection.close()


def get_user_orders(user_id):
    """Возвращает активные заказы пользователя"""
    connection = create_connection()
    if not connection:
        return []

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
        SELECT ao.id, ao.order_id, o.title, o.price, ao.status, o.description, 
               o.deadline, ao.started_at
        FROM accepted_orders ao
        JOIN orders o ON ao.order_id = o.order_id
        WHERE ao.worker_id = %s
        AND ao.status IN ('in_progress', 'waiting_review', 'under_review')
        ORDER BY ao.started_at DESC
        LIMIT 5
        """, (user_id,))
        return cursor.fetchall()
    except Error as e:
        logger.error(f"Ошибка получения заказов пользователя: {e}")
        return []
    finally:
        if connection.is_connected():
            connection.close()


def get_client_orders(user_id):
    """Возвращает заказы клиента"""
    connection = create_connection()
    if not connection:
        return []

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
        SELECT o.order_id, o.title, o.price, o.description, o.quantity, o.deadline, o.status,
               (SELECT COUNT(*) FROM accepted_orders WHERE order_id = o.order_id AND status != 'canceled') as accepted_count,
               (SELECT COUNT(*) FROM accepted_orders WHERE order_id = o.order_id AND status = 'completed') as completed_count
        FROM orders o
        WHERE o.user_id = %s
        ORDER BY o.created_at DESC
        LIMIT 10
        """, (user_id,))
        return cursor.fetchall()
    except Error as e:
        logger.error(f"Ошибка получения заказов клиента: {e}")
        return []
    finally:
        if connection.is_connected():
            connection.close()


def create_order(user_id, title, price, quantity, description, deadline):
    """Создает новый заказ"""
    connection = create_connection()
    if not connection:
        return None

    try:
        # Проверяем лимит активных заказов (не более 10)
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = %s AND status = 'active'", (user_id,))
        active_orders_count = cursor.fetchone()[0]
        if active_orders_count >= 10:
            return None

        cursor.execute("""
        INSERT INTO orders (user_id, title, price, quantity, description, deadline)
        VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, title, price, quantity, description, deadline))
        order_id = cursor.lastrowid
        connection.commit()
        return order_id
    except Error as e:
        logger.error(f"Ошибка создания заказа: {e}")
        return None
    finally:
        if connection.is_connected():
            connection.close()


def update_order_status(order_id, status):
    """Обновляет статус заказа"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("""
        UPDATE orders 
        SET status = %s 
        WHERE order_id = %s
        """, (status, order_id))
        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка обновления статуса заказа: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def update_accepted_order_status(order_id, worker_id, status):
    """Обновляет статус принятого заказа"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("""
        UPDATE accepted_orders 
        SET status = %s 
        WHERE order_id = %s AND worker_id = %s
        """, (status, order_id, worker_id))
        connection.commit()
        return cursor.rowcount > 0
    except Error as e:
        logger.error(f"Ошибка обновления статуса: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def cancel_order(order_id, worker_id):
    """Отменяет заказ и возвращает его в биржу"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("""
        UPDATE accepted_orders 
        SET status = 'canceled' 
        WHERE order_id = %s AND worker_id = %s
        """, (order_id, worker_id))
        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка отмены заказа: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def submit_order_for_review(order_id, worker_id):
    """Отправляет заказ на проверку и запрещает повторную отправку"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()

        # Проверяем текущий статус заказа
        cursor.execute("""
        SELECT status FROM accepted_orders 
        WHERE order_id = %s AND worker_id = %s
        """, (order_id, worker_id))
        result = cursor.fetchone()

        if not result:
            return False

        current_status = result[0]

        # Запрещаем повторную отправку, если уже ожидает проверки или на проверке
        if current_status in ('waiting_review', 'under_review'):
            return False

        cursor.execute("""
        UPDATE accepted_orders 
        SET status = 'waiting_review'
        WHERE order_id = %s AND worker_id = %s
        AND status = 'in_progress'
        """, (order_id, worker_id))

        connection.commit()
        return cursor.rowcount > 0
    except Error as e:
        logger.error(f"Ошибка отправки на проверку: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def get_user_active_order(user_id, order_id):
    """Проверяет, есть ли у пользователя активный заказ"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("""
        SELECT 1 FROM accepted_orders 
        WHERE order_id = %s AND worker_id = %s 
        AND status IN ('in_progress', 'waiting_review', 'under_review')
        """, (order_id, user_id))
        return cursor.fetchone() is not None
    except Error as e:
        logger.error(f"Ошибка проверки заказа: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def delete_completed_order(order_id):
    """Удаляет полностью выполненный заказ из БД"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()

        # Удаляем сначала принятые заказы
        cursor.execute("DELETE FROM accepted_orders WHERE order_id = %s", (order_id,))

        # Затем удаляем сам заказ
        cursor.execute("DELETE FROM orders WHERE order_id = %s", (order_id,))

        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка удаления заказа: {e}")
        connection.rollback()
        return False
    finally:
        if connection.is_connected():
            connection.close()


def create_payment(user_id, amount, method, details):
    """Создает запись о выплате"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("""
        INSERT INTO payments (user_id, amount, payment_method, details)
        VALUES (%s, %s, %s, %s)
        """, (user_id, amount, method, details))
        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка создания платежа: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()


def create_deposit_request(user_id, amount, fio, phone, bank):
    """Создает запрос на пополнение баланса"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("""
        INSERT INTO deposits (user_id, amount, fio, phone, bank, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
        """, (user_id, amount, fio, phone, bank))
        connection.commit()
        return cursor.lastrowid
    except Error as e:
        logger.error(f"Ошибка создания запроса на пополнение: {e}")
        return None
    finally:
        if connection.is_connected():
            connection.close()


def complete_deposit(deposit_id):
    """Подтверждает пополнение баланса"""
    connection = create_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor(dictionary=True)
        # Получаем данные о пополнении
        cursor.execute("SELECT user_id, amount FROM deposits WHERE deposit_id = %s", (deposit_id,))
        deposit = cursor.fetchone()

        if not deposit:
            return False

        # Обновляем баланс
        cursor.execute("""
        UPDATE users 
        SET client_balance = client_balance + %s 
        WHERE user_id = %s
        """, (deposit['amount'], deposit['user_id']))

        # Обновляем статус пополнения
        cursor.execute("""
        UPDATE deposits 
        SET status = 'completed' 
        WHERE deposit_id = %s
        """, (deposit_id,))

        connection.commit()
        return True
    except Error as e:
        logger.error(f"Ошибка подтверждения пополнения: {e}")
        connection.rollback()
        return False
    finally:
        if connection.is_connected():
            connection.close()


# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ==========

def start(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    add_user(user_id)

    keyboard = [
        [InlineKeyboardButton("📋 Список заказов", callback_data='order_list')],
        [InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("❓ Справка", callback_data='help')],
        [InlineKeyboardButton("👔 Меню заказчика", callback_data='client_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Добро пожаловать в фриланс-бот! Выберите действие:', reply_markup=reply_markup)


def show_order_list(query, page=0, per_page=5, sort_by='newest'):
    """Показывает список заказов с пагинацией и сортировкой"""
    try:
        orders = get_active_orders(sort_by)

        if not orders:
            if query.message.text != "На данный момент нет доступных заказов.":
                query.edit_message_text(text="На данный момент нет доступных заказов.")
            return

        total_pages = (len(orders) + per_page - 1) // per_page
        current_orders = orders[page * per_page: (page + 1) * per_page]

        sort_text = {
            'price_high': ' (сначала дорогие)',
            'price_low': ' (сначала дешевые)',
            'newest': ' (сначала новые)',
            'oldest': ' (сначала старые)'
        }.get(sort_by, '')

        text = f"Доступные заказы{sort_text} (страница {page + 1} из {total_pages}):"

        keyboard = []
        for order in current_orders:
            available = order['quantity'] - order['accepted_count']
            keyboard.append([InlineKeyboardButton(
                f"{order['title']} - {order['price']} руб. (осталось: {available})",
                callback_data=f"order_{order['order_id']}"
            )])
        # Кнопки пагинации с сохранением сортировки
        pagination = []
        if page > 0:
            pagination.append(InlineKeyboardButton("⬅️ Назад",
                                                   callback_data=f"order_page_{page - 1}_{sort_by}"))
        if page < total_pages - 1:
            pagination.append(InlineKeyboardButton("Вперед ➡️",
                                                   callback_data=f"order_page_{page + 1}_{sort_by}"))

        if pagination:
            keyboard.append(pagination)

        # Кнопка сортировки
        keyboard.append([InlineKeyboardButton("🔀 Сортировать", callback_data='sort_orders')])
        keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')])

        query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в show_order_list: {e}")

def show_sort_options(query):
    """Показывает варианты сортировки заказов"""
    keyboard = [
        [InlineKeyboardButton("Сначала дорогие", callback_data='sort_price_high')],
        [InlineKeyboardButton("Сначала дешевые", callback_data='sort_price_low')],
        [InlineKeyboardButton("Сначала новые", callback_data='sort_newest')],
        [InlineKeyboardButton("Сначала старые", callback_data='sort_oldest')],
        [InlineKeyboardButton("🔙 Назад", callback_data='order_list')]
    ]
    query.edit_message_text(
        text="Выберите способ сортировки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_order_details(query):
    """Показывает детали заказа"""
    order_id = int(query.data.split('_')[1])
    order = get_order_details(order_id)

    if not order:
        query.edit_message_text(text="Заказ не найден.")
        return

    text = f"📌 {order['title']}\n💵 Цена: {order['price']} руб.\n⏱ Срок: {order['deadline']} ч.\n\n📝 Описание:\n{order['description']}"

    keyboard = [
        [InlineKeyboardButton("✅ Выбрать заказ", callback_data=f"accept_{order['order_id']}")],
        [InlineKeyboardButton("🔙 Назад к списку", callback_data='order_list')]
    ]
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def accept_order_handler(query):
    """Обрабатывает принятие заказа"""
    user_id = query.from_user.id
    order_id = int(query.data.split('_')[1])

    if get_user_status(user_id) == 'banned':
        query.edit_message_text(
            text="⛔ Вы забанены и не можете принимать заказы. Если вас забанили по ошибке, пожалуйста напишите в поддержку: @kirillrakitin")
        return

    if get_user_active_order(user_id, order_id):
        keyboard = [
            [InlineKeyboardButton("📌 Мои заказы", callback_data='my_orders')],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data='order_list')]
        ]
        query.edit_message_text(
            text="❌ Один и тот же заказ нельзя брать повторно.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if accept_order(order_id, user_id):
        keyboard = [
            [InlineKeyboardButton("📌 Мои заказы", callback_data='my_orders')],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data='order_list')]
        ]
        query.edit_message_text(
            text="🎉 Вы успешно приняли заказ! Выполните требования и отправьте материалы через раздел 'Мои заказы'.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Проверяем, не превышен ли лимит заказов
        connection = create_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM accepted_orders WHERE worker_id = %s AND status IN ('in_progress', 'waiting_review', 'under_review')",
                    (user_id,))
                active_orders_count = cursor.fetchone()[0]
                if active_orders_count >= 5:
                    query.edit_message_text(text="⚠ Вы не можете принять более 5 заказов одновременно.")
                    return
            except Error as e:
                logger.error(f"Ошибка проверки лимита заказов: {e}")
            finally:
                if connection.is_connected():
                    connection.close()

        query.edit_message_text(text="❌ Один и тот же заказ нельзя брать повторно.")


def show_profile(query):
    """Показывает профиль пользователя"""
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    status = get_user_status(user_id)

    status_text = {
        'verified': '✅ Проверенный',
        'suspicious': '⚠ Под подозрением',
        'banned': '⛔ Заблокирован'
    }.get(status, '❓ Неизвестно')

    text = f"👤 Ваш профиль\n\n💰 Баланс: {balance} руб.\n🔒 Статус: {status_text}"

    keyboard = [
        [InlineKeyboardButton("📌 Мои заказы", callback_data='my_orders')],
        [InlineKeyboardButton("💸 Вывести", callback_data='withdraw')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')]
    ]
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def start_withdrawal(update: Update, context: CallbackContext):
    """Начинает процесс вывода средств"""
    query = update.callback_query
    query.answer()

    user_id = query.from_user.id
    balance = get_user_balance(user_id)

    if balance < 100:
        query.edit_message_text(
            text="❌ Минимальная сумма для вывода - 100 руб.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data='profile')]
            ])
        )
        return ConversationHandler.END

    query.edit_message_text(text="Введите сумму для вывода (от 100 руб):")
    return ENTER_AMOUNT


def process_withdrawal_amount(update: Update, context: CallbackContext):
    """Обрабатывает ввод суммы для вывода"""
    try:
        amount = float(update.message.text)
        user_id = update.message.from_user.id
        balance = get_user_balance(user_id)

        if amount < 100:
            update.message.reply_text("❌ Минимальная сумма - 100 руб. Введите сумму еще раз:")
            return ENTER_AMOUNT

        if amount > balance:
            update.message.reply_text(f"❌ Недостаточно средств. Ваш баланс: {balance} руб. Введите меньшую сумму:")
            return ENTER_AMOUNT

        context.user_data['withdrawal'] = {'amount': amount}

        keyboard = [
            [InlineKeyboardButton("Сбербанк", callback_data='method_sber')],
            [InlineKeyboardButton("Тинькофф", callback_data='method_tinkoff')],
            [InlineKeyboardButton("Другой банк", callback_data='method_other')],
            [InlineKeyboardButton("Отмена", callback_data='cancel_withdraw')]
        ]

        update.message.reply_text(
            text=f"Выберите способ получения {amount} руб:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECT_METHOD
    except ValueError:
        update.message.reply_text("❌ Введите корректную сумму (число, например: 150.50):")
        return ENTER_AMOUNT


def process_payment_method(update: Update, context: CallbackContext):
    """Обрабатывает выбор способа оплаты"""
    query = update.callback_query
    query.answer()

    if query.data == 'cancel_withdraw':
        query.edit_message_text(text="❌ Вывод средств отменен.")
        return ConversationHandler.END

    method = query.data.split('_')[1]

    if method == 'other':
        query.edit_message_text(text="Введите название вашего банка:")
        context.user_data['withdrawal']['method'] = 'Другой банк'
        return ENTER_DETAILS

    method_names = {
        'sber': 'Сбербанк',
        'tinkoff': 'Тинькофф'
    }

    context.user_data['withdrawal']['method'] = method_names.get(method, method)
    query.edit_message_text(text="Введите реквизиты для перевода (номер карты/телефона):")
    return ENTER_DETAILS


def complete_withdrawal(update: Update, context: CallbackContext):
    """Завершает процесс вывода средств"""
    details = update.message.text
    withdrawal = context.user_data['withdrawal']
    user_id = update.message.from_user.id

    # Если был выбран "Другой банк", добавляем его название к деталям
    if withdrawal['method'] == 'Другой банк':
        bank_name = details
        withdrawal['method'] = f"Другой банк ({bank_name})"
        update.message.reply_text("Теперь введите реквизиты для перевода (номер карты/телефона):")
        return ENTER_DETAILS

    # Записываем платеж в БД
    if create_payment(user_id, withdrawal['amount'], withdrawal['method'], details):
        # Списываем средства с баланса
        update_user_balance(user_id, -withdrawal['amount'])

        # Отправляем уведомление админу
        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📌 Новый запрос на вывод:\n\n"
                     f"👤 Пользователь: @{update.message.from_user.username or update.message.from_user.full_name} (ID: {user_id})\n"
                     f"💵 Сумма: {withdrawal['amount']} руб.\n"
                     f"📱 Способ: {withdrawal['method']}\n"
                     f"🔢 Реквизиты: {details}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Уведомить пользователя",
                                          callback_data=f"notify_user_{user_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу: {e}")

        update.message.reply_text("✅ Запрос на вывод отправлен! Средства будут переведены в течение 24 часов.")
    else:
        update.message.reply_text("❌ Произошла ошибка при обработке запроса. Попробуйте позже.")

    return ConversationHandler.END


def cancel_withdrawal(update: Update, context: CallbackContext):
    """Отменяет процесс вывода средств"""
    query = update.callback_query
    query.answer()

    if 'withdrawal' in context.user_data:
        del context.user_data['withdrawal']

    query.edit_message_text(text="❌ Вывод средств отменен.")
    return ConversationHandler.END


def confirm_cancel_order(query):
    """Показывает подтверждение отмены заказа"""
    order_id = int(query.data.split('_')[1])

    query.edit_message_text(
        text="❓ Вы уверены, что хотите отменить заказ? Повторно взять его уже будет нельзя.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, отменить", callback_data=f"confirm_cancel_{order_id}")],
            [InlineKeyboardButton("❌ Нет, вернуться", callback_data=f"myorder_{order_id}")]
        ])
    )


def process_order_cancellation(query):
    """Обрабатывает подтверждение отмены заказа"""
    order_id = int(query.data.split('_')[2])
    user_id = query.from_user.id

    if cancel_order(order_id, user_id):
        query.edit_message_text(text="✅ Заказ успешно отменен.")
    else:
        query.edit_message_text(text="❌ Произошла ошибка при отмене заказа.")


def show_client_menu(query):
    """Показывает меню заказчика"""
    user_id = query.from_user.id
    client_balance = get_client_balance(user_id)

    text = f"👔 Меню заказчика\n\n💰 Баланс заказчика: {client_balance} руб."

    keyboard = [
        [InlineKeyboardButton("➕ Создать заказ", callback_data='create_order')],
        [InlineKeyboardButton("📋 Мои заказы", callback_data='client_orders')],
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data='deposit')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')]
    ]
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def show_client_orders(query):
    """Показывает заказы клиента"""
    user_id = query.from_user.id
    orders = get_client_orders(user_id)

    if not orders:
        text = "У вас нет созданных заказов."
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='client_menu')]]
    else:
        text = "📋 Выберите заказ для просмотра:"
        keyboard = []

        for order in orders:
            status_text = {
                'active': '🟢 Активен',
                'completed': '✅ Завершен',
                'rejected': '❌ Отклонен'
            }.get(order['status'], '❓ Неизвестно')

            keyboard.append([InlineKeyboardButton(
                f"{order['title']} ({status_text}) - {order['completed_count']}/{order['quantity']}",
                callback_data=f"clientorder_{order['order_id']}"
            )])

        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='client_menu')])

    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def show_client_order_details(query):
    """Показывает детали заказа клиента"""
    order_id = int(query.data.split('_')[1])
    order = get_order_details(order_id)

    if not order:
        query.edit_message_text(text="Заказ не найден.")
        return

    status_text = {
        'active': '🟢 Активен',
        'completed': '✅ Завершен',
        'rejected': '❌ Отклонен'
    }.get(order['status'], '❓ Неизвестно')

    text = (
        f"📌 Заказ: {order['title']}\n"
        f"💵 Цена за единицу: {order['price']} руб.\n"
        f"🔢 Количество исполнителей: {order['quantity']}\n"
        f"⏱ Срок выполнения: {order['deadline']} ч.\n"
        f"📝 Описание:\n{order['description']}\n\n"
        f"🔹 Статус: {status_text}"
    )

    keyboard = [[InlineKeyboardButton("🔙 Назад к списку", callback_data='client_orders')]]
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def show_user_orders(query):
    """Показывает заказы пользователя"""
    user_id = query.from_user.id
    orders = get_user_orders(user_id)

    if not orders:
        text = "У вас нет активных заказов."
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='profile')]]
    else:
        text = "📌 Ваши активные заказы:\n\n"
        keyboard = []

        for order in orders:
            status_text = {
                'in_progress': '🟡 В выполнении',
                'waiting_review': '🟠 Ожидает проверки',
                'under_review': '🟣 На проверке'
            }.get(order['status'], '❓ Неизвестно')

            # Рассчитываем оставшееся время только для заказов в работе
            if order['status'] == 'in_progress':
                deadline_time = order['started_at'] + timedelta(hours=order['deadline'])
                time_left = deadline_time - datetime.now()

                if time_left.total_seconds() <= 0:
                    time_text = "🕛 Просрочен"
                    # Автоматически отменяем просроченный заказ
                    cancel_order(order['order_id'], user_id)
                else:
                    hours = int(time_left.total_seconds() // 3600)
                    minutes = int((time_left.total_seconds() % 3600) // 60)
                    time_text = f"⏱ {hours}ч {minutes}м"
            else:
                time_text = "⏳ На проверке (время приостановлено)"

            text += f"{order['title']} - {order['price']} руб. ({status_text}, {time_text})\n"
            keyboard.append([InlineKeyboardButton(
                f"{order['title']} ({status_text})",
                callback_data=f"myorder_{order['order_id']}"
            )])

        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='profile')])

    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def show_user_order_details(update: Update, order_id, worker_id):
    """Показывает детали заказа пользователя"""
    order = get_order_details(order_id)
    if not order:
        update.callback_query.edit_message_text(text="Заказ не найден.")
        return

    # Получаем информацию о принятом заказе
    connection = create_connection()
    if not connection:
        return

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
        SELECT status, started_at 
        FROM accepted_orders 
        WHERE order_id = %s AND worker_id = %s
        """, (order_id, worker_id))
        accepted_order = cursor.fetchone()
    except Error as e:
        logger.error(f"Ошибка получения заказа: {e}")
        return
    finally:
        if connection.is_connected():
            connection.close()

    if not accepted_order:
        update.callback_query.edit_message_text(text="Заказ не найден.")
        return

    status_map = {
        'in_progress': '🟡 В выполнении',
        'waiting_review': '🟠 Ожидает проверки',
        'under_review': '🟣 На проверке'
    }

    # Рассчитываем оставшееся время только для заказов в работе
    if accepted_order['status'] == 'in_progress':
        deadline_time = accepted_order['started_at'] + timedelta(hours=order['deadline'])
        time_left = deadline_time - datetime.now()

        if time_left.total_seconds() <= 0:
            status_text = "🕛 Просрочен"
            # Автоматически отменяем просроченный заказ
            cancel_order(order_id, worker_id)
        else:
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            status_text = f"⏳ Осталось: {hours}ч {minutes}м"
    else:
        status_text = "⏳ На проверке (время приостановлено)"

    text = (
        f"📌 Заказ: {order['title']}\n"
        f"💵 Цена: {order['price']} руб.\n"
        f"⏱️ {status_text}\n"
        f"📝 Описание:\n{order['description']}\n\n"
        f"🔹 Статус: {status_map.get(accepted_order['status'], '❓ Неизвестно')}"
    )

    keyboard = []
    if accepted_order['status'] == 'in_progress':
        keyboard.append([InlineKeyboardButton("📤 Отправить на проверку", callback_data=f"submit_{order_id}")])
        keyboard.append([InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{order_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад к списку", callback_data='my_orders')])

    update.callback_query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def handle_order_submission(update: Update, context: CallbackContext):
    """Обрабатывает отправку заказа на проверку"""
    query = update.callback_query
    order_id = int(query.data.split('_')[1])
    user_id = query.from_user.id

    query.edit_message_text(text="Отправьте ссылку на выполненную работу (Google Drive, Яндекс.Диск и т.д.):")
    context.user_data['awaiting_materials'] = {
        'order_id': order_id,
        'user_id': user_id,
        'action': 'submit'
    }


def handle_order_cancellation(update: Update, context: CallbackContext):
    """Обрабатывает отмену заказа"""
    query = update.callback_query
    order_id = int(query.data.split('_')[1])
    user_id = query.from_user.id

    if cancel_order(order_id, user_id):
        query.edit_message_text(text="Заказ успешно отменен и возвращен в биржу.")
    else:
        query.edit_message_text(text="Произошла ошибка при отмене заказа.")


def handle_materials(update: Update, context: CallbackContext):
    """Обрабатывает полученные материалы с проверкой на повторную отправку"""
    if 'awaiting_materials' not in context.user_data or not update.message.text:
        return

    user_id = update.message.from_user.id
    order_id = context.user_data['awaiting_materials']['order_id']
    action = context.user_data['awaiting_materials']['action']
    link = update.message.text

    if action == 'submit':
        order = get_order_details(order_id)
        if not order:
            update.message.reply_text("Ошибка: заказ не найден.")
            return

        # Проверяем, можно ли отправить материалы
        connection = create_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("""
                SELECT status FROM accepted_orders 
                WHERE order_id = %s AND worker_id = %s
                """, (order_id, user_id))
                result = cursor.fetchone()

                if result and result[0] in ('waiting_review', 'under_review'):
                    update.message.reply_text("❌ Вы уже отправили материалы по этому заказу. Дождитесь проверки.")
                    return
            except Error as e:
                logger.error(f"Ошибка проверки статуса заказа: {e}")
            finally:
                if connection.is_connected():
                    connection.close()

        if submit_order_for_review(order_id, user_id):
            # Отправляем ссылку заказчику
            text = (
                f"📌 Заказ: {order['title']}\n"
                f"💵 Цена: {order['price']} руб.\n\n"
                f"📝 Описание заказа:\n{order['description']}\n\n"
                f"🔗 Ссылка на выполненную работу:\n{link}\n\n"
                f"Проверьте выполнение:"
            )

            try:
                context.bot.send_message(
                    chat_id=order['user_id'],
                    text=text,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ Принять", callback_data=f"client_approve_{order_id}_{user_id}"),
                            InlineKeyboardButton("❌ Отклонить", callback_data=f"client_reject_{order_id}_{user_id}")
                        ]
                    ])
                )
                update.message.reply_text("✅ Ссылка отправлена заказчику.")
            except Exception as e:
                logger.error(f"Ошибка при отправке ссылки: {e}")
                update.message.reply_text("Ошибка при отправке материалов. Попробуйте позже.")
        else:
            update.message.reply_text("❌ Не удалось отправить материалы. Возможно, вы уже отправили их ранее.")


def handle_client_decision(update: Update, context: CallbackContext):
    """Обрабатывает решение заказчика"""
    query = update.callback_query
    data = query.data.split('_')
    action = data[1]
    order_id = int(data[2])
    worker_id = int(data[3])

    # Получаем информацию о заказе
    order = get_order_details(order_id)
    if not order:
        query.message.reply_text("Ошибка: заказ не найден.")
        return




    if action == 'approve':
        if update_accepted_order_status(order_id, worker_id, 'completed'):
            if update_user_balance(worker_id, order['price']):
                context.bot.send_message(
                    chat_id=worker_id,
                    text=f"✅ Ваш заказ \"{order['title']}\" принят! На ваш баланс зачислено {order['price']} руб."
                )
                context.bot.send_message(
                    chat_id=order['user_id'],
                    text=f"Вы приняли заказ \"{order['title']}\"."
                )

                # Проверяем, все ли заказы выполнены
                connection = create_connection()
                if connection:
                    try:
                        cursor = connection.cursor()
                        cursor.execute("""
                        SELECT COUNT(*) as completed_count 
                        FROM accepted_orders 
                        WHERE order_id = %s AND status = 'completed'
                        """, (order_id,))
                        completed_count = cursor.fetchone()[0]

                        if completed_count >= order['quantity']:
                            update_order_status(order_id, 'completed')
                            # Удаляем полностью выполненный заказ
                            delete_completed_order(order_id)
                    except Error as e:
                        logger.error(f"Ошибка проверки завершения заказа: {e}")
                    finally:
                        if connection.is_connected():
                            connection.close()
    elif action == 'reject':
        if update_accepted_order_status(order_id, worker_id, 'under_review'):
            # Просто пересылаем сообщение админу без указания причины
            text = (
                f"⚠️ Конфликт по заказу:\n\n"
                f"📌 Заказ: {order['title']}\n"
                f"💵 Цена: {order['price']} руб.\n"
                f"📝 Описание заказа:\n{order['description']}\n\n"
                f"Примите решение:"
            )

            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=text,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Принять работу",
                                             callback_data=f"admin_final_approve_{order_id}_{worker_id}"),
                        InlineKeyboardButton("❌ Отклонить работу",
                                             callback_data=f"admin_final_reject_{order_id}_{worker_id}")
                    ]
                ])
            )

            context.bot.send_message(
                chat_id=order['user_id'],
                text="Работа отклонена и отправлена администратору на проверку."
            )


def handle_rejection_reason(update: Update, context: CallbackContext):
    """Обрабатывает причину отклонения работы"""
    if 'awaiting_rejection_reason' not in context.user_data:
        return

    reason = update.message.text
    order_id = context.user_data['awaiting_rejection_reason']['order_id']
    worker_id = context.user_data['awaiting_rejection_reason']['worker_id']
    client_id = context.user_data['awaiting_rejection_reason']['client_id']

    order = get_order_details(order_id)
    if not order:
        update.message.reply_text("Ошибка: заказ не найден.")
        return

    # Отправляем сообщение администратору
    text = (
        f"⚠️ Конфликт по заказу:\n\n"
        f"📌 Заказ: {order['title']}\n"
        f"💵 Цена: {order['price']} руб.\n"
        f"📝 Описание заказа:\n{order['description']}\n\n"
        f"🔹 Причина отклонения:\n{reason}\n\n"
        f"Примите решение:"
    )

    context.bot.send_message(
        chat_id=ADMIN_ID,
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Принять работу", callback_data=f"admin_final_approve_{order_id}_{worker_id}"),
                InlineKeyboardButton("❌ Отклонить работу", callback_data=f"admin_final_reject_{order_id}_{worker_id}")
            ]
        ])
    )

    update.message.reply_text("Работа отклонена. Материалы отправлены администратору на проверку.")
    del context.user_data['awaiting_rejection_reason']


def handle_admin_final_decision(update: Update, context: CallbackContext):
    """Обрабатывает окончательное решение администратора"""
    query = update.callback_query
    query.answer()
    data = query.data.split('_')
    action = data[2]
    order_id = int(data[3])
    worker_id = int(data[4])

    order = get_order_details(order_id)
    if not order:
        try:
            query.edit_message_text(text="Заказ не найден.")
        except Exception as e:
            logger.error(f"Ошибка редактирования сообщения: {e}")
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Заказ не найден."
            )
        return

    try:
        # Удаляем сообщение с кнопками
        query.delete_message()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

    if action == 'approve':
        if update_accepted_order_status(order_id, worker_id, 'completed'):
            if update_user_balance(worker_id, order['price']):
                # Уведомление исполнителю
                context.bot.send_message(
                    chat_id=worker_id,
                    text=f"✅ Администратор принял ваш заказ \"{order['title']}\"! "
                         f"На ваш баланс зачислено {order['price']} руб."
                )
                # Уведомление заказчику
                context.bot.send_message(
                    chat_id=order['user_id'],
                    text=f"Администратор принял работу по вашему заказу \"{order['title']}\"."
                )

                # Проверка завершения всех заданий по заказу
                connection = create_connection()
                if connection:
                    try:
                        cursor = connection.cursor()
                        cursor.execute("""
                        SELECT COUNT(*) as completed_count 
                        FROM accepted_orders 
                        WHERE order_id = %s AND status = 'completed'
                        """, (order_id,))
                        completed_count = cursor.fetchone()[0]

                        if completed_count >= order['quantity']:
                            update_order_status(order_id, 'completed')
                            delete_completed_order(order_id)
                    except Error as e:
                        logger.error(f"Ошибка проверки завершения заказа: {e}")
                    finally:
                        if connection.is_connected():
                            connection.close()
            else:
                context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text="Ошибка при начислении средств исполнителю."
                )

    elif action == 'reject':
        connection = create_connection()
        if not connection:
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Ошибка соединения с базой данных."
            )
            return

        try:
            cursor = connection.cursor()

            # 1. Полностью удаляем запись о принятом заказе
            cursor.execute("""
            DELETE FROM accepted_orders 
            WHERE order_id = %s AND worker_id = %s
            """, (order_id, worker_id))

            # 2. Возвращаем заказ в биржу (активный статус)
            cursor.execute("""
            UPDATE orders 
            SET status = 'active' 
            WHERE order_id = %s
            """, (order_id,))

            connection.commit()

            # 3. Наказываем исполнителя
            current_status = get_user_status(worker_id)
            new_status = 'banned' if current_status == 'suspicious' else 'suspicious'
            update_user_status(worker_id, new_status)

            status_message = "заблокирован" if new_status == 'banned' else "помечен как подозрительный"

            # 4. Отправляем уведомления
            # Исполнителю
            context.bot.send_message(
                chat_id=worker_id,
                text=f"❌ Администратор отклонил ваш заказ \"{order['title']}\". "
                     f"Ваш статус: {status_message}.\n\n"
                     f"Заказ возвращен в биржу."
            )
            # Заказчику
            context.bot.send_message(
                chat_id=order['user_id'],
                text=f"Администратор отклонил работу по вашему заказу \"{order['title']}\".\n"
                     f"Исполнитель {status_message}.\n\n"
                     f"Заказ возвращен в биржу для выполнения другим исполнителем."
            )

        except Error as e:
            logger.error(f"Ошибка при отклонении заказа: {e}")
            connection.rollback()
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Произошла ошибка при обработке запроса."
            )
        finally:
            if connection.is_connected():
                connection.close()


def start_order_creation(query, context: CallbackContext):
    """Начинает процесс создания заказа"""
    user_id = query.from_user.id
    client_balance = get_client_balance(user_id)

    if client_balance <= 0:
        query.edit_message_text(
            text="❌ У вас недостаточно средств на балансе заказчика. Пополните баланс.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Пополнить баланс", callback_data='deposit')],
                [InlineKeyboardButton("🔙 Назад", callback_data='client_menu')]
            ])
        )
        return

    query.edit_message_text(text="Для создания заказа заполните форму:\n\n1. Краткое название:")
    context.user_data['creating_order'] = {'step': 'title'}


def confirm_order_creation(update: Update, context: CallbackContext):
    """Подтверждает создание заказа"""
    query = update.callback_query
    user_id = query.from_user.id
    order_data = context.user_data['creating_order']

    # Расчет суммы к оплате
    total = order_data['price'] * order_data['quantity'] * 1.5  # 50% комиссия
    client_balance = get_client_balance(user_id)

    if client_balance < total:
        query.edit_message_text(
            text=f"❌ Недостаточно средств на балансе заказчика. Нужно: {total} руб., доступно: {client_balance} руб.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Пополнить баланс", callback_data='deposit')],
                [InlineKeyboardButton("🔙 Назад", callback_data='client_menu')]
            ])
        )
        return

    order_id = create_order(
        user_id,
        order_data['title'],
        order_data['price'],
        order_data['quantity'],
        order_data['description'],
        order_data['deadline']
    )

    if order_id:
        # Списываем средства с баланса заказчика
        update_client_balance(user_id, -total)

        admin_text = (
            f"Новый заказ для проверки:\n\n"
            f"ID: {order_id}\n"
            f"От: @{query.from_user.username or query.from_user.full_name}\n"
            f"Название: {order_data['title']}\n"
            f"Цена: {order_data['price']} руб.\n"
            f"Количество: {order_data['quantity']}\n"
            f"Срок: {order_data['deadline']} ч.\n"
            f"Описание:\n{order_data['description']}\n\n"
            f"Подтвердить заказ?"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_approve_{order_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{order_id}")
            ]
        ]

        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        query.edit_message_text(
            text="Ваш заказ отправлен на модерацию. Вы получите уведомление, когда он будет проверен.")
    else:
        # Проверяем, не превышен ли лимит заказов
        connection = create_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = %s AND status = 'active'", (user_id,))
                active_orders_count = cursor.fetchone()[0]
                if active_orders_count >= 10:
                    query.edit_message_text(text="⚠ Вы не можете иметь более 10 активных заказов одновременно.")
                    return
            except Error as e:
                logger.error(f"Ошибка проверки лимита заказов: {e}")
            finally:
                if connection.is_connected():
                    connection.close()

        query.edit_message_text(text="Произошла ошибка при создании заказа. Попробуйте позже.")

    if 'creating_order' in context.user_data:
        del context.user_data['creating_order']


def cancel_order_creation(update: Update, context: CallbackContext):
    """Отменяет создание заказа"""
    query = update.callback_query
    query.edit_message_text(text="Создание заказа отменено.")
    if 'creating_order' in context.user_data:
        del context.user_data['creating_order']


def handle_admin_action(update: Update, context: CallbackContext):
    """Обрабатывает действия администратора"""
    query = update.callback_query
    data = query.data.split('_')
    action = data[1]
    order_id = int(data[2])

    if action == 'approve':
        if update_order_status(order_id, 'active'):
            # Получаем информацию о заказе
            order = get_order_details(order_id)
            if order:
                # Уведомляем создателя заказа
                context.bot.send_message(
                    chat_id=order['user_id'],
                    text=f"✅ Ваш заказ \"{order['title']}\" подтвержден и опубликован!"
                )

            query.edit_message_text(text=f"Заказ #{order_id} успешно подтвержден и опубликован.")
        else:
            query.edit_message_text(text=f"Ошибка при подтверждении заказа #{order_id}")

    elif action == 'reject':
        # Сохраняем данные для обработки причины отклонения
        context.user_data['awaiting_admin_rejection_reason'] = {
            'order_id': order_id
        }

        query.edit_message_text(text="Укажите причину отклонения заказа:")


def handle_admin_rejection_reason(update: Update, context: CallbackContext):
    """Обрабатывает причину отклонения заказа администратором"""
    if 'awaiting_admin_rejection_reason' not in context.user_data or not update.message.text:
        return

    reason = update.message.text
    order_id = context.user_data['awaiting_admin_rejection_reason']['order_id']

    if update_order_status(order_id, 'rejected'):
        # Получаем информацию о заказе
        order = get_order_details(order_id)
        if not order:
            update.message.reply_text("Ошибка: заказ не найден.")
            return

        # Возвращаем средства заказчику
        total = order['price'] * order['quantity'] * 1.5
        update_client_balance(order['user_id'], total)

        # Уведомляем создателя заказа
        context.bot.send_message(
            chat_id=order['user_id'],
            text=f"❌ Ваш заказ \"{order['title']}\" был отклонен администратором.\n\nПричина: {reason}\n\nСредства возвращены на баланс."
        )

    update.message.reply_text(f"Заказ #{order_id} отклонен. Средства возвращены заказчику.")
    del context.user_data['awaiting_admin_rejection_reason']


def start_deposit(update: Update, context: CallbackContext):
    """Начинает процесс пополнения баланса"""
    query = update.callback_query
    query.answer()

    query.edit_message_text(text="Введите сумму пополнения (минимум 100 руб):")
    return DEPOSIT_AMOUNT


def process_deposit_fio(update: Update, context: CallbackContext):
    """Обрабатывает ввод ФИО для пополнения"""
    fio = update.message.text
    if len(fio.split()) < 2:
        update.message.reply_text("Пожалуйста, укажите ФИО в формате: Иван Иванович И. Попробуйте еще раз:")
        return DEPOSIT_FIO

    user_id = update.message.from_user.id
    amount = context.user_data['deposit']['amount']
    phone = context.user_data['deposit']['phone']
    bank = context.user_data['deposit']['bank']

    # Создаем запрос на пополнение
    deposit_id = create_deposit_request(user_id, amount, fio, phone, bank)
    if not deposit_id:
        update.message.reply_text("Произошла ошибка при обработке запроса. Попробуйте позже.")
        return ConversationHandler.END

    # Отправляем инструкции пользователю
    instructions = (
        f"📌 Инструкция по пополнению:\n\n"
        f"1. Переведите точную сумму {amount} руб. на карту:\n"
        f"💳 2202 2082 0868 5595 (Сбербанк)\n\n"
        f"2. После перевода администратор проверит платеж и зачислит средства на ваш баланс.\n\n"
        f"⚠ Если средства не поступят в течение 24 часов, пожалуйста, обратитесь в поддержку: @kirillrakitin"
    )

    # Отправляем уведомление администратору
    admin_text = (
        f"📌 Новый запрос на пополнение баланса:\n\n"
        f"ID запроса: {deposit_id}\n"
        f"👤 Пользователь: @{update.message.from_user.username or update.message.from_user.full_name} (ID: {user_id})\n"
        f"💰 Сумма: {amount} руб.\n"
        f"📱 Телефон: {phone}\n"
        f"🏦 Банк отправителя: {bank}\n"
        f"📝 ФИО: {fio}\n\n"
        f"После получения платежа нажмите кнопку ниже:"
    )

    try:
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Подтвердить пополнение", callback_data=f"confirm_deposit_{deposit_id}")]
            ])
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

    update.message.reply_text(instructions)
    return ConversationHandler.END




def process_deposit_phone(update: Update, context: CallbackContext):
    """Обрабатывает ввод телефона для пополнения"""
    phone = update.message.text
    if not phone.startswith('+') or not phone[1:].isdigit() or len(phone) < 11:
        update.message.reply_text("Пожалуйста, укажите номер в формате +79998887766. Попробуйте еще раз:")
        return DEPOSIT_PHONE

    context.user_data['deposit']['phone'] = phone
    update.message.reply_text("Введите ваш банк (например, Сбербанк, Тинькофф и т.д.):")
    return DEPOSIT_BANK


def process_deposit_bank(update: Update, context: CallbackContext):
    """Обрабатывает ввод банка для пополнения"""
    bank = update.message.text
    if len(bank) < 2:
        update.message.reply_text("Пожалуйста, укажите корректное название банка. Попробуйте еще раз:")
        return DEPOSIT_BANK

    context.user_data['deposit']['bank'] = bank
    update.message.reply_text("Введите ваше ФИО в формате: Иван Иванович И.")
    return DEPOSIT_FIO


def process_deposit_amount(update: Update, context: CallbackContext):
    """Обрабатывает ввод суммы для пополнения"""
    try:
        amount = float(update.message.text)
        if amount < 100:
            update.message.reply_text("Минимальная сумма пополнения - 100 руб. Введите сумму еще раз:")
            return DEPOSIT_AMOUNT

        context.user_data['deposit'] = {'amount': amount}
        update.message.reply_text("Введите ваш номер телефона (в формате +79998887766):")
        return DEPOSIT_PHONE
    except ValueError:
        update.message.reply_text("Пожалуйста, введите корректную сумму (например: 150.50):")
        return DEPOSIT_AMOUNT


def confirm_deposit(update: Update, context: CallbackContext):
    """Подтверждает пополнение баланса администратором"""
    query = update.callback_query
    query.answer()

    deposit_id = int(query.data.split('_')[2])

    if complete_deposit(deposit_id):
        # Получаем информацию о пополнении
        connection = create_connection()
        if connection:
            try:
                cursor = connection.cursor(dictionary=True)
                cursor.execute("SELECT user_id, amount FROM deposits WHERE deposit_id = %s", (deposit_id,))
                deposit = cursor.fetchone()

                if deposit:
                    # Уведомляем пользователя
                    context.bot.send_message(
                        chat_id=deposit['user_id'],
                        text=f"✅ Ваш баланс заказчика пополнен на {deposit['amount']} руб.!"
                    )

                    query.edit_message_text(text=query.message.text + "\n\n✅ Пополнение подтверждено")
            except Error as e:
                logger.error(f"Ошибка подтверждения пополнения: {e}")
            finally:
                if connection.is_connected():
                    connection.close()
    else:
        query.edit_message_text(text="Ошибка при подтверждении пополнения.")


def cancel_deposit(update: Update, context: CallbackContext):
    """Отменяет процесс пополнения"""
    if 'deposit' in context.user_data:
        del context.user_data['deposit']

    update.message.reply_text("❌ Пополнение баланса отменено.")
    return ConversationHandler.END


def show_help(query):
    """Показывает справку"""
    help_text = """
📚 Справка по боту:

Данный бот представляет из себя платформу, где пользователи могут создавать свои задания или выполнять чужие и получать за это реальных деньги

Функции бота:
1. 📋 Список заказов - просмотр доступных заданий
2. 👤 Профиль - информация о вашем аккаунте и активных заказах. В нем можно вывести средства
3. 👔 Меню заказчика - создание и управление своими заказами

⚠ Правила:
- Запрещено обманывать других пользователей
- Выполняйте заказы качественно и в срок

Нарушители будут заблокированы

По вопросам обращайтесь в поддержку: @kirillrakitin
"""
    keyboard = [
        [InlineKeyboardButton("📜 Нормы и правила заданий", callback_data='show_rules')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')]
    ]
    query.edit_message_text(text=help_text, reply_markup=InlineKeyboardMarkup(keyboard))


def show_rules(query):
    """Показывает нормы и правила заданий"""
    rules_text = """
📜 Нормы и правила заданий:

1. Задание - это работа, которую пользователь должен выполнить и прислать материалы, подтверждающие выполнение

2. При создании задания обязательно укажите в описании, какие результаты нужно предоставить и в виде чего прислать (фото не принимаются)

3. Материалы должны быть загружены на Яндекс.Диск, Google Drive и т.д. Ссылка отправляется в чат и пересылается заказчику.
Без этой информации администратор может отклонить задание

4. Задание может быть отклонено, если оно:
   - Создает угрозу заражения вирусом
   - Наносит явный вред другим людям
   - Нарушает законодательство

По вопросам обращайтесь в поддержку: @kirillrakitin
"""
    keyboard = [
        [InlineKeyboardButton("📚 Основная справка", callback_data='help')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')]
    ]
    query.edit_message_text(text=rules_text, reply_markup=InlineKeyboardMarkup(keyboard))


def back_to_menu(query):
    """Возвращает в главное меню"""
    keyboard = [
        [InlineKeyboardButton("📋 Список заказов", callback_data='order_list')],
        [InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("❓ Справка", callback_data='help')],
        [InlineKeyboardButton("👔 Меню заказчика", callback_data='client_menu')]
    ]
    query.edit_message_text('Главное меню:', reply_markup=InlineKeyboardMarkup(keyboard))


def button(update: Update, context: CallbackContext) -> None:
    """Обработчик callback-запросов"""
    query = update.callback_query
    query.answer()

    if query.data == 'order_list':
        show_order_list(query, sort_by='newest')  # Всегда по умолчанию новые
    elif query.data.startswith('order_page_'):
        parts = query.data.split('_')
        page = int(parts[2])
        sort_by = '_'.join(parts[3:]) if len(parts) > 3 else 'newest'

        # Проверяем валидность sort_by
        valid_sorts = ['price_high', 'price_low', 'newest', 'oldest']
        if sort_by not in valid_sorts:
            sort_by = 'newest'

        show_order_list(query, page=page, sort_by=sort_by)
    elif query.data == 'sort_orders':
        show_sort_options(query)
    elif query.data.startswith('sort_'):
        # Получаем полный тип сортировки (например 'price_high' или 'newest')
        sort_type = query.data[5:]  # Убираем префикс 'sort_'

        # Проверяем допустимые значения
        valid_sorts = ['price_high', 'price_low', 'newest', 'oldest']
        if sort_type not in valid_sorts:
            sort_type = 'newest'

        # Всегда показываем первую страницу при смене сортировки
        show_order_list(query, page=0, sort_by=sort_type)

    elif query.data.startswith('notify_user_'):
        # Обработчик уведомления пользователя
        user_id = int(query.data.split('_')[2])
        try:
            context.bot.send_message(
                chat_id=user_id,
                text="✅ Средства были переведены на ваши реквизиты. Если вы не получили деньги, пожалуйста, обратитесь в поддержку бота - @kirillrakitin"
            )
            query.edit_message_text(text=query.message.text + "\n\n✅ Пользователь уведомлен")
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя: {e}")
            query.edit_message_text(text=query.message.text + "\n\n❌ Ошибка уведомления пользователя")
    elif query.data.startswith('confirm_deposit_'):
        confirm_deposit(update, context)
    elif query.data == 'order_list':
        show_order_list(query)
    elif query.data.startswith('order_page_'):
        parts = query.data.split('_')
        page = int(parts[2])
        sort_by = parts[3] if len(parts) > 3 else 'newest'  # По умолчанию новые
        show_order_list(query, page=page, sort_by=sort_by)
        show_order_list(query, page=page)
    elif query.data == 'profile':
        show_profile(query)
    elif query.data == 'help':
        show_help(query)
    elif query.data == 'show_rules':
        show_rules(query)
    elif query.data == 'client_menu':
        show_client_menu(query)
    elif query.data == 'client_orders':
        show_client_orders(query)
    elif query.data.startswith('clientorder_'):
        show_client_order_details(query)
    elif query.data == 'create_order':
        start_order_creation(query, context)
    elif query.data == 'deposit':
        start_deposit(update, context)
    elif query.data.startswith('order_'):
        order_id = int(query.data.split('_')[1])
        if get_user_active_order(query.from_user.id, order_id):
            keyboard = [
                [InlineKeyboardButton("📌 Мои заказы", callback_data='my_orders')],
                [InlineKeyboardButton("🔙 Назад к списку", callback_data='order_list')]
            ]
            query.edit_message_text(
                text="❌ Один и тот же заказ нельзя брать повторно.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            show_order_details(query)
    elif query.data.startswith('accept_'):
        order_id = int(query.data.split('_')[1])
        if get_user_active_order(query.from_user.id, order_id):
            keyboard = [
                [InlineKeyboardButton("📌 Мои заказы", callback_data='my_orders')],
                [InlineKeyboardButton("🔙 Назад к списку", callback_data='order_list')]
            ]
            query.edit_message_text(
                text="❌ Один и тот же заказ нельзя брать повторно.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            accept_order_handler(query)
    elif query.data == 'my_orders':
        show_user_orders(query)
    elif query.data.startswith('myorder_'):
        order_id = int(query.data.split('_')[1])
        show_user_order_details(update, order_id, query.from_user.id)
    elif query.data.startswith('submit_'):
        handle_order_submission(update, context)
    elif query.data.startswith('cancel_'):
        confirm_cancel_order(query)
    elif query.data.startswith('confirm_cancel_'):
        process_order_cancellation(query)
    elif query.data.startswith('client_'):
        handle_client_decision(update, context)
    elif query.data.startswith('admin_final_'):
        handle_admin_final_decision(update, context)
    elif query.data == 'back_to_menu':
        back_to_menu(query)
    elif query.data == 'confirm_order':
        confirm_order_creation(update, context)
    elif query.data == 'cancel_order':
        cancel_order_creation(update, context)
    elif query.data.startswith('admin_'):
        handle_admin_action(update, context)
    elif query.data == 'withdraw':
        start_withdrawal(update, context)


def error_handler(update: Update, context: CallbackContext) -> None:
    """Обработчик ошибок"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


def handle_message(update: Update, context: CallbackContext) -> None:
    """Обрабатывает текстовые сообщения"""
    # Если пользователь в процессе создания заказа
    if 'creating_order' in context.user_data:
        user_id = update.message.from_user.id
        message_text = update.message.text
        step = context.user_data['creating_order']['step']

        if step == 'title':
            context.user_data['creating_order']['title'] = message_text
            context.user_data['creating_order']['step'] = 'price'
            update.message.reply_text("2. Цена за один заказ (в рублях):")
        elif step == 'price':
            try:
                price = float(message_text)
                if price <= 0:
                    raise ValueError
                context.user_data['creating_order']['price'] = price
                context.user_data['creating_order']['step'] = 'quantity'
                update.message.reply_text("3. Количество исполнителей (сколько человек могут взять этот заказ):")
            except ValueError:
                update.message.reply_text("Пожалуйста, введите корректную цену (положительное число).")
        elif step == 'quantity':
            try:
                quantity = int(message_text)
                if quantity <= 0:
                    raise ValueError
                context.user_data['creating_order']['quantity'] = quantity
                context.user_data['creating_order']['step'] = 'deadline'
                update.message.reply_text("4. Время на выполнение (в часах):")
            except ValueError:
                update.message.reply_text("Пожалуйста, введите корректное количество (целое число больше 0).")
        elif step == 'deadline':
            try:
                deadline = int(message_text)
                if deadline <= 0:
                    raise ValueError
                context.user_data['creating_order']['deadline'] = deadline
                context.user_data['creating_order']['step'] = 'description'
                update.message.reply_text(
                    "5. Подробное описание заказа, учитывая, что в описании должно быть написано, "
                    "в каком формате нужно прислать ответ, напимер: \"пришлите ссылку на яндекс диск с фотографиями\"."
                    " \nВ отсутствии этой информации администратор может отклонить заказ. \nОбратите внимание,"
                    " что в качестве проверки ботом принимается только текст.")
            except ValueError:
                update.message.reply_text("Пожалуйста, введите корректное время (целое число больше 0).")
        elif step == 'description':
            context.user_data['creating_order']['description'] = message_text

            # Расчет суммы к оплате
            price = context.user_data['creating_order']['price']
            quantity = context.user_data['creating_order']['quantity']
            total = price * quantity * 1.5  # 50% комиссия
            client_balance = get_client_balance(user_id)

            order_info = (
                f"📌 Название: {context.user_data['creating_order']['title']}\n"
                f"💵 Цена за 1 заказ: {price} руб.\n"
                f"👥 Количество исполнителей: {quantity}\n"
                f"⏱ Время на выполнение: {context.user_data['creating_order']['deadline']} ч.\n"
                f"📝 Описание:\n{message_text}\n\n"
                f"💰 Итого к оплате: {total} руб. (включая 50% комиссию)\n"
                f"💳 Доступно на балансе заказчика: {client_balance} руб.\n\n"
                f"Подтверждаете создание заказа?"
            )

            keyboard = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data='confirm_order')],
                [InlineKeyboardButton("❌ Отменить", callback_data='cancel_order')]
            ]
            update.message.reply_text(order_info, reply_markup=InlineKeyboardMarkup(keyboard))
            context.user_data['creating_order']['step'] = 'confirmation'

    # Если пользователь отправляет ссылку на выполненную работу
    elif 'awaiting_materials' in context.user_data:
        handle_materials(update, context)

    # Если администратор указывает причину отклонения заказа
    elif 'awaiting_admin_rejection_reason' in context.user_data:
        handle_admin_rejection_reason(update, context)

    # Если заказчик указывает причину отклонения работы
    elif 'awaiting_rejection_reason' in context.user_data:
        handle_rejection_reason(update, context)

    # Если пользователь в процессе вывода средств
    elif context.user_data.get('withdrawal_state') == 'amount':
        process_withdrawal_amount(update, context)
    elif context.user_data.get('withdrawal_state') == 'details':
        complete_withdrawal(update, context)


def main() -> None:
    """Основная функция"""
    init_db()
    updater = Updater(token)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))

    # Обработчик вывода средств
    withdrawal_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                lambda update, context: start_withdrawal(update, context),
                pattern='^withdraw$'
            )
        ],
        states={
            ENTER_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, process_withdrawal_amount)],
            SELECT_METHOD: [CallbackQueryHandler(process_payment_method, pattern='^method_')],
            ENTER_DETAILS: [MessageHandler(Filters.text & ~Filters.command, complete_withdrawal)]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_withdrawal, pattern='^cancel_withdraw$'),
            CommandHandler('cancel', cancel_withdrawal)
        ]
    )

    # Обработчик пополнения баланса
    deposit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                lambda update, context: start_deposit(update, context),
                pattern='^deposit$'
            )
        ],
        states={
            DEPOSIT_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, process_deposit_amount)],
            DEPOSIT_PHONE: [MessageHandler(Filters.text & ~Filters.command, process_deposit_phone)],
            DEPOSIT_BANK: [MessageHandler(Filters.text & ~Filters.command, process_deposit_bank)],
            DEPOSIT_FIO: [MessageHandler(Filters.text & ~Filters.command, process_deposit_fio)]
        },
        fallbacks=[
            CommandHandler('cancel', cancel_deposit)
        ]
    )

    dispatcher.add_handler(withdrawal_conv)
    dispatcher.add_handler(deposit_conv)
    dispatcher.add_handler(CallbackQueryHandler(button))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dispatcher.add_error_handler(error_handler)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
