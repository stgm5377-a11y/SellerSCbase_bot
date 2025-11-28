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
import time
from collections import defaultdict
import re

# ==================== СИСТЕМА БЕЗОПАСНОСТИ ====================

class SecurityManager:
    def __init__(self):
        self.user_requests = defaultdict(list)
        self.blocked_users = set()
        self.suspicious_patterns = [
            r'http[s]?://',  # URL
            r'@\w+',         # Упоминания
            r'[\w\.-]+@[\w\.-]+',  # Email
            r'[0-9]{16}',    # Номера карт
            r'(?i)admin',    # Админ команды
        ]
        self.max_requests_per_minute = 30
        self.max_message_length = 1000
        
    def is_rate_limited(self, user_id: int) -> bool:
        """Защита от флуда"""
        now = time.time()
        
        # Очистка старых запросов
        self.user_requests[user_id] = [
            req_time for req_time in self.user_requests[user_id] 
            if now - req_time < 60
        ]
        
        # Проверка лимита
        if len(self.user_requests[user_id]) >= self.max_requests_per_minute:
            if user_id not in self.blocked_users:
                logging.warning(f"🚨 User {user_id} rate limited - too many requests")
                self.blocked_users.add(user_id)
            return True
            
        self.user_requests[user_id].append(now)
        return user_id in self.blocked_users
    
    def validate_input(self, text: str, user_id: int) -> tuple[bool, str]:
        """Валидация входных данных"""
        if not text:
            return True, ""
            
        # Проверка длины
        if len(text) > self.max_message_length:
            return False, "Сообщение слишком длинное"
            
        # Проверка подозрительных паттернов
        for pattern in self.suspicious_patterns:
            if re.search(pattern, text):
                logging.warning(f"🚨 Suspicious pattern from user {user_id}: {pattern} in '{text}'")
                return False, "Обнаружен подозрительный контент"
                
        # Проверка SQL-инъекций
        sql_keywords = ['DROP', 'DELETE', 'UPDATE', 'INSERT', '--', ';']
        if any(keyword in text.upper() for keyword in sql_keywords):
            logging.warning(f"🚨 SQL injection attempt from user {user_id}: {text}")
            return False, "Недопустимые символы в сообщении"
            
        return True, ""
    
    def log_security_event(self, user_id: int, event_type: str, details: str):
        """Логирование событий безопасности"""
        logging.warning(f"SECURITY: {event_type} - User {user_id} - {details}")

security_manager = SecurityManager()

# ==================== ОБЕРТКИ ДЛЯ ЗАЩИТЫ ====================

