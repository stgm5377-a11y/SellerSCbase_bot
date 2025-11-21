import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, 
    CallbackQueryHandler, ConversationHandler, ContextTypes
)
import sqlite3
from datetime import datetime
from typing import Dict, List, Set

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

ADMIN_IDS = {6240653984, 5828927567}
ITEMS_PER_PAGE = 5

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(APPLICATION_ACTIVITY, APPLICATION_CITY, APPLICATION_LINK, 
 APPLICATION_DESC, APPLICATION_PROOFS, APPLICATION_CONFIRM) = range(6)

(SCAM_USERNAME, SCAM_DESCRIPTION, SCAM_PROOFS, SCAM_CONFIRM) = range(6, 10)
(APPEAL_USERNAME, APPEAL_EXPLANATION, APPEAL_PROOFS, APPEAL_CONFIRM) = range(10, 14)

# Состояния для запроса информации
(REQUEST_INFO_WHITE, REQUEST_INFO_SCAM, REQUEST_INFO_APPEAL, 
 PROVIDE_INFO_WHITE, PROVIDE_INFO_SCAM, PROVIDE_INFO_APPEAL) = range(14, 20)


class Database:
    def __init__(self):
        self.db_path = "scam_bot.db"
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Проверяем существование таблиц перед созданием
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS white_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                activity TEXT,
                city TEXT,
                link TEXT,
                description TEXT,
                proofs TEXT,
                file_ids TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'approved'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scam_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                reason TEXT,
                proofs TEXT,
                file_ids TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS white_list_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                activity TEXT,
                city TEXT,
                link TEXT,
                description TEXT,
                proofs TEXT,
                file_ids TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scam_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                scammer_username TEXT,
                description TEXT,
                proofs TEXT,
                file_ids TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS appeal_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                explanation TEXT,
                proofs TEXT,
                file_ids TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS info_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_type TEXT,
                request_id INTEGER,
                user_id INTEGER,
                admin_id INTEGER,
                request_text TEXT,
                response_text TEXT,
                response_files TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_user_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT
            )
        ''')
        
        cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("notification_channel", "")')
        cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("mass_notifications", "1")')
        
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    
    def add_to_white_list(self, user_data: Dict) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO white_list 
                (user_id, username, activity, city, link, description, proofs, file_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_data['user_id'],
                user_data['username'],
                user_data['activity'],
                user_data['city'],
                user_data['link'],
                user_data['description'],
                user_data['proofs'],
                user_data.get('file_ids', '')
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding to white list: {e}")
            return False

    def get_white_list(self, page: int = 1) -> List[Dict]:
        offset = (page - 1) * ITEMS_PER_PAGE
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM white_list 
            WHERE status = 'approved'
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        ''', (ITEMS_PER_PAGE, offset))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_white_list_count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM white_list WHERE status = "approved"')
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def add_to_scam_list(self, user_data: Dict) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO scam_list 
                (user_id, username, reason, proofs, file_ids)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_data.get('user_id'),
                user_data['username'],
                user_data['reason'],
                user_data['proofs'],
                user_data.get('file_ids', '')
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding to scam list: {e}")
            return False

    def get_scam_list(self, page: int = 1) -> List[Dict]:
        offset = (page - 1) * ITEMS_PER_PAGE
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM scam_list 
            WHERE status = 'active'
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        ''', (ITEMS_PER_PAGE, offset))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_scam_list_count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM scam_list WHERE status = "active"')
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_pending_applications(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM white_list_applications WHERE status = "pending"')
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_white_list_application_by_id(self, application_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM white_list_applications WHERE id = ?', (application_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

    def update_application_status(self, application_id: int, status: str, admin_notes: str = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if admin_notes:
            cursor.execute('''
                UPDATE white_list_applications 
                SET status = ?, admin_notes = ? 
                WHERE id = ?
            ''', (status, admin_notes, application_id))
        else:
            cursor.execute('''
                UPDATE white_list_applications 
                SET status = ? 
                WHERE id = ?
            ''', (status, application_id))
        conn.commit()
        conn.close()

    def get_pending_reports(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM scam_reports WHERE status = "pending"')
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_scam_report_by_id(self, report_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM scam_reports WHERE id = ?', (report_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

    def update_report_status(self, report_id: int, status: str, admin_notes: str = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if admin_notes:
            cursor.execute('''
                UPDATE scam_reports 
                SET status = ?, admin_notes = ? 
                WHERE id = ?
            ''', (status, admin_notes, report_id))
        else:
            cursor.execute('''
                UPDATE scam_reports 
                SET status = ? 
                WHERE id = ?
            ''', (status, report_id))
        conn.commit()
        conn.close()

    def get_pending_appeals(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM appeal_applications WHERE status = "pending"')
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_appeal_by_id(self, appeal_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM appeal_applications WHERE id = ?', (appeal_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

    def update_appeal_status(self, appeal_id: int, status: str, admin_notes: str = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if admin_notes:
            cursor.execute('''
                UPDATE appeal_applications 
                SET status = ?, admin_notes = ? 
                WHERE id = ?
            ''', (status, admin_notes, appeal_id))
        else:
            cursor.execute('''
                UPDATE appeal_applications 
                SET status = ? 
                WHERE id = ?
            ''', (status, appeal_id))
        conn.commit()
        conn.close()

    def add_user(self, user_id: int, username: str, first_name: str, last_name: str = None):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO bot_users 
                (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error adding user: {e}")

    def get_all_users(self) -> List[int]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM bot_users')
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results

    def log_action(self, admin_id: int, action: str, target_user_id: int = None, details: str = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO action_logs (admin_id, action, target_user_id, details)
            VALUES (?, ?, ?, ?)
        ''', (admin_id, action, target_user_id, details))
        conn.commit()
        conn.close()

    def add_white_list_application(self, user_data: Dict) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO white_list_applications 
                (user_id, username, activity, city, link, description, proofs, file_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_data['user_id'],
                user_data['username'],
                user_data['activity'],
                user_data['city'],
                user_data['link'],
                user_data['description'],
                user_data['proofs'],
                user_data.get('file_ids', '')
            ))
            application_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return application_id
        except Exception as e:
            logger.error(f"Error adding white list application: {e}")
            return 0

    def add_scam_report(self, report_data: Dict) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO scam_reports 
                (reporter_id, scammer_username, description, proofs, file_ids)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                report_data['reporter_id'],
                report_data['scammer_username'],
                report_data['description'],
                report_data['proofs'],
                report_data.get('file_ids', '')
            ))
            report_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return report_id
        except Exception as e:
            logger.error(f"Error adding scam report: {e}")
            return 0

    def add_appeal(self, appeal_data: Dict) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO appeal_applications 
                (user_id, username, explanation, proofs, file_ids)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                appeal_data['user_id'],
                appeal_data['username'],
                appeal_data['explanation'],
                appeal_data['proofs'],
                appeal_data.get('file_ids', '')
            ))
            appeal_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return appeal_id
        except Exception as e:
            logger.error(f"Error adding appeal: {e}")
            return 0

    def is_user_in_scam_list(self, username: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM scam_list WHERE username = ? AND status = "active"', (username,))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0

    def remove_from_scam_list(self, username: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE scam_list SET status = "removed" WHERE username = ?', (username,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error removing from scam list: {e}")
            return False

    def add_info_request(self, request_data: Dict) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO info_requests 
                (request_type, request_id, user_id, admin_id, request_text)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                request_data['request_type'],
                request_data['request_id'],
                request_data['user_id'],
                request_data['admin_id'],
                request_data['request_text']
            ))
            request_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return request_id
        except Exception as e:
            logger.error(f"Error adding info request: {e}")
            return 0

    def get_active_info_request(self, user_id: int, request_type: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if request_type:
            cursor.execute('SELECT * FROM info_requests WHERE user_id = ? AND request_type = ? AND status = "pending" ORDER BY id DESC LIMIT 1', 
                         (user_id, request_type))
        else:
            cursor.execute('SELECT * FROM info_requests WHERE user_id = ? AND status = "pending" ORDER BY id DESC LIMIT 1', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

    def update_info_request_response(self, request_id: int, response_text: str, response_files: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE info_requests 
            SET response_text = ?, response_files = ?, status = 'completed'
            WHERE id = ?
        ''', (response_text, response_files, request_id))
        conn.commit()
        conn.close()

    def get_info_request_by_id(self, request_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM info_requests WHERE id = ?', (request_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

    def get_info_request_by_type_id(self, request_type: str, request_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM info_requests WHERE request_type = ? AND request_id = ? AND status = "pending"', 
                       (request_type, request_id))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

db = Database()

# Клавиатуры
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🟩 Белый список", "🟥 Список скамеров"],
        ["✉️ Подать заявку в белый список", "❗️ Подать жалобу на скамера"],
        ["🔄 Обжаловать статус скамера"],
        ["📜 Правила подачи заявок", "ℹ️ О проекте"]
    ], resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["📋 Управление заявками", "👥 Управление белым списком"],
        ["⚠️ Управление скамерами", "📊 Статистика"],
        ["⚙️ Настройки", "🔙 В главное меню"]
    ], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Отменить"]], resize_keyboard=True)

def get_provide_info_keyboard(request_id: int, request_type: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Отправить информацию", callback_data=f"provide_{request_type}_{request_id}")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_provide_{request_type}_{request_id}")]
    ])

def get_pagination_keyboard(page: int, total_pages: int, list_type: str):
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"{list_type}_page_{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"{list_type}_page_{page+1}"))
    return InlineKeyboardMarkup([buttons]) if buttons else None

def get_application_actions_keyboard(application_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟩 Одобрить", callback_data=f"approve_white_{application_id}"),
            InlineKeyboardButton("🟥 Отклонить", callback_data=f"reject_white_{application_id}")
        ],
        [
            InlineKeyboardButton("🟦 Запросить доп. инфо", callback_data=f"info_white_{application_id}")
        ]
    ])

def get_scam_report_actions_keyboard(report_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟥 Добавить в скамеры", callback_data=f"approve_scam_{report_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_scam_{report_id}")
        ],
        [
            InlineKeyboardButton("🟦 Запросить доп. инфу", callback_data=f"info_scam_{report_id}")
        ]
    ])

def get_appeal_actions_keyboard(appeal_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Снять статус", callback_data=f"approve_appeal_{appeal_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_appeal_{appeal_id}")
        ],
        [
            InlineKeyboardButton("🟦 Запросить доп. инфо", callback_data=f"info_appeal_{appeal_id}")
        ]
    ])

# Функция для обработки файлов
async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    file_ids = []
    
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        file_ids.append(f"photo:{file.file_id}")
    elif update.message.document:
        file = await update.message.document.get_file()
        file_ids.append(f"document:{file.file_id}")
    elif update.message.video:
        file = await update.message.video.get_file()
        file_ids.append(f"video:{file.file_id}")
    elif update.message.audio:
        file = await update.message.audio.get_file()
        file_ids.append(f"audio:{file.file_id}")
    
    return ",".join(file_ids) if file_ids else ""

# Основные обработчики
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.first_name, user.last_name)
    
    if user.id in ADMIN_IDS:
        await update.message.reply_text("👑 Панель администратора", reply_markup=get_admin_keyboard())
    else:
        welcome_text = f"""👋 Привет, {user.first_name}!

🤝 Бот ведет списки проверенных пользователей и скамеров.

📋 Основные функции:
🟩 Белый список - проверенные пользователи
🟥 Список скамеров - мошенники
✉️ Подать заявку в белый список
❗️ Пожаловаться на скамера
🔄 Обжаловать статус скамера

Выберите действие: 👇"""
        await update.message.reply_text(welcome_text, reply_markup=get_main_menu_keyboard())

async def show_white_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    white_list = db.get_white_list(1)
    total_count = db.get_white_list_count()
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    if not white_list:
        text = "🟩 Белый список\n\nПока нет записей"
        await update.message.reply_text(text)
        return
    
    text = "🟩 Белый список\n\n"
    for i, user in enumerate(white_list, 1):
        text += f"{i}. @{user['username']}\n"
        text += f"   📝 {user['activity']}\n"
        if user['link'] and user['link'] != 'нет':
            text += f"   🔗 {user['link']}\n"
        text += f"   📅 {user['created_at'][:10]}\n\n"
    
    text += f"Страница 1 из {total_pages}"
    reply_markup = get_pagination_keyboard(1, total_pages, "white")
    await update.message.reply_text(text, reply_markup=reply_markup)

async def show_scam_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scam_list = db.get_scam_list(1)
    total_count = db.get_scam_list_count()
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    if not scam_list:
        text = "🟥 Список скамеров\n\nПока нет записей"
        await update.message.reply_text(text)
        return
    
    text = "🟥 Список скамеров\n\n"
    for i, scammer in enumerate(scam_list, 1):
        text += f"{i}. @{scammer['username']}\n"
        text += f"   ⚠️ {scammer['reason']}\n"
        text += f"   📅 {scammer['created_at'][:10]}\n\n"
    
    text += f"Страница 1 из {total_pages}"
    reply_markup = get_pagination_keyboard(1, total_pages, "scam")
    await update.message.reply_text(text, reply_markup=reply_markup)

# Заявка в белый список
async def start_white_list_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['white_application'] = {
        'user_id': user.id,
        'username': user.username or user.first_name
    }
    
    await update.message.reply_text(
        "✉️ Заявка в белый список\n\n"
        "Username и ID определены автоматически:\n"
        f"👤 @{user.username or user.first_name}\n"
        f"🆔 {user.id}\n\n"
        "1. Чем ты занимаешься?\nКороткое описание деятельности:",
        reply_markup=get_cancel_keyboard()
    )
    return APPLICATION_ACTIVITY

async def process_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    context.user_data['white_application']['activity'] = update.message.text
    await update.message.reply_text("2. Город / регион\nГде находится пользователь:")
    return APPLICATION_CITY

async def process_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    context.user_data['white_application']['city'] = update.message.text
    await update.message.reply_text(
        "3. Ссылка на магазин/канал/бота/профиль\n"
        "Можно написать 'нет':"
    )
    return APPLICATION_LINK

async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    context.user_data['white_application']['link'] = update.message.text
    await update.message.reply_text(
        "4. Почему тебя нужно добавить в белый список?\n"
        "Описание репутации, опыта, отзывов:"
    )
    return APPLICATION_DESC

async def process_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    context.user_data['white_application']['description'] = update.message.text
    await update.message.reply_text(
        "5. Пруфы (обязательно)\n"
        "Отправьте фото, скриншоты, документы или опишите текстом:"
    )
    return APPLICATION_PROOFS

async def process_proofs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    # Обрабатываем текст пруфов
    if update.message.text:
        context.user_data['white_application']['proofs'] = update.message.text
    else:
        context.user_data['white_application']['proofs'] = "Пруфы в виде файлов"
    
    # Обрабатываем файлы
    file_ids = await handle_files(update, context)
    if file_ids:
        context.user_data['white_application']['file_ids'] = file_ids
    
    await update.message.reply_text(
        "6. Подтверждение правил\n\n"
        "✅ Писать честно, без выдумок\n"
        "✅ Фейковые данные = отказ и бан\n"
        "✅ Админы могут отказать без объяснений\n\n"
        "Напишите 'Подтверждаю' для отправки заявки:"
    )
    return APPLICATION_CONFIRM

async def finish_white_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    if update.message.text and update.message.text.lower() == 'подтверждаю':
        application_id = db.add_white_list_application(context.user_data['white_application'])
        
        if application_id:
            app_data = context.user_data['white_application']
            
            # Отправляем админам с файлами
            for admin_id in ADMIN_IDS:
                try:
                    # Сначала отправляем текст
                    admin_text = f"""🟩 Новая заявка в Белый список #{application_id}

Пользователь: @{app_data['username']}
ID: {app_data['user_id']}

Деятельность: {app_data['activity']}
Город: {app_data['city']}
Ссылка: {app_data['link']}

Почему добавить: {app_data['description']}

Пруфы: {app_data['proofs']}"""
                    
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_text,
                        reply_markup=get_application_actions_keyboard(application_id)
                    )
                    
                    # Затем отправляем файлы если есть
                    if app_data.get('file_ids'):
                        file_list = app_data['file_ids'].split(',')
                        for file_info in file_list:
                            file_type, file_id = file_info.split(':')
                            if file_type == 'photo':
                                await context.bot.send_photo(admin_id, file_id)
                            elif file_type == 'document':
                                await context.bot.send_document(admin_id, file_id)
                            elif file_type == 'video':
                                await context.bot.send_video(admin_id, file_id)
                            elif file_type == 'audio':
                                await context.bot.send_audio(admin_id, file_id)
                            
                except Exception as e:
                    logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
            
            await update.message.reply_text(
                "✅ Заявка отправлена! Администраторы рассмотрят её в ближайшее время.",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при отправке заявки. Попробуйте позже.",
                reply_markup=get_main_menu_keyboard()
            )
        
        context.user_data.pop('white_application', None)
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Заявка не отправлена. Напишите 'Подтверждаю' для подтверждения.")
        return APPLICATION_CONFIRM

# Жалоба на скамера
async def start_scam_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❗️ Подать жалобу на скамера\n\n"
        "1. Username скамера (с @):",
        reply_markup=get_cancel_keyboard()
    )
    return SCAM_USERNAME

async def process_scam_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    username = update.message.text.replace('@', '')
    context.user_data['scam_report'] = {
        'reporter_id': update.effective_user.id,
        'scammer_username': username
    }
    await update.message.reply_text("2. Описание ситуации:")
    return SCAM_DESCRIPTION

async def process_scam_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    context.user_data['scam_report']['description'] = update.message.text
    await update.message.reply_text(
        "3. Пруфы (обязательно)\n"
        "Фото, скриншоты, документы (можно отправить файлы или описать текстом):"
    )
    return SCAM_PROOFS

async def process_scam_proofs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    # Обрабатываем текст пруфов
    if update.message.text:
        context.user_data['scam_report']['proofs'] = update.message.text
    else:
        context.user_data['scam_report']['proofs'] = "Пруфы в виде файлов"
    
    # Обрабатываем файлы
    file_ids = await handle_files(update, context)
    if file_ids:
        context.user_data['scam_report']['file_ids'] = file_ids
    
    await update.message.reply_text(
        "4. Подтверждение правил\n\n"
        "✅ Пруфы обязательны\n"
        "✅ Фейковые жалобы = бан\n"
        "✅ Возможен запрос дополнительной информации\n\n"
        "Напишите 'Подтверждаю' для отправки жалобы:"
    )
    return SCAM_CONFIRM

async def finish_scam_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    if update.message.text and update.message.text.lower() == 'подтверждаю':
        report_id = db.add_scam_report(context.user_data['scam_report'])
        
        if report_id:
            report_data = context.user_data['scam_report']
            
            # Отправляем админам с файлами
            for admin_id in ADMIN_IDS:
                try:
                    admin_text = f"""🟥 Жалоба на скамера #{report_id}

Подозреваемый: @{report_data['scammer_username']}
Жалобщик: ID {report_data['reporter_id']}

Описание ситуации: {report_data['description']}

Пруфы: {report_data['proofs']}"""
                    
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_text,
                        reply_markup=get_scam_report_actions_keyboard(report_id)
                    )
                    
                    # Отправляем файлы если есть
                    if report_data.get('file_ids'):
                        file_list = report_data['file_ids'].split(',')
                        for file_info in file_list:
                            file_type, file_id = file_info.split(':')
                            if file_type == 'photo':
                                await context.bot.send_photo(admin_id, file_id)
                            elif file_type == 'document':
                                await context.bot.send_document(admin_id, file_id)
                            elif file_type == 'video':
                                await context.bot.send_video(admin_id, file_id)
                            elif file_type == 'audio':
                                await context.bot.send_audio(admin_id, file_id)
                            
                except Exception as e:
                    logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
            
            await update.message.reply_text(
                "✅ Жалоба отправлена! Администраторы рассмотрят её в ближайшее время.",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при отправке жалобы. Попробуйте позже.",
                reply_markup=get_main_menu_keyboard()
            )
        
        context.user_data.pop('scam_report', None)
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Жалоба не отправлена. Напишите 'Подтверждаю' для подтверждения.")
        return SCAM_CONFIRM

# Обжалование статуса
async def start_appeal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 Обжалование статуса скамера\n\n"
        "1. Username пользователя, которого хотите обжаловать (с @):",
        reply_markup=get_cancel_keyboard()
    )
    return APPEAL_USERNAME

async def process_appeal_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    username = update.message.text.replace('@', '')
    
    if not db.is_user_in_scam_list(username):
        await update.message.reply_text(
            f"❌ Пользователь @{username} не найден в списке скамеров. Обжалование не требуется.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    context.user_data['appeal'] = {
        'user_id': update.effective_user.id,
        'username': username
    }
    
    await update.message.reply_text(
        f"🔄 Обжалование статуса скамера\n\n"
        f"Пользователь: @{username}\n"
        f"Жалобщик: ID {update.effective_user.id}\n\n"
        "2. Текст объяснения:",
        reply_markup=get_cancel_keyboard()
    )
    return APPEAL_EXPLANATION

async def process_appeal_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    context.user_data['appeal']['explanation'] = update.message.text
    await update.message.reply_text(
        "3. Пруфы (можно несколько)\n"
        "Доказательства невиновности (можно отправить файлы или описать текстом):"
    )
    return APPEAL_PROOFS

async def process_appeal_proofs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    # Обрабатываем текст пруфов
    if update.message.text:
        context.user_data['appeal']['proofs'] = update.message.text
    else:
        context.user_data['appeal']['proofs'] = "Пруфы в виде файлов"
    
    # Обрабатываем файлы
    file_ids = await handle_files(update, context)
    if file_ids:
        context.user_data['appeal']['file_ids'] = file_ids
    
    await update.message.reply_text(
        "4. Подтверждение правил\n\n"
        "✅ Честно описать ситуацию\n"
        "✅ Нужны доказательства невиновности\n\n"
        "Напишите 'Подтверждаю' для отправки обжалования:"
    )
    return APPEAL_CONFIRM

async def finish_appeal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отменить":
        return await cancel_application(update, context)
    
    if update.message.text and update.message.text.lower() == 'подтверждаю':
        appeal_id = db.add_appeal(context.user_data['appeal'])
        
        if appeal_id:
            appeal_data = context.user_data['appeal']
            
            # Отправляем админам с файлами
            for admin_id in ADMIN_IDS:
                try:
                    admin_text = f"""🔄 Обжалование статуса #{appeal_id}

Пользователь: @{appeal_data['username']}
Жалобщик: ID {appeal_data['user_id']}

Текст объяснения: {appeal_data['explanation']}

Пруфы: {appeal_data['proofs']}"""
                    
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_text,
                        reply_markup=get_appeal_actions_keyboard(appeal_id)
                    )
                    
                    # Отправляем файлы если есть
                    if appeal_data.get('file_ids'):
                        file_list = appeal_data['file_ids'].split(',')
                        for file_info in file_list:
                            file_type, file_id = file_info.split(':')
                            if file_type == 'photo':
                                await context.bot.send_photo(admin_id, file_id)
                            elif file_type == 'document':
                                await context.bot.send_document(admin_id, file_id)
                            elif file_type == 'video':
                                await context.bot.send_video(admin_id, file_id)
                            elif file_type == 'audio':
                                await context.bot.send_audio(admin_id, file_id)
                            
                except Exception as e:
                    logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
            
            await update.message.reply_text(
                "✅ Обжалование отправлено! Администраторы рассмотрят его в ближайшее время.",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при отправке обжалования. Попробуйте позже.",
                reply_markup=get_main_menu_keyboard()
            )
        
        context.user_data.pop('appeal', None)
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Обжалование не отправлено. Напишите 'Подтверждаю' для подтверждения.")
        return APPEAL_CONFIRM

# Отмена всех ConversationHandler
async def cancel_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Операция отменена.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# Админ функции
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    await update.message.reply_text(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )

async def show_pending_applications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    # Получаем все типы заявок
    white_applications = db.get_pending_applications()
    scam_reports = db.get_pending_reports()
    appeals = db.get_pending_appeals()
    
    total_pending = len(white_applications) + len(scam_reports) + len(appeals)
    
    if total_pending == 0:
        await update.message.reply_text("📋 Нет ожидающих заявок всех типов.")
        return
    
    # Показываем заявки по отдельности
    if white_applications:
        await update.message.reply_text(f"🟩 Заявки в белый список: {len(white_applications)}")
        for app in white_applications:
            text = f"""🟩 Заявка в Белый список #{app['id']}

Пользователь: @{app['username']}
ID: {app['user_id']}

Деятельность: {app['activity']}
Город: {app['city']}
Ссылка: {app['link']}

Почему добавить: {app['description']}

Пруфы: {app['proofs']}"""
            await update.message.reply_text(text, reply_markup=get_application_actions_keyboard(app['id']))
            
            # Отправляем файлы если есть
            if app.get('file_ids'):
                file_list = app['file_ids'].split(',')
                for file_info in file_list:
                    file_type, file_id = file_info.split(':')
                    if file_type == 'photo':
                        await context.bot.send_photo(update.effective_chat.id, file_id)
                    elif file_type == 'document':
                        await context.bot.send_document(update.effective_chat.id, file_id)
                    elif file_type == 'video':
                        await context.bot.send_video(update.effective_chat.id, file_id)
                    elif file_type == 'audio':
                        await context.bot.send_audio(update.effective_chat.id, file_id)
    
    if scam_reports:
        await update.message.reply_text(f"🟥 Жалобы на скамеров: {len(scam_reports)}")
        for report in scam_reports:
            text = f"""🟥 Жалоба на скамера #{report['id']}

Подозреваемый: @{report['scammer_username']}
Жалобщик: ID {report['reporter_id']}

Описание ситуации: {report['description']}

Пруфы: {report['proofs']}"""
            await update.message.reply_text(text, reply_markup=get_scam_report_actions_keyboard(report['id']))
            
            # Отправляем файлы если есть
            if report.get('file_ids'):
                file_list = report['file_ids'].split(',')
                for file_info in file_list:
                    file_type, file_id = file_info.split(':')
                    if file_type == 'photo':
                        await context.bot.send_photo(update.effective_chat.id, file_id)
                    elif file_type == 'document':
                        await context.bot.send_document(update.effective_chat.id, file_id)
                    elif file_type == 'video':
                        await context.bot.send_video(update.effective_chat.id, file_id)
                    elif file_type == 'audio':
                        await context.bot.send_audio(update.effective_chat.id, file_id)
    
    if appeals:
        await update.message.reply_text(f"🔄 Обжалования: {len(appeals)}")
        for appeal in appeals:
            text = f"""🔄 Обжалование статуса #{appeal['id']}

Пользователь: @{appeal['username']}
Жалобщик: ID {appeal['user_id']}

Текст объяснения: {appeal['explanation']}

Пруфы: {appeal['proofs']}"""
            await update.message.reply_text(text, reply_markup=get_appeal_actions_keyboard(appeal['id']))
            
            # Отправляем файлы если есть
            if appeal.get('file_ids'):
                file_list = appeal['file_ids'].split(',')
                for file_info in file_list:
                    file_type, file_id = file_info.split(':')
                    if file_type == 'photo':
                        await context.bot.send_photo(update.effective_chat.id, file_id)
                    elif file_type == 'document':
                        await context.bot.send_document(update.effective_chat.id, file_id)
                    elif file_type == 'video':
                        await context.bot.send_video(update.effective_chat.id, file_id)
                    elif file_type == 'audio':
                        await context.bot.send_audio(update.effective_chat.id, file_id)

# ОБРАБОТЧИК CALLBACK
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    try:
        # Пагинация
        if data.startswith('white_page_'):
            page = int(data.split('_')[-1])
            white_list = db.get_white_list(page)
            total_count = db.get_white_list_count()
            total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            
            text = "🟩 Белый список\n\n"
            for i, user in enumerate(white_list, 1):
                text += f"{i}. @{user['username']}\n"
                text += f"   📝 {user['activity']}\n"
                if user['link'] and user['link'] != 'нет':
                    text += f"   🔗 {user['link']}\n"
                text += f"   📅 {user['created_at'][:10]}\n\n"
            
            text += f"Страница {page} из {total_pages}"
            reply_markup = get_pagination_keyboard(page, total_pages, "white")
            await query.edit_message_text(text, reply_markup=reply_markup)
            return
        
        elif data.startswith('scam_page_'):
            page = int(data.split('_')[-1])
            scam_list = db.get_scam_list(page)
            total_count = db.get_scam_list_count()
            total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            
            text = "🟥 Список скамеров\n\n"
            for i, scammer in enumerate(scam_list, 1):
                text += f"{i}. @{scammer['username']}\n"
                text += f"   ⚠️ {scammer['reason']}\n"
                text += f"   📅 {scammer['created_at'][:10]}\n\n"
            
            text += f"Страница {page} из {total_pages}"
            reply_markup = get_pagination_keyboard(page, total_pages, "scam")
            await query.edit_message_text(text, reply_markup=reply_markup)
            return
        
        # Действия с заявками в белый список
        elif data.startswith('approve_white_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            app_id = int(data.split('_')[-1])
            app_data = db.get_white_list_application_by_id(app_id)
            
            if app_data:
                white_list_data = {
                    'user_id': app_data['user_id'],
                    'username': app_data['username'],
                    'activity': app_data['activity'],
                    'city': app_data['city'],
                    'link': app_data['link'],
                    'description': app_data['description'],
                    'proofs': app_data['proofs'],
                    'file_ids': app_data.get('file_ids', '')
                }
                
                if db.add_to_white_list(white_list_data):
                    db.update_application_status(app_id, "approved")
                    await query.edit_message_text(
                        query.message.text + "\n\n✅ ЗАЯВКА ОДОБРЕНА\nПользователь добавлен в белый список"
                    )
                else:
                    await query.edit_message_text(
                        query.message.text + "\n\n❌ ОШИБКА ПРИ ДОБАВЛЕНИИ"
                    )
            return
        
        elif data.startswith('reject_white_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            app_id = int(data.split('_')[-1])
            db.update_application_status(app_id, "rejected")
            await query.edit_message_text(
                query.message.text + "\n\n❌ ЗАЯВКА ОТКЛОНЕНА"
            )
            return
        
        # Действия с жалобами
        elif data.startswith('approve_scam_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            report_id = int(data.split('_')[-1])
            report_data = db.get_scam_report_by_id(report_id)
            
            if report_data:
                scam_data = {
                    'username': report_data['scammer_username'],
                    'reason': report_data['description'],
                    'proofs': report_data['proofs'],
                    'file_ids': report_data.get('file_ids', '')
                }
                
                if db.add_to_scam_list(scam_data):
                    db.update_report_status(report_id, "approved")
                    await query.edit_message_text(
                        query.message.text + "\n\n✅ ЖАЛОБА ПРИНЯТА\nПользователь добавлен в список скамеров"
                    )
                else:
                    await query.edit_message_text(
                        query.message.text + "\n\n❌ ОШИБКА ПРИ ДОБАВЛЕНИИ"
                    )
            return
        
        elif data.startswith('reject_scam_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            report_id = int(data.split('_')[-1])
            db.update_report_status(report_id, "rejected")
            await query.edit_message_text(
                query.message.text + "\n\n❌ ЖАЛОБА ОТКЛОНЕНА"
            )
            return
        
        # Действия с обжалованиями
        elif data.startswith('approve_appeal_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            appeal_id = int(data.split('_')[-1])
            appeal_data = db.get_appeal_by_id(appeal_id)
            
            if appeal_data:
                db.update_appeal_status(appeal_id, "approved")
                db.remove_from_scam_list(appeal_data['username'])
                
                await query.edit_message_text(
                    query.message.text + "\n\n✅ ОБЖАЛОВАНИЕ ПРИНЯТО\nСтатус скамера снят"
                )
            return
        
        elif data.startswith('reject_appeal_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            appeal_id = int(data.split('_')[-1])
            db.update_appeal_status(appeal_id, "rejected")
            await query.edit_message_text(
                query.message.text + "\n\n❌ ОБЖАЛОВАНИЕ ОТКЛОНЕНО"
            )
            return
        
        # ЗАПРОС ДОПОЛНИТЕЛЬНОЙ ИНФОРМАЦИИ ДЛЯ БЕЛЫХ ЗАЯВОК
        elif data.startswith('info_white_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            app_id = int(data.split('_')[-1])
            app_data = db.get_white_list_application_by_id(app_id)
            
            if app_data:
                context.user_data['requesting_info'] = {
                    'type': 'white',
                    'id': app_id,
                    'user_id': app_data['user_id']
                }
                
                await query.edit_message_text(
                    "🟦 Запрос дополнительной информации\n\n"
                    f"Заявка в белый список #{app_id}\n"
                    f"Пользователь: ID {app_data['user_id']}\n\n"
                    "Укажите, какая именно информация нужна:"
                )
                return REQUEST_INFO_WHITE
            return
        
        # ЗАПРОС ДОПОЛНИТЕЛЬНОЙ ИНФОРМАЦИИ ДЛЯ ЖАЛОБ
        elif data.startswith('info_scam_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            report_id = int(data.split('_')[-1])
            report_data = db.get_scam_report_by_id(report_id)
            
            if report_data:
                context.user_data['requesting_info'] = {
                    'type': 'scam',
                    'id': report_id,
                    'user_id': report_data['reporter_id']
                }
                
                await query.edit_message_text(
                    "🟦 Запрос дополнительной информации\n\n"
                    f"Жалоба на скамера #{report_id}\n"
                    f"Пользователь: ID {report_data['reporter_id']}\n\n"
                    "Укажите, какая именно информация нужна:"
                )
                return REQUEST_INFO_SCAM
            return
        
        # ЗАПРОС ДОПОЛНИТЕЛЬНОЙ ИНФОРМАЦИИ ДЛЯ ОБЖАЛОВАНИЙ
        elif data.startswith('info_appeal_'):
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
                
            appeal_id = int(data.split('_')[-1])
            appeal_data = db.get_appeal_by_id(appeal_id)
            
            if appeal_data:
                context.user_data['requesting_info'] = {
                    'type': 'appeal', 
                    'id': appeal_id,
                    'user_id': appeal_data['user_id']
                }
                
                await query.edit_message_text(
                    "🟦 Запрос дополнительной информации\n\n"
                    f"Обжалование #{appeal_id}\n"
                    f"Пользователь: ID {appeal_data['user_id']}\n\n"
                    "Укажите, какая именно информация нужна:"
                )
                return REQUEST_INFO_APPEAL
            return
        
        # Обработка кнопки предоставления информации пользователем
        elif data.startswith('provide_'):
            parts = data.split('_')
            request_type = parts[1]
            request_id = int(parts[2])
            
            # Получаем данные запроса
            request_data = db.get_info_request_by_id(request_id)
            if not request_data:
                await query.edit_message_text("❌ Запрос не найден или уже обработан.")
                return
            
            # Проверяем, принадлежит ли запрос пользователю
            if request_data['user_id'] != user_id:
                await query.edit_message_text("❌ У вас нет доступа к этому запросу.")
                return
            
            # Сохраняем в user_data для ConversationHandler
            context.user_data['providing_info'] = {
                'request_id': request_id,
                'request_type': request_type,
                'request_data': request_data
            }
            
            await query.edit_message_text(
                f"📤 Предоставление дополнительной информации\n\n"
                f"<b>Запрос от администратора:</b>\n{request_data['request_text']}\n\n"
                f"Пожалуйста, отправьте запрошенную информацию текстом или файлами:",
                parse_mode='HTML'
            )
            
            # Запускаем соответствующее состояние
            if request_type == 'white':
                return PROVIDE_INFO_WHITE
            elif request_type == 'scam':
                return PROVIDE_INFO_SCAM
            elif request_type == 'appeal':
                return PROVIDE_INFO_APPEAL
        
        elif data.startswith('finish_provide_'):
            # Завершаем процесс отправки
            if 'providing_info' in context.user_data:
                context.user_data.pop('providing_info')
            
            await query.edit_message_text(
                "✅ Информация отправлена администраторам. Спасибо!",
                reply_markup=get_main_menu_keyboard()
            )
            return ConversationHandler.END
        
        elif data.startswith('cancel_provide_'):
            if 'providing_info' in context.user_data:
                context.user_data.pop('providing_info')
            
            await query.edit_message_text(
                "❌ Отправка информации отменена.",
                reply_markup=get_main_menu_keyboard()
            )
            return ConversationHandler.END
            
        # Обработка кнопок админ-панели
        elif data == 'add_admin':
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
            await query.edit_message_text(
                "➕ Добавление администратора\n\n"
                "Отправьте ID пользователя, которого хотите добавить в администраторы:"
            )
            
        elif data == 'remove_admin':
            if user_id not in ADMIN_IDS:
                await query.edit_message_text("❌ У вас нет прав для этого действия.")
                return
            await query.edit_message_text(
                "➖ Удаление администратора\n\n"
                "Отправьте ID пользователя, которого хотите удалить из администраторов:"
            )
            
        elif data == 'admin_back':
            await query.edit_message_text(
                "👑 Панель администратора\n\nВыберите действие:",
                reply_markup=get_admin_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике callback: {e}")
        await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

# ОБРАБОТЧИКИ ДЛЯ ЗАПРОСА ИНФОРМАЦИИ ОТ АДМИНА
async def handle_request_info_white(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    if 'requesting_info' not in context.user_data:
        await update.message.reply_text("❌ Сессия запроса устарела")
        return ConversationHandler.END
    
    request_data = context.user_data['requesting_info']
    info_request = update.message.text
    
    # Сохраняем запрос в базе
    request_id = db.add_info_request({
        'request_type': request_data['type'],
        'request_id': request_data['id'],
        'user_id': request_data['user_id'],
        'admin_id': update.effective_user.id,
        'request_text': info_request
    })
    
    if request_id:
        # Отправляем запрос пользователю
        try:
            await context.bot.send_message(
                chat_id=request_data['user_id'],
                text=f"🟦 Администратор запросил дополнительную информацию:\n\n"
                     f"<b>Запрос:</b> {info_request}\n\n"
                     f"Пожалуйста, предоставьте дополнительную информацию, нажав кнопку ниже:",
                parse_mode='HTML',
                reply_markup=get_provide_info_keyboard(request_id, request_data['type'])
            )
            
            await update.message.reply_text(
                f"✅ Запрос информации отправлен пользователю ID {request_data['user_id']}",
                reply_markup=get_admin_keyboard()
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Не удалось отправить запрос пользователю: {e}")
    
    context.user_data.pop('requesting_info', None)
    return ConversationHandler.END

async def handle_request_info_scam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    if 'requesting_info' not in context.user_data:
        await update.message.reply_text("❌ Сессия запроса устарела")
        return ConversationHandler.END
    
    request_data = context.user_data['requesting_info']
    info_request = update.message.text
    
    # Сохраняем запрос в базе
    request_id = db.add_info_request({
        'request_type': request_data['type'],
        'request_id': request_data['id'],
        'user_id': request_data['user_id'],
        'admin_id': update.effective_user.id,
        'request_text': info_request
    })
    
    if request_id:
        # Отправляем запрос пользователю
        try:
            await context.bot.send_message(
                chat_id=request_data['user_id'],
                text=f"🟦 Администратор запросил дополнительную информацию:\n\n"
                     f"<b>Запрос:</b> {info_request}\n\n"
                     f"Пожалуйста, предоставьте дополнительную информацию, нажав кнопку ниже:",
                parse_mode='HTML',
                reply_markup=get_provide_info_keyboard(request_id, request_data['type'])
            )
            
            await update.message.reply_text(
                f"✅ Запрос информации отправлен пользователю ID {request_data['user_id']}",
                reply_markup=get_admin_keyboard()
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Не удалось отправить запрос: {e}")
    
    context.user_data.pop('requesting_info', None)
    return ConversationHandler.END

async def handle_request_info_appeal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    if 'requesting_info' not in context.user_data:
        await update.message.reply_text("❌ Сессия запроса устарела")
        return ConversationHandler.END
    
    request_data = context.user_data['requesting_info']
    info_request = update.message.text
    
    # Сохраняем запрос в базе
    request_id = db.add_info_request({
        'request_type': request_data['type'],
        'request_id': request_data['id'],
        'user_id': request_data['user_id'],
        'admin_id': update.effective_user.id,
        'request_text': info_request
    })
    
    if request_id:
        # Отправляем запрос пользователю
        try:
            await context.bot.send_message(
                chat_id=request_data['user_id'],
                text=f"🟦 Администратор запросил дополнительную информацию:\n\n"
                     f"<b>Запрос:</b> {info_request}\n\n"
                     f"Пожалуйста, предоставьте дополнительную информацию, нажав кнопку ниже:",
                parse_mode='HTML',
                reply_markup=get_provide_info_keyboard(request_id, request_data['type'])
            )
            
            await update.message.reply_text(
                f"✅ Запрос информации отправлен пользователю ID {request_data['user_id']}",
                reply_markup=get_admin_keyboard()
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Не удалось отправить запрос: {e}")
    
    context.user_data.pop('requesting_info', None)
    return ConversationHandler.END

# УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ДЛЯ ПРЕДОСТАВЛЕНИЯ ИНФОРМАЦИИ
async def handle_provide_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'providing_info' not in context.user_data:
        await update.message.reply_text("❌ Сессия устарела")
        return ConversationHandler.END
    
    provide_data = context.user_data['providing_info']
    request_id = provide_data['request_id']
    request_type = provide_data['request_type']
    request_data = provide_data['request_data']
    
    # Сохраняем ответ пользователя
    response_text = update.message.text or ""
    file_ids = await handle_files(update, context)
    
    # Обновляем запрос в базе
    db.update_info_request_response(request_id, response_text, file_ids)
    
    # Получаем данные оригинальной заявки для кнопок
    original_data = None
    if request_type == 'white':
        original_data = db.get_white_list_application_by_id(request_data['request_id'])
    elif request_type == 'scam':
        original_data = db.get_scam_report_by_id(request_data['request_id'])
    elif request_type == 'appeal':
        original_data = db.get_appeal_by_id(request_data['request_id'])
    
    if original_data:
        # Уведомляем админа с кнопками управления
        admin_message = f"""🟦 ПОЛУЧЕНА ДОП. ИНФОРМАЦИЯ

Запрос #{request_id} ({'Белая заявка' if request_type == 'white' else 'Жалоба' if request_type == 'scam' else 'Обжалование'} #{request_data['request_id']})
От пользователя: ID {update.effective_user.id}

<b>Исходный запрос:</b>
{request_data['request_text']}

<b>Ответ пользователя:</b>
{response_text if response_text else 'Без текстового ответа'}"""
        
        # Отправляем админу с кнопками управления
        for admin_id in ADMIN_IDS:
            try:
                # Отправляем текст с кнопками
                if request_type == 'white':
                    await context.bot.send_message(
                        admin_id, 
                        admin_message,
                        parse_mode='HTML',
                        reply_markup=get_application_actions_keyboard(request_data['request_id'])
                    )
                elif request_type == 'scam':
                    await context.bot.send_message(
                        admin_id, 
                        admin_message,
                        parse_mode='HTML',
                        reply_markup=get_scam_report_actions_keyboard(request_data['request_id'])
                    )
                elif request_type == 'appeal':
                    await context.bot.send_message(
                        admin_id, 
                        admin_message,
                        parse_mode='HTML',
                        reply_markup=get_appeal_actions_keyboard(request_data['request_id'])
                    )
                
                # Отправляем файлы если есть
                if file_ids:
                    file_list = file_ids.split(',')
                    for file_info in file_list:
                        file_type, file_id = file_info.split(':')
                        caption = f"Файл от пользователя ID {update.effective_user.id} (запрос #{request_id})"
                        
                        if file_type == 'photo':
                            await context.bot.send_photo(admin_id, file_id, caption=caption)
                        elif file_type == 'document':
                            await context.bot.send_document(admin_id, file_id, caption=caption)
                        elif file_type == 'video':
                            await context.bot.send_video(admin_id, file_id, caption=caption)
                        elif file_type == 'audio':
                            await context.bot.send_audio(admin_id, file_id, caption=caption)
                            
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin_id}: {e}")
    
    # Завершаем процесс
    context.user_data.pop('providing_info', None)
    
    await update.message.reply_text(
        "✅ Информация отправлена администраторам. Спасибо!",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# Обработчики завершения предоставления информации
async def provide_info_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if 'providing_info' in context.user_data:
        context.user_data.pop('providing_info')
    
    await query.edit_message_text(
        "✅ Информация отправлена администраторам. Спасибо!",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def provide_info_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if 'providing_info' in context.user_data:
        context.user_data.pop('providing_info')
    
    await query.edit_message_text(
        "❌ Отправка информации отменена.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# Остальные функции админа
async def admin_manage_white_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    white_count = db.get_white_list_count()
    await update.message.reply_text(
        f"👥 Управление белым списком\n\nЗаписей: {white_count}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Показать белый список", callback_data="show_white_list_admin")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ])
    )

async def admin_manage_scam_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    scam_count = db.get_scam_list_count()
    await update.message.reply_text(
        f"⚠️ Управление скамерами\n\nЗаписей: {scam_count}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Показать список скамеров", callback_data="show_scam_list_admin")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ])
    )

async def admin_show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    white_count = db.get_white_list_count()
    scam_count = db.get_scam_list_count()
    pending_apps = len(db.get_pending_applications())
    pending_reports = len(db.get_pending_reports())
    pending_appeals = len(db.get_pending_appeals())
    total_users = len(db.get_all_users())
    
    stats_text = f"""📊 Статистика бота

🟩 Белый список: {white_count}
🟥 Скамеры: {scam_count}
📋 Ожидают заявок: {pending_apps}
⚠️ Ожидают жалоб: {pending_reports}
🔄 Ожидают обжалований: {pending_appeals}
👥 Всего пользователей: {total_users}"""
    await update.message.reply_text(stats_text)

async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    await update.message.reply_text(
        "⚙️ Настройки админа\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin")],
            [InlineKeyboardButton("➖ Удалить админа", callback_data="remove_admin")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ])
    )

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules_text = """📜 Правила подачи заявок

🟩 Для белого списка:
• Писать честно, без выдумок
• Желательно прислать пруфы
• Фейковые данные = отказ и бан
• Админы могут отказать без объяснений

🟥 Для жалоб:
• Пруфы обязательны
• Фейковые жалобы = бан
• Возможен запрос дополнительной информации

🔄 Для обжалования:
• Нужно честно описать ситуацию
• Нужны доказательства невиновности"""
    await update.message.reply_text(rules_text)

async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = """ℹ️ О проекте

Бот для ведения списков проверенных пользователей и скамеров.

Цели:
• Снизить количество мошенничеств
• Помочь найти проверенных пользователей
• Создать безопасную среду для сделок"""
    await update.message.reply_text(about_text)

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ОСНОВНАЯ ФУНКЦИЯ
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен. Установите переменную окружения BOT_TOKEN.")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ConversationHandler для заявки в белый список
    white_list_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✉️ Подать заявку в белый список$"), start_white_list_application)],
        states={
            APPLICATION_ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_activity)],
            APPLICATION_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_city)],
            APPLICATION_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_link)],
            APPLICATION_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_description)],
            APPLICATION_PROOFS: [MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO, process_proofs)],
            APPLICATION_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_white_application)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Отменить$"), cancel_application), CommandHandler("cancel", cancel_application)]
    )
    
    # ConversationHandler для жалобы на скамера
    scam_report_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^❗️ Подать жалобу на скамера$"), start_scam_report)],
        states={
            SCAM_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_scam_username)],
            SCAM_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_scam_description)],
            SCAM_PROOFS: [MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO, process_scam_proofs)],
            SCAM_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_scam_report)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Отменить$"), cancel_application), CommandHandler("cancel", cancel_application)]
    )
    
    # ConversationHandler для обжалования
    appeal_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔄 Обжаловать статус скамера$"), start_appeal)],
        states={
            APPEAL_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_appeal_username)],
            APPEAL_EXPLANATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_appeal_explanation)],
            APPEAL_PROOFS: [MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO, process_appeal_proofs)],
            APPEAL_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_appeal)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Отменить$"), cancel_application), CommandHandler("cancel", cancel_application)]
    )
    
    # ConversationHandler для запроса информации админом
    request_info_white_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^info_white_")],
        states={
            REQUEST_INFO_WHITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_request_info_white)]
        },
        fallbacks=[CommandHandler("cancel", cancel_application)]
    )
    
    request_info_scam_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^info_scam_")],
        states={
            REQUEST_INFO_SCAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_request_info_scam)]
        },
        fallbacks=[CommandHandler("cancel", cancel_application)]
    )
    
    request_info_appeal_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^info_appeal_")],
        states={
            REQUEST_INFO_APPEAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_request_info_appeal)]
        },
        fallbacks=[CommandHandler("cancel", cancel_application)]
    )

    # УНИВЕРСАЛЬНЫЙ ConversationHandler для предоставления информации пользователем
    provide_info_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^provide_")],
        states={
            PROVIDE_INFO_WHITE: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_provide_info)
            ],
            PROVIDE_INFO_SCAM: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_provide_info)
            ],
            PROVIDE_INFO_APPEAL: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_provide_info)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_application),
            CallbackQueryHandler(provide_info_finish, pattern="^finish_provide_"),
            CallbackQueryHandler(provide_info_cancel, pattern="^cancel_provide_")
        ]
    )

    # Основные обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    application.add_handler(MessageHandler(filters.Regex("^🟩 Белый список$"), show_white_list))
    application.add_handler(MessageHandler(filters.Regex("^🟥 Список скамеров$"), show_scam_list))
    application.add_handler(MessageHandler(filters.Regex("^📋 Управление заявками$"), show_pending_applications))
    application.add_handler(MessageHandler(filters.Regex("^👥 Управление белым списком$"), admin_manage_white_list))
    application.add_handler(MessageHandler(filters.Regex("^⚠️ Управление скамерами$"), admin_manage_scam_list))
    application.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), admin_show_stats))
    application.add_handler(MessageHandler(filters.Regex("^⚙️ Настройки$"), admin_settings))
    application.add_handler(MessageHandler(filters.Regex("^📜 Правила подачи заявок$"), show_rules))
    application.add_handler(MessageHandler(filters.Regex("^ℹ️ О проекте$"), show_about))
    application.add_handler(MessageHandler(filters.Regex("^🔙 В главное меню$"), back_to_main))
    
    # Добавление ConversationHandler
    application.add_handler(white_list_conv)
    application.add_handler(scam_report_conv)
    application.add_handler(appeal_conv)
    application.add_handler(request_info_white_conv)
    application.add_handler(request_info_scam_conv)
    application.add_handler(request_info_appeal_conv)
    application.add_handler(provide_info_conv)
    
    # Обработчик callback запросов
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Запуск бота
    logger.info("Бот запущен")
    application.run_polling()

if __name__ == "__main__":
    main()