def secure_handler(handler):
    """Декоратор для защиты обработчиков"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        message_text = update.message.text if update.message else ""
        
        # Проверка флуда
        if security_manager.is_rate_limited(user.id):
            await update.message.reply_text("🚫 Слишком много запросов. Попробуйте через минуту.")
            return
            
        # Валидация входных данных
        if message_text:
            is_valid, error_msg = security_manager.validate_input(message_text, user.id)
            if not is_valid:
                security_manager.log_security_event(user.id, "INVALID_INPUT", message_text)
                await update.message.reply_text(f"🚫 {error_msg}")
                return
                
        # Вызов оригинального обработчика
        try:
            await handler(update, context)
        except Exception as e:
            logging.error(f"Error in handler: {e}")
            security_manager.log_security_event(user.id, "HANDLER_ERROR", str(e))
            
    return wrapper

# ==================== БАЗОВЫЙ КОД (БЕЗ ИЗМЕНЕНИЙ) ====================

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
        self.query_timeout = 5  # seconds
        self.max_retries = 3
    
    def secure_execute(self, query, params=(), retry_count=0):
        """Безопасное выполнение запроса с таймаутом"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=self.query_timeout)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            
            if "DELETE" in query.upper() or "DROP" in query.upper():
                logger.warning(f"Dangerous query attempted: {query}")
            
            result = cursor.execute(query, params)
            conn.commit()
            return result
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry_count < self.max_retries:
                time.sleep(0.1)
                return self.secure_execute(query, params, retry_count + 1)
            raise e
        finally:
            conn.close()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Создаем таблицу для логов безопасности
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS security_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                activity TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
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
            # Валидация данных
            if not all(key in user_data for key in ['user_id', 'username', 'activity']):
                raise ValueError("Missing required fields")
            
            # Экранирование специальных символов
            for key, value in user_data.items():
                if isinstance(value, str):
                    user_data[key] = value.replace('"', '""').replace("'", "''")
            
            return self.secure_execute('''
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
        except Exception as e:
            logger.error(f"Security error adding to white list: {e}")
            return False

    # Остальные методы Database остаются без изменений...
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
            # Валидация данных
            if not all(key in user_data for key in ['username', 'reason']):
                raise ValueError("Missing required fields")
            
            return self.secure_execute('''
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
        except Exception as e:
            logger.error(f"Security error adding to scam list: {e}")
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
            # Валидация данных
            if not all(key in user_data for key in ['user_id', 'username', 'activity']):
                raise ValueError("Missing required fields")
            
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
            # Валидация данных
            if not all(key in report_data for key in ['reporter_id', 'scammer_username', 'description']):
                raise ValueError("Missing required fields")
            
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
            # Валидация данных
            if not all(key in appeal_data for key in ['user_id', 'username', 'explanation']):
                raise ValueError("Missing required fields")
            
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

# Клавиатуры (без изменений)
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

# Функция для обработки файлов (без изменений)
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

# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ С ЗАЩИТОЙ ====================

@secure_handler
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

@secure_handler
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

@secure_handler
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

# Остальные обработчики остаются без изменений, но добавьте @secure_handler к основным:
@secure_handler
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    await update.message.reply_text(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )

@secure_handler
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

@secure_handler
async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = """ℹ️ О проекте

Бот для ведения списков проверенных пользователей и скамеров.

Цели:
• Снизить количество мошенничеств
• Помочь найти проверенных пользователей
• Создать безопасную среду для сделок"""
    await update.message.reply_text(about_text)

# ==================== CONVERSATION HANDLERS (без изменений) ====================

# Заявка в белый список
async def start_white_list_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка безопасности
    user = update.effective_user
    if security_manager.is_rate_limited(user.id):
        await update.message.reply_text("🚫 Слишком много запросов. Попробуйте через минуту.")
        return ConversationHandler.END
    
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
    
    # Валидация ввода
    is_valid, error_msg = security_manager.validate_input(update.message.text, update.effective_user.id)
    if not is_valid:
        await update.message.reply_text(f"🚫 {error_msg}")
        return APPLICATION_ACTIVITY
    
    context.user_data['white_application']['activity'] = update.message.text
    await update.message.reply_text("2. Город / регион\nГде находится пользователь:")
    return APPLICATION_CITY

# Аналогично добавьте валидацию в process_city, process_link и т.д.

# Остальной код ConversationHandlers остается без изменений...

# ==================== ЗАПУСК БОТА ====================

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
    
    # Остальные ConversationHandlers без изменений...
    
    # Основные обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    application.add_handler(MessageHandler(filters.Regex("^🟩 Белый список$"), show_white_list))
    application.add_handler(MessageHandler(filters.Regex("^🟥 Список скамеров$"), show_scam_list))
    application.add_handler(MessageHandler(filters.Regex("^📜 Правила подачи заявок$"), show_rules))
    application.add_handler(MessageHandler(filters.Regex("^ℹ️ О проекте$"), show_about))
    
    # Добавление ConversationHandler
    application.add_handler(white_list_conv)
    # Добавьте остальные ConversationHandlers...
    
    # Обработчик callback запросов
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Запуск бота
    logger.info("🛡️ Бот запущен с системой безопасности")
    application.run_polling()

if __name__ == "__main__":
    main()