
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests
from dotenv import load_dotenv
import hashlib
import hmac
import uuid
import decimal
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from flask import Flask, request, jsonify
from threading import Thread
import qrcode
from io import BytesIO

# --- Load environment variables ---
load_dotenv()

# --- Flask Keep Alive & Webhooks ---
app = Flask('')

@app.route('/webhook/zapupi', methods=['POST'])
def zapupi_webhook():
    data = request.get_json()
    logger.info(f"Zapupi webhook received: {data}")
    threading.Thread(target=process_zapupi_webhook, args=(data,)).start()
    return jsonify({"status": "ok"}), 200

@app.route('/')
def home():
    return "XN HOSTING BOT - Advanced Bot Hosting Platform"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive & Webhook server started.")

# --- Configuration ---
TOKEN = os.getenv('TOKEN', '8913116499:AAGYS-aTCaTPaX8lSK8xbEmElO7R3ICh0Po')
OWNER_ID = int(os.getenv('OWNER_ID', 6952035047))
ADMIN_ID = int(os.getenv('ADMIN_ID', 6952035047))
YOUR_USERNAME = os.getenv('YOUR_USERNAME', '@Xit_Macro')
UPDATE_CHANNEL = os.getenv('UPDATE_CHANNEL', '@XMHostingOfficial')
SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', '@Xit_Macro')

FREE_USER_LIMIT = 0
SUBSCRIBED_USER_LIMIT = 5
ADMIN_LIMIT = 20
OWNER_LIMIT = float('inf')

TRIAL_DURATION_HOURS = 1
TRIAL_BOT_LIMIT = 1
TRIAL_COOLDOWN_DAYS = 30

EXCHANGE_RATE = 83.0  # INR per USD

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
os.makedirs(TEMPLATES_DIR, exist_ok=True)

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')  # default HTML to avoid markdown parsing issues

# --- Data structures ---
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
banned_users = set()
user_limits = {}
bot_locked = False

pending_modules = {}
manual_install_requests = {}
mandatory_channels = {}
pending_zip_files = {}

plan_groups_cache = {}   # id -> {id, name, bot_limit, ram_limit, description, status}
plan_prices_cache = {}   # id -> {id, group_id, duration_months, price_inr}
zapupi_settings = {}
binance_manual_settings = {}

user_wallets = {}

templates_cache = {}
template_purchases_cache = {}

security_bypass_requests = {}
expired_user_data = {}
pending_add_balance = {}

# --- Security Settings ---
SECURITY_CONFIG = {
    'blocked_modules': ['os.system', 'os', 'zipfile', 'subprocess.Popen', 'subprocess', 'eval', 'exec','compile', '__import__'],
    'max_file_size': 20 * 1024 * 1024,
    'max_script_runtime': 3600,
    'allowed_extensions': ['.py', '.js'],
    'blocked_imports': ['shutil.rmtree', 'subprocess','os.remove', 'os.unlink']
}

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Database Setup with Migrations ---
def init_db():
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        # Existing tables
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT, PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY, join_date TEXT, last_seen TEXT, phone TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_by INTEGER, added_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, ban_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_limits (user_id INTEGER PRIMARY KEY, file_limit INTEGER, set_by INTEGER, set_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS mandatory_channels (channel_id TEXT PRIMARY KEY, channel_username TEXT, channel_name TEXT, added_by INTEGER, added_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS install_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, module_name TEXT, package_name TEXT, status TEXT, log TEXT, install_date TEXT)''')

        # Plan groups and prices
        c.execute('''CREATE TABLE IF NOT EXISTS plan_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            bot_limit INTEGER NOT NULL,
            ram_limit INTEGER DEFAULT 128,
            description TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS plan_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            duration_months INTEGER NOT NULL,
            price_inr REAL NOT NULL,
            FOREIGN KEY (group_id) REFERENCES plan_groups(id),
            UNIQUE(group_id, duration_months)
        )''')

        # Payment tables
        c.execute('''CREATE TABLE IF NOT EXISTS zapupi_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, api_key TEXT, gateway_enabled INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_id INTEGER, amount REAL, currency TEXT, gateway TEXT, transaction_id TEXT UNIQUE, status TEXT DEFAULT 'pending', type TEXT DEFAULT 'plan', payment_details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_id INTEGER, start_date TEXT, expiry_date TEXT, bot_limit INTEGER, ram_limit INTEGER DEFAULT 128, active INTEGER DEFAULT 1, transaction_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES active_users(user_id), FOREIGN KEY (plan_id) REFERENCES plan_groups(id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS payment_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, gateway TEXT, request_data TEXT, response_data TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_trials (user_id INTEGER PRIMARY KEY, start_time TEXT, expiry_time TEXT, active INTEGER DEFAULT 1, last_trial_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS wallets (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, updated_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS wallet_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, type TEXT, description TEXT, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS auto_renew_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_id INTEGER, amount REAL, status TEXT, message TEXT, created_at TEXT)''')

        # Templates
        c.execute('''CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price_inr REAL NOT NULL,
            demo_video_url TEXT,
            zip_file_path TEXT NOT NULL,
            required_params TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS template_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            template_id INTEGER,
            transaction_id INTEGER,
            params TEXT,
            bot_script_key TEXT,
            folder_name TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES active_users(user_id),
            FOREIGN KEY (template_id) REFERENCES templates(id),
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS binance_manual_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT,
            binance_id TEXT,
            trc_address TEXT,
            enabled INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        # Security Bypass Requests
        c.execute('''CREATE TABLE IF NOT EXISTS security_bypass_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            file_path TEXT,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            resolved_by INTEGER
        )''')

        # Expired User Data
        c.execute('''CREATE TABLE IF NOT EXISTS expired_user_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            deletion_date TEXT,
            notified_10d INTEGER DEFAULT 0,
            notified_5d INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        # --- MIGRATIONS: ensure columns exist ---
        for col, dtype in [
            ('bot_limit', 'INTEGER'),
            ('ram_limit', 'INTEGER DEFAULT 128'),
            ('description', 'TEXT'),
            ('status', "TEXT DEFAULT 'active'")
        ]:
            try:
                c.execute(f"ALTER TABLE plan_groups ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                pass

        for col, dtype in [
            ('demo_video_url', 'TEXT'),
            ('required_params', 'TEXT')
        ]:
            try:
                c.execute(f"ALTER TABLE templates ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                pass

        try:
            c.execute("ALTER TABLE binance_manual_settings ADD COLUMN binance_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE binance_manual_settings ADD COLUMN trc_address TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE transactions ADD COLUMN type TEXT DEFAULT 'plan'")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE template_purchases ADD COLUMN folder_name TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE template_purchases ADD COLUMN bot_script_key TEXT")
        except sqlite3.OperationalError:
            pass

        # --- Insert default plan groups and prices ---
        c.execute('SELECT COUNT(*) FROM plan_groups')
        if c.fetchone()[0] == 0:
            default_groups = [
                ('Entry', 1, 128, '1 Bot'),
                ('Pro', 3, 256, '3 Bots'),
                ('Prime', 5, 512, '5 Bots'),
                ('Business', 10, 1024, '10 Bots'),
                ('Business Pro', 25, 2048, '25 Bots'),
                ('Enterprise', 50, 4096, '50 Bots')
            ]
            group_ids = {}
            for name, bot_limit, ram, desc in default_groups:
                c.execute('''INSERT INTO plan_groups (name, bot_limit, ram_limit, description, status)
                             VALUES (?, ?, ?, ?, 'active')''', (name, bot_limit, ram, desc))
                group_ids[name] = c.lastrowid

            prices = {
                'Entry': {1: 60, 2: 120, 3: 180, 6: 360, 12: 720},
                'Pro': {1: 160, 2: 320, 3: 480, 6: 960, 12: 1920},
                'Prime': {1: 270, 2: 540, 3: 810, 6: 1620, 12: 3240},
                'Business': {1: 550, 2: 1100, 3: 1650, 6: 3300, 12: 6600},
                'Business Pro': {1: 1400, 2: 2800, 3: 4200, 6: 8400, 12: 16800},
                'Enterprise': {1: 2500, 2: 5000, 3: 7500, 6: 15000, 12: 30000}
            }
            for group_name, dur_prices in prices.items():
                gid = group_ids[group_name]
                for months, price in dur_prices.items():
                    c.execute('INSERT INTO plan_prices (group_id, duration_months, price_inr) VALUES (?, ?, ?)',
                              (gid, months, price))
            logger.info("Default plan groups and prices inserted.")

        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("exchange_rate", "83.0")')
        c.execute('INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)', (OWNER_ID, OWNER_ID, datetime.now().isoformat()))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)', (ADMIN_ID, OWNER_ID, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

def load_data():
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except ValueError:
                logger.warning(f"⚠️ Invalid expiry date format for user {user_id}: {expiry}. Skipping.")
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            if (file_name, file_type) not in user_files[user_id]:
                user_files[user_id].append((file_name, file_type))
        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())
        c.execute('SELECT user_id FROM banned_users')
        banned_users.update(user_id for (user_id,) in c.fetchall())
        c.execute('SELECT user_id, file_limit FROM user_limits')
        for user_id, file_limit in c.fetchall():
            user_limits[user_id] = file_limit
        c.execute('SELECT channel_id, channel_username, channel_name FROM mandatory_channels')
        for channel_id, channel_username, channel_name in c.fetchall():
            mandatory_channels[channel_id] = {'username': channel_username, 'name': channel_name}
        c.execute('SELECT id, name, bot_limit, ram_limit, description, status FROM plan_groups')
        for row in c.fetchall():
            plan_groups_cache[row[0]] = {
                'id': row[0],
                'name': row[1],
                'bot_limit': row[2],
                'ram_limit': row[3],
                'description': row[4],
                'status': row[5]
            }
        c.execute('SELECT id, group_id, duration_months, price_inr FROM plan_prices')
        for row in c.fetchall():
            plan_prices_cache[row[0]] = {
                'id': row[0],
                'group_id': row[1],
                'duration_months': row[2],
                'price_inr': row[3]
            }
        c.execute('SELECT api_key, gateway_enabled FROM zapupi_settings ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        if row:
            zapupi_settings['api_key'] = row[0]
            zapupi_settings['enabled'] = bool(row[1])
        else:
            zapupi_settings['api_key'] = None
            zapupi_settings['enabled'] = False
        c.execute('SELECT value FROM settings WHERE key = "exchange_rate"')
        row = c.fetchone()
        if row:
            global EXCHANGE_RATE
            EXCHANGE_RATE = float(row[0])
        c.execute('SELECT user_id, balance FROM wallets')
        for user_id, balance in c.fetchall():
            user_wallets[user_id] = balance

        c.execute('SELECT id, name, description, price_inr, demo_video_url, zip_file_path, required_params, status FROM templates')
        for row in c.fetchall():
            templates_cache[row[0]] = {
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'price_inr': row[3],
                'demo_video_url': row[4],
                'zip_file_path': row[5],
                'required_params': json.loads(row[6]) if row[6] else [],
                'status': row[7]
            }
        c.execute('SELECT address, binance_id, trc_address, enabled FROM binance_manual_settings ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        if row:
            binance_manual_settings['address'] = row[0]
            binance_manual_settings['binance_id'] = row[1]
            binance_manual_settings['trc_address'] = row[2]
            binance_manual_settings['enabled'] = bool(row[3])
        else:
            binance_manual_settings['address'] = ''
            binance_manual_settings['binance_id'] = ''
            binance_manual_settings['trc_address'] = ''
            binance_manual_settings['enabled'] = False

        c.execute('SELECT id, user_id, file_name, file_path, reason, status FROM security_bypass_requests WHERE status = "pending"')
        for row in c.fetchall():
            security_bypass_requests[row[0]] = {
                'id': row[0],
                'user_id': row[1],
                'file_name': row[2],
                'file_path': row[3],
                'reason': row[4],
                'status': row[5]
            }

        c.execute('SELECT id, user_id, deletion_date, notified_10d, notified_5d, deleted FROM expired_user_data WHERE deleted = 0')
        for row in c.fetchall():
            expired_user_data[row[0]] = {
                'id': row[0],
                'user_id': row[1],
                'deletion_date': datetime.fromisoformat(row[2]),
                'notified_10d': bool(row[3]),
                'notified_5d': bool(row[4]),
                'deleted': bool(row[5])
            }

        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(plan_groups_cache)} groups, {len(plan_prices_cache)} prices, {len(templates_cache)} templates, wallets: {len(user_wallets)}")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

init_db()
load_data()

# --- Helper functions for plan system ---
def get_plan_group(group_id):
    return plan_groups_cache.get(group_id)

def get_plan_prices_for_group(group_id):
    return [p for p in plan_prices_cache.values() if p['group_id'] == group_id]

def get_price_display(price_inr):
    usd = price_inr / EXCHANGE_RATE
    return f"₹{price_inr:.0f} (≈ ${usd:.2f} USDT)"

def get_user_active_plan(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''SELECT plan_id, bot_limit, ram_limit, expiry_date FROM user_plans 
                 WHERE user_id = ? AND active = 1 AND expiry_date > datetime('now') 
                 ORDER BY expiry_date DESC LIMIT 1''', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        plan_id, bot_limit, ram_limit, expiry_date = row
        return {'plan_id': plan_id, 'bot_limit': bot_limit, 'ram_limit': ram_limit, 'expiry_date': datetime.fromisoformat(expiry_date)}
    return None

def get_user_plan_limit(user_id):
    plan = get_user_active_plan(user_id)
    if plan:
        return plan['bot_limit']
    return None

def get_user_ram_limit(user_id):
    plan = get_user_active_plan(user_id)
    if plan:
        return plan['ram_limit']
    if get_user_trial(user_id):
        return 128
    return 64

def get_user_file_limit(user_id):
    plan_limit = get_user_plan_limit(user_id)
    if plan_limit is not None:
        return plan_limit
    trial_expiry = get_user_trial(user_id)
    if trial_expiry:
        return TRIAL_BOT_LIMIT
    if user_id == OWNER_ID:
        return OWNER_LIMIT
    if user_id in admin_ids:
        return ADMIN_LIMIT
    if user_id in user_limits:
        return user_limits[user_id]
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def activate_user_plan(user_id, group_id, duration_months, transaction_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT bot_limit, ram_limit FROM plan_groups WHERE id = ?', (group_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Plan group not found"
    bot_limit, ram_limit = row

    c.execute('SELECT id, expiry_date FROM user_plans WHERE user_id = ? AND active = 1', (user_id,))
    existing = c.fetchone()
    start_date = datetime.now()
    expiry_date = start_date + timedelta(days=duration_months*30)  # approx

    if existing:
        existing_id, existing_expiry_str = existing
        existing_expiry = datetime.fromisoformat(existing_expiry_str)
        if existing_expiry > start_date:
            new_expiry = existing_expiry + timedelta(days=duration_months*30)
        else:
            new_expiry = expiry_date
        c.execute('''UPDATE user_plans SET plan_id = ?, start_date = ?, expiry_date = ?, bot_limit = ?, ram_limit = ?, updated_at = datetime("now") WHERE id = ?''',
                  (group_id, start_date.isoformat(), new_expiry.isoformat(), bot_limit, ram_limit, existing_id))
        conn.commit()
        conn.close()
        save_subscription(user_id, new_expiry)
        return True, new_expiry
    else:
        c.execute('''INSERT INTO user_plans (user_id, plan_id, start_date, expiry_date, bot_limit, ram_limit, active, transaction_id)
                     VALUES (?, ?, ?, ?, ?, ?, 1, ?)''',
                  (user_id, group_id, start_date.isoformat(), expiry_date.isoformat(), bot_limit, ram_limit, transaction_id))
        conn.commit()
        conn.close()
        save_subscription(user_id, expiry_date)
        return True, expiry_date

# --- Trial system functions (unchanged) ---
def get_user_trial(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT expiry_time, last_trial_date FROM user_trials WHERE user_id = ? AND active = 1', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        try:
            expiry = datetime.fromisoformat(row[0])
            if expiry > datetime.now():
                return expiry
            else:
                deactivate_trial(user_id)
                return None
        except:
            return None
    return None

def can_start_trial(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT last_trial_date FROM user_trials WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        try:
            last_trial = datetime.fromisoformat(row[0])
            if (datetime.now() - last_trial).days < TRIAL_COOLDOWN_DAYS:
                return False, f"Please wait {TRIAL_COOLDOWN_DAYS} days between trials. Your last trial was on {last_trial.strftime('%Y-%m-%d')}."
        except:
            pass
    return True, "OK"

def activate_trial(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM user_trials WHERE user_id = ?', (user_id,))
    start = datetime.now()
    expiry = start + timedelta(hours=TRIAL_DURATION_HOURS)
    c.execute('INSERT INTO user_trials (user_id, start_time, expiry_time, active, last_trial_date) VALUES (?, ?, ?, 1, ?)',
              (user_id, start.isoformat(), expiry.isoformat(), start.isoformat()))
    conn.commit()
    conn.close()
    logger.info(f"Trial activated for user {user_id}, expires at {expiry}")

def deactivate_trial(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE user_trials SET active = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    delete_user_files(user_id)
    logger.info(f"Trial deactivated and files deleted for user {user_id}")

def delete_user_files(user_id):
    user_folder = get_user_folder(user_id)
    if os.path.exists(user_folder):
        try:
            shutil.rmtree(user_folder)
            logger.info(f"Deleted folder for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting folder for {user_id}: {e}")
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM user_files WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    if user_id in user_files:
        del user_files[user_id]
    for script_key in list(bot_scripts.keys()):
        if script_key.startswith(f"{user_id}_"):
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

def trial_expiry_checker():
    while True:
        try:
            time.sleep(60)
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('SELECT user_id FROM user_trials WHERE active = 1 AND expiry_time < ?', (now,))
            expired_users = [row[0] for row in c.fetchall()]
            conn.close()
            for user_id in expired_users:
                logger.info(f"Trial expired for user {user_id}, deleting files.")
                deactivate_trial(user_id)
                try:
                    bot.send_message(user_id, "⏰ Your 1-hour trial has expired. Your files have been deleted. To continue hosting, please purchase a plan using /plans.")
                except:
                    pass
        except Exception as e:
            logger.error(f"Error in trial expiry checker: {e}")

trial_thread = threading.Thread(target=trial_expiry_checker, daemon=True)
trial_thread.start()

# --- Wallet functions ---
def get_wallet_balance(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT balance FROM wallets WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0]
    return 0.0

def update_wallet_balance(user_id, amount, description, transaction_type='credit'):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO wallets (user_id, balance, updated_at) VALUES (?, COALESCE((SELECT balance FROM wallets WHERE user_id = ?), 0) + ?, datetime("now"))',
              (user_id, user_id, amount))
    c.execute('INSERT INTO wallet_transactions (user_id, amount, type, description, created_at) VALUES (?, ?, ?, ?, datetime("now"))',
              (user_id, amount, transaction_type, description))
    conn.commit()
    conn.close()
    user_wallets[user_id] = get_wallet_balance(user_id)
    return True

def deduct_wallet(user_id, amount, description):
    balance = get_wallet_balance(user_id)
    if balance < amount:
        return False, f"Insufficient balance: {balance} < {amount}"
    update_wallet_balance(user_id, -amount, description, 'debit')
    return True, "Success"

# --- Auto-renewal ---
def check_auto_renewals():
    while True:
        try:
            time.sleep(3600)
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('''SELECT up.id, up.user_id, up.plan_id, up.bot_limit, up.ram_limit, pg.name, 
                                (SELECT price_inr FROM plan_prices WHERE group_id = up.plan_id AND duration_months = 1) as price,
                                30 as duration_days
                         FROM user_plans up
                         JOIN plan_groups pg ON up.plan_id = pg.id
                         WHERE up.active = 1 AND up.expiry_date < datetime('now')''')
            expired_plans = c.fetchall()
            conn.close()
            for plan_id, user_id, group_id, bot_limit, ram_limit, group_name, price, duration_days in expired_plans:
                if not price:
                    continue
                balance = get_wallet_balance(user_id)
                if balance >= price:
                    success, msg = deduct_wallet(user_id, price, f"Auto-renewal of plan {group_name} (ID: {group_id})")
                    if success:
                        new_expiry = datetime.now() + timedelta(days=duration_days)
                        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                        c = conn.cursor()
                        c.execute('UPDATE user_plans SET expiry_date = ?, updated_at = datetime("now") WHERE id = ?', (new_expiry.isoformat(), plan_id))
                        conn.commit()
                        conn.close()
                        save_subscription(user_id, new_expiry)
                        logger.info(f"Auto-renewed plan for user {user_id}, plan {group_id}, new expiry {new_expiry}")
                        try:
                            bot.send_message(user_id, f"🔄 Your plan '{group_name}' has been auto-renewed for another {duration_days} days. Amount ₹{price:.2f} deducted from wallet. New expiry: {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}")
                        except:
                            pass
                        remove_expired_user_data(user_id)
                    else:
                        logger.warning(f"Auto-renewal failed for user {user_id}: {msg}")
                        try:
                            bot.send_message(user_id, f"⚠️ Auto-renewal failed: {msg}. Please add funds to your wallet to keep your plan active.")
                        except:
                            pass
                        schedule_user_data_deletion(user_id)
                else:
                    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('UPDATE user_plans SET active = 0 WHERE id = ?', (plan_id,))
                    conn.commit()
                    conn.close()
                    logger.info(f"Plan deactivated for user {user_id} due to insufficient wallet balance.")
                    try:
                        bot.send_message(user_id, f"❌ Your plan '{group_name}' has expired and could not be auto-renewed due to insufficient wallet balance. Please top up your wallet or purchase a new plan.")
                    except:
                        pass
                    schedule_user_data_deletion(user_id)
        except Exception as e:
            logger.error(f"Error in auto-renewal checker: {e}", exc_info=True)

auto_renew_thread = threading.Thread(target=check_auto_renewals, daemon=True)
auto_renew_thread.start()

# --- Expired user data deletion functions ---
def schedule_user_data_deletion(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id FROM expired_user_data WHERE user_id = ? AND deleted = 0', (user_id,))
    if c.fetchone():
        conn.close()
        return
    deletion_date = datetime.now() + timedelta(days=14)
    c.execute('INSERT INTO expired_user_data (user_id, deletion_date, notified_10d, notified_5d, deleted) VALUES (?, ?, 0, 0, 0)',
              (user_id, deletion_date.isoformat()))
    conn.commit()
    conn.close()
    expired_user_data[user_id] = {
        'id': None,
        'user_id': user_id,
        'deletion_date': deletion_date,
        'notified_10d': False,
        'notified_5d': False,
        'deleted': False
    }
    logger.info(f"Scheduled deletion for user {user_id} on {deletion_date}")

def remove_expired_user_data(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM expired_user_data WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    if user_id in expired_user_data:
        del expired_user_data[user_id]
    logger.info(f"Removed deletion schedule for user {user_id}")

def check_expired_user_data():
    while True:
        try:
            time.sleep(3600)
            now = datetime.now()
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT id, user_id, deletion_date, notified_10d, notified_5d, deleted FROM expired_user_data WHERE deleted = 0')
            rows = c.fetchall()
            conn.close()
            for row in rows:
                entry_id, user_id, deletion_date_str, notified_10d, notified_5d, deleted = row
                deletion_date = datetime.fromisoformat(deletion_date_str)
                days_left = (deletion_date - now).days

                if days_left <= 10 and not notified_10d:
                    try:
                        bot.send_message(user_id, f"⚠️ Your hosting files will be deleted in {days_left} days because your plan has expired. Please renew your plan to keep your bots running.")
                        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                        c = conn.cursor()
                        c.execute('UPDATE expired_user_data SET notified_10d = 1 WHERE id = ?', (entry_id,))
                        conn.commit()
                        conn.close()
                        expired_user_data[user_id]['notified_10d'] = True
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id} about deletion: {e}")

                if days_left <= 5 and not notified_5d:
                    try:
                        bot.send_message(user_id, f"⚠️ Your hosting files will be deleted in {days_left} days! Please renew immediately to avoid data loss.")
                        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                        c = conn.cursor()
                        c.execute('UPDATE expired_user_data SET notified_5d = 1 WHERE id = ?', (entry_id,))
                        conn.commit()
                        conn.close()
                        expired_user_data[user_id]['notified_5d'] = True
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id} about deletion: {e}")

                if days_left <= 0:
                    logger.info(f"Deleting files for user {user_id} due to expired plan.")
                    delete_user_files(user_id)
                    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('UPDATE expired_user_data SET deleted = 1 WHERE id = ?', (entry_id,))
                    conn.commit()
                    conn.close()
                    if user_id in expired_user_data:
                        expired_user_data[user_id]['deleted'] = True
                    try:
                        bot.send_message(user_id, "🗑️ Your files have been deleted because your plan expired over 14 days ago and you did not renew. You can upload again after purchasing a plan.")
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error in expired data checker: {e}", exc_info=True)

expired_data_thread = threading.Thread(target=check_expired_user_data, daemon=True)
expired_data_thread.start()

# --- Payment and Transaction functions ---
def generate_transaction_id():
    return f"TXN_{uuid.uuid4().hex[:12].upper()}_{int(time.time())}"

def create_transaction(user_id, amount, gateway, transaction_id, plan_id=None, txn_type='plan', duration_months=None, group_id=None):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    details = {}
    if duration_months:
        details['duration_months'] = duration_months
    if group_id:
        details['group_id'] = group_id
    c.execute('''INSERT INTO transactions (user_id, plan_id, amount, currency, gateway, transaction_id, status, type, payment_details, created_at)
                 VALUES (?, ?, ?, 'INR', ?, ?, 'pending', ?, ?, datetime("now"))''',
              (user_id, plan_id, amount, gateway, transaction_id, txn_type, json.dumps(details) if details else None))
    txn_db_id = c.lastrowid
    conn.commit()
    conn.close()
    return txn_db_id

def update_transaction_status(txn_id, status, details=None):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    if details:
        c.execute('UPDATE transactions SET status = ?, payment_details = ?, updated_at = datetime("now") WHERE id = ?', (status, json.dumps(details), txn_id))
    else:
        c.execute('UPDATE transactions SET status = ?, updated_at = datetime("now") WHERE id = ?', (status, txn_id))
    conn.commit()
    conn.close()

def get_pending_transactions(gateway=None):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    if gateway:
        c.execute('SELECT id, user_id, plan_id, amount, transaction_id, gateway, type FROM transactions WHERE status = "pending" AND gateway = ?', (gateway,))
    else:
        c.execute('SELECT id, user_id, plan_id, amount, transaction_id, gateway, type FROM transactions WHERE status = "pending"')
    rows = c.fetchall()
    conn.close()
    return rows

def get_transaction_by_id(transaction_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, user_id, plan_id, amount, status, type FROM transactions WHERE transaction_id = ?', (transaction_id,))
    row = c.fetchone()
    conn.close()
    return row

def complete_transaction(transaction_id, user_id, group_id=None, amount=None, txn_type='plan', duration_months=None):
    if txn_type == 'plan' and group_id and duration_months:
        success, result = activate_user_plan(user_id, group_id, duration_months, transaction_id)
        if success:
            expiry_date = result
            remove_expired_user_data(user_id)
            return True, f"Plan activated until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            return False, result
    elif txn_type == 'balance':
        if amount is None:
            return False, "Amount missing for balance transaction"
        update_wallet_balance(user_id, amount, f"Added balance via {transaction_id}", 'credit')
        return True, f"₹{amount:.2f} added to wallet"
    elif txn_type == 'template':
        return True, "Template purchase recorded, awaiting activation."
    else:
        return False, "Unknown transaction type"

# --- Zapupi integration ---
def create_zapupi_order(user_id, amount, order_id, plan_id=None, txn_type='plan', duration_months=None):
    api_key = zapupi_settings.get('api_key')
    if not api_key:
        return None, "Zapupi API key not configured."
    if amount <= 0:
        return None, "Amount must be positive"
    customer_mobile = "9999999999"
    url = "https://pay.zapupi.com/api/create-order"
    payload = {
        "zap_key": api_key,
        "order_id": order_id,
        "amount": str(amount),
        "customer_mobile": customer_mobile,
        "remark": f"{txn_type.upper()} for user {user_id}" + (f" Plan {plan_id}" if plan_id else ""),
        "success_url": "https://your-domain.com/success",
        "failed_url": "https://your-domain.com/failed",
        "timeout_url": "https://your-domain.com/timeout",
        "webhook_url": "https://your-domain.com/webhook/zapupi"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('status') == 'success':
            txn_id = data.get('txn_id')
            payment_url = data.get('payment_url')
            return txn_id, payment_url
        else:
            return None, f"Zapupi error: {data.get('message')}"
    except Exception as e:
        logger.error(f"Zapupi order creation error: {e}")
        return None, str(e)

def verify_zapupi_order(order_id):
    api_key = zapupi_settings.get('api_key')
    if not api_key:
        return False, "Zapupi API key missing"
    url = "https://pay.zapupi.com/api/order-status"
    payload = {"zap_key": api_key, "order_id": order_id}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('status') == 'success':
            order_data = data.get('data', {})
            status = order_data.get('status', '').lower()
            if status == 'success':
                return True, "Paid"
            elif status == 'pending':
                return False, "Pending"
            else:
                return False, f"Status: {status}"
        else:
            return False, f"API error: {data.get('message')}"
    except Exception as e:
        logger.error(f"Zapupi verify error: {e}")
        return False, str(e)

# --- Helper: validate URL ---
def is_valid_url(url):
    if not url:
        return False
    return url.startswith('http://') or url.startswith('https://')

# --- Existing helper functions ---
def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try:
                        script_info['log_file'].close()
                    except Exception as log_e:
                        logger.error(f"Error closing log file during zombie cleanup {script_key}: {log_e}")
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try:
                    script_info['log_file'].close()
                except Exception as log_e:
                    logger.error(f"Error closing log file during cleanup of non-existent process {script_key}: {log_e}")
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"Error checking process status for {script_key}: {e}", exc_info=True)
            return False
    return False

def kill_process_tree(process_info):
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A')
    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
                logger.info(f"Closed log file for {script_key}")
            except Exception as log_e:
                logger.error(f"Error closing log file during kill for {script_key}: {log_e}")
        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                        except Exception as e:
                            try:
                                child.kill()
                            except:
                                pass
                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        try:
                            p.kill()
                        except:
                            pass
                    try:
                        parent.terminate()
                        try:
                            parent.wait(timeout=1)
                        except psutil.TimeoutExpired:
                            parent.kill()
                    except psutil.NoSuchProcess:
                        pass
                except psutil.NoSuchProcess:
                    pass
        elif log_file_closed:
            logger.warning(f"Process object missing for {script_key}, but log file closed.")
        else:
            logger.error(f"Process object missing for {script_key}, and no log file. Cannot kill.")
    except Exception as e:
        logger.error(f"❌ Unexpected error killing process tree for PID {pid or 'N/A'} ({script_key}): {e}", exc_info=True)

# --- Security functions ---
def check_code_security(file_path, file_type, allow_bypass=False):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        dangerous_patterns = [r'\bos\b', r'\bos\.system\b', r'\bos\.(remove|unlink|walk|listdir|scandir|stat|popen|fork|exec|kill|spawn)\b',
            r'\bshutdown\b', r'\breboot\b', r'rm\s+-rf', r'format\s+c:', r'dd\s+if=', r'\bmkfs\b', r'\bfdisk\b',
            r'chmod\s+777', r'chmod\s+\+x', r'\bsys\.exit\b', r'\bsys\.argv\b', r'\bls\b', r'\bcd\b', r'\bvps\b',
            r'\bkill\b', r'\bkillall\b', r'\bpkill\b', r'\bkill\s+-\d+', r'\bhalt\b', r'\bpoweroff\b',
            r'\binit\s+0', r'\binit\s+6', r'\btelinit\s+0', r'\btelinit\s+6', r'\bmv\b.*/dev/null',
            r'\bcat\s+>/dev/null', r'>\s*/dev/null', r'2>\s*&1', r'\b&\s*$', r'\bnohup\b', r'\bdisown\b',
            r'rm\s+-rf\s+/', r'rm\s+-rf\s+~', r'rm\s+-rf\s+\.', r'rm\s+-rf\s+\*', r'rm\s+-rf\s+.*',
            r'\bdd\s+if=/dev/zero', r'\bdd\s+of=/dev/sda', r'\bmv\s+/dev/null', r'>\s+\.bash_history',
            r'>\s+\.zsh_history', r'echo\s+""\s+>', r'truncate\s+-s\s+0', r':>\s*']
        found_patterns = []
        for pattern in dangerous_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                found_patterns.append(pattern)
        if found_patterns:
            if allow_bypass:
                logger.warning(f"🚨 Dangerous patterns detected but bypass allowed: {found_patterns}")
                return True, "Code is safe (bypassed)"
            logger.warning(f"🚨 Dangerous patterns detected in {file_path}: {found_patterns}")
            return False, f"Code contains dangerous commands: {', '.join(found_patterns[:5])}"
        return True, "Code is safe"
    except Exception as e:
        logger.error(f"Error in security check: {e}")
        return False, f"Security check error: {str(e)}"

def scan_zip_security(zip_path, allow_bypass=False):
    try:
        dangerous_patterns = [r'\bos\b', r'\bos\.system\b', r'\bos\.(remove|unlink|walk|listdir|scandir|stat|popen|fork|exec|kill|spawn)\b',
            r'\bshutdown\b', r'\breboot\b', r'rm\s+-rf', r'format\s+c:', r'dd\s+if=', r'\bmkfs\b', r'\bfdisk\b',
            r'chmod\s+777', r'chmod\s+\+x', r'\bsys\.exit\b', r'\bsys\.argv\b', r'\bls\b', r'\bcd\b', r'\bvps\b',
            r'\bkill\b', r'\bkillall\b', r'\bpkill\b', r'\bkill\s+-\d+', r'\bhalt\b', r'\bpoweroff\b',
            r'\binit\s+0', r'\binit\s+6', r'\btelinit\s+0', r'\btelinit\s+6', r'\bmv\b.*/dev/null',
            r'\bcat\s+>/dev/null', r'>\s*/dev/null', r'2>\s*&1', r'\b&\s*$', r'\bnohup\b', r'\bdisown\b',
            r'rm\s+-rf\s+/', r'rm\s+-rf\s+~', r'rm\s+-rf\s+\.', r'rm\s+-rf\s+\*', r'rm\s+-rf\s+.*',
            r'\bdd\s+if=/dev/zero', r'\bdd\s+of=/dev/sda', r'\bmv\s+/dev/null', r'>\s+\.bash_history',
            r'>\s+\.zsh_history', r'echo\s+""\s+>', r'truncate\s+-s\s+0', r':>\s*']
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith(('.py', '.js', '.zip', '.txt', '.sh', '.bat', '.cmd')):
                    with zip_ref.open(file_info.filename) as f:
                        try:
                            content = f.read().decode('utf-8', errors='ignore')
                        except:
                            continue
                        for pattern in dangerous_patterns:
                            if re.search(pattern, content, re.IGNORECASE):
                                if allow_bypass:
                                    logger.warning(f"Zip contains dangerous pattern but bypass allowed: {pattern}")
                                    continue
                                return False, f"File {file_info.filename} contains dangerous command: {pattern}"
        return True, "Archive is safe"
    except Exception as e:
        return False, f"Error scanning archive: {str(e)}"

# --- Mandatory Channels Functions ---
def is_user_member(user_id, channel_id):
    try:
        chat_member = bot.get_chat_member(channel_id, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking channel membership for {user_id} in {channel_id}: {e}")
        return False

def check_mandatory_subscription(user_id):
    if not mandatory_channels:
        return True, []
    not_joined = []
    for channel_id, channel_info in mandatory_channels.items():
        if not is_user_member(user_id, channel_id):
            not_joined.append((channel_id, channel_info))
    if not_joined:
        return False, not_joined
    return True, []

def save_mandatory_channel(channel_id, channel_username, channel_name, added_by):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            added_date = datetime.now().isoformat()
            c.execute('INSERT OR REPLACE INTO mandatory_channels (channel_id, channel_username, channel_name, added_by, added_date) VALUES (?, ?, ?, ?, ?)',
                      (channel_id, channel_username, channel_name, added_by, added_date))
            conn.commit()
            mandatory_channels[channel_id] = {'username': channel_username, 'name': channel_name}
            return True
        except:
            return False
        finally:
            conn.close()

def remove_mandatory_channel_db(channel_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM mandatory_channels WHERE channel_id = ?', (channel_id,))
            conn.commit()
            if channel_id in mandatory_channels:
                del mandatory_channels[channel_id]
            return True
        except:
            return False
        finally:
            conn.close()

def create_mandatory_channels_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Add Channel', callback_data='add_mandatory_channel'),
               types.InlineKeyboardButton('➖ Remove Channel', callback_data='remove_mandatory_channel'))
    markup.row(types.InlineKeyboardButton('📋 List Channels', callback_data='list_mandatory_channels'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_subscription_check_message(not_joined_channels):
    message = "📢 **Important: Join Our Channels First:**\n\n"
    markup = types.InlineKeyboardMarkup()
    for channel_id, channel_info in not_joined_channels:
        channel_username = channel_info.get('username', '')
        channel_name = channel_info.get('name', 'Channel')
        if channel_username:
            channel_link = f"https://t.me/{channel_username.replace('@', '')}"
        else:
            channel_link = f"https://t.me/c/{channel_id.replace('-100', '')}"
        message += f"• {channel_name}\n"
        markup.add(types.InlineKeyboardButton(f"Join {channel_name}", url=channel_link))
    markup.add(types.InlineKeyboardButton("✅ Verify Subscription", callback_data='check_subscription_status'))
    return message, markup

DB_LOCK = threading.Lock()

# --- User Management Functions ---
def is_user_banned(user_id):
    return user_id in banned_users

def ban_user_db(user_id, reason, banned_by):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            ban_date = datetime.now().isoformat()
            c.execute('INSERT OR REPLACE INTO banned_users (user_id, reason, banned_by, ban_date) VALUES (?, ?, ?, ?)',
                      (user_id, reason, banned_by, ban_date))
            conn.commit()
            banned_users.add(user_id)
            return True
        except:
            return False
        finally:
            conn.close()

def unban_user_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
            conn.commit()
            banned_users.discard(user_id)
            return True
        except:
            return False
        finally:
            conn.close()

def set_user_limit_db(user_id, limit, set_by):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            set_date = datetime.now().isoformat()
            c.execute('INSERT OR REPLACE INTO user_limits (user_id, file_limit, set_by, set_date) VALUES (?, ?, ?, ?)',
                      (user_id, limit, set_by, set_date))
            conn.commit()
            user_limits[user_id] = limit
            return True
        except:
            return False
        finally:
            conn.close()

def remove_user_limit_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_limits WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_limits:
                del user_limits[user_id]
            return True
        except:
            return False
        finally:
            conn.close()

# --- Other helper functions ---
def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files: user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
        except:
            pass
        finally:
            conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]:
                    del user_files[user_id]
        except:
            pass
        finally:
            conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            join_date = datetime.now().isoformat()
            c.execute('INSERT OR REPLACE INTO active_users (user_id, join_date, last_seen, phone) VALUES (?, ?, ?, ?)',
                      (user_id, join_date, join_date, ''))
            conn.commit()
        except:
            pass
        finally:
            conn.close()

def save_subscription(user_id, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (user_id, expiry_str))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry}
        except:
            pass
        finally:
            conn.close()

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions:
                del user_subscriptions[user_id]
        except:
            pass
        finally:
            conn.close()

def add_admin_db(admin_id, added_by):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            added_date = datetime.now().isoformat()
            c.execute('INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)',
                      (admin_id, added_by, added_date))
            conn.commit()
            admin_ids.add(admin_id)
        except:
            pass
        finally:
            conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
            conn.commit()
            if c.rowcount > 0:
                admin_ids.discard(admin_id)
                return True
            return False
        except:
            return False
        finally:
            conn.close()

# --- TELEGRAM_MODULES mapping ---
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'telethon.sync': 'telethon',
    'telepot': 'telepot',
    'pytg': 'pytg',
    'tgcrypto': 'tgcrypto',
    'telegram_upload': 'telegram-upload',
    'telegram_send': 'telegram-send',
    'telegram_text': 'telegram-text',
    'mtproto': 'telegram-mtproto',
    'tl': 'telethon',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'psutil': 'psutil',
}

# --- Manual install functions ---
def save_install_log(user_id, module_name, package_name, status, log):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            install_date = datetime.now().isoformat()
            c.execute('INSERT INTO install_logs (user_id, module_name, package_name, status, log, install_date) VALUES (?, ?, ?, ?, ?, ?)',
                      (user_id, module_name, package_name, status, log, install_date))
            conn.commit()
        except:
            pass
        finally:
            conn.close()

def attempt_install_pip(module_name, message, manual_request=False):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None:
        return False, "Core module - no installation needed"
    try:
        if manual_request:
            bot.reply_to(message, f"🔄 Manual installation requested for `{module_name}` -> `{package_name}`...", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"🐍 Module `{module_name}` not found. Installing `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            log_msg = f"Installed {package_name}. Output:\n{result.stdout}"
            bot.reply_to(message, f"✅ Package `{package_name}` (for `{module_name}`) installed successfully.", parse_mode='Markdown')
            save_install_log(message.from_user.id, module_name, package_name, "success", log_msg)
            return True, log_msg
        else:
            error_msg = f"❌ Failed to install `{package_name}` for `{module_name}`.\nLog:\n```\n{result.stderr or result.stdout}\n```"
            if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            save_install_log(message.from_user.id, module_name, package_name, "failed", error_msg)
            return False, error_msg
    except Exception as e:
        error_msg = f"❌ Error installing `{package_name}`: {str(e)}"
        bot.reply_to(message, error_msg)
        save_install_log(message.from_user.id, module_name, package_name, "error", error_msg)
        return False, error_msg

def attempt_install_npm(module_name, user_folder, message, manual_request=False):
    try:
        if manual_request:
            bot.reply_to(message, f"🔄 Manual Node package installation requested for `{module_name}`...", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"🟠 Node package `{module_name}` not found. Installing locally...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            log_msg = f"Installed {module_name}. Output:\n{result.stdout}"
            bot.reply_to(message, f"✅ Node package `{module_name}` installed locally.", parse_mode='Markdown')
            save_install_log(message.from_user.id, module_name, module_name, "success", log_msg)
            return True, log_msg
        else:
            error_msg = f"❌ Failed to install Node package `{module_name}`.\nLog:\n```\n{result.stderr or result.stdout}\n```"
            if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            save_install_log(message.from_user.id, module_name, module_name, "failed", error_msg)
            return False, error_msg
    except FileNotFoundError:
        error_msg = "❌ Error: 'npm' not found. Ensure Node.js/npm are installed and in PATH."
        bot.reply_to(message, error_msg)
        save_install_log(message.from_user.id, module_name, module_name, "error", error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"❌ Error installing Node package `{module_name}`: {str(e)}"
        bot.reply_to(message, error_msg)
        save_install_log(message.from_user.id, module_name, module_name, "error", error_msg)
        return False, error_msg

def manual_install_module_init(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked by admin. Try later.")
        return
    msg = bot.reply_to(message, "📦 Send module name to install (e.g., `requests` or `pillow`)\nFor Node.js: `npm:module_name`\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_manual_install_module)

def process_manual_install_module(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Installation cancelled.")
        return
    module_name = message.text.strip()
    if module_name.lower().startswith('npm:'):
        module_name = module_name[4:].strip()
        user_folder = get_user_folder(user_id)
        success, log = attempt_install_npm(module_name, user_folder, message, manual_request=True)
    else:
        success, log = attempt_install_pip(module_name, message, manual_request=True)
    if success:
        logger.info(f"User {user_id} manually installed module: {module_name}")

# --- Menu creation functions ---
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates', url=f'https://t.me/{UPDATE_CHANNEL.replace("@", "")}'),
        types.InlineKeyboardButton('📤 Upload', callback_data='upload'),
        types.InlineKeyboardButton('📂 My Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Speed', callback_data='speed'),
        types.InlineKeyboardButton('📦 Install Module', callback_data='manual_install'),
        types.InlineKeyboardButton('💰 Balance', callback_data='wallet_menu'),
        types.InlineKeyboardButton('🤖 Available Bots', callback_data='available_bots'),
        types.InlineKeyboardButton('📊 Stats', callback_data='stats')
    ]
    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('🔒 Lock' if not bot_locked else '🔓 Unlock', callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('📢 Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('🟢 Run All', callback_data='run_all_scripts'),
            types.InlineKeyboardButton('📢 Channels', callback_data='manage_mandatory_channels'),
            types.InlineKeyboardButton('👥 Users', callback_data='user_management'),
            types.InlineKeyboardButton('🔧 Admin Install', callback_data='admin_install'),
            types.InlineKeyboardButton('⚙️ Settings', callback_data='admin_settings'),
            types.InlineKeyboardButton('💰 Wallet Mgmt', callback_data='admin_wallet_management'),
            types.InlineKeyboardButton('📦 Templates', callback_data='manage_templates'),
            types.InlineKeyboardButton('💲 Payments', callback_data='admin_payment_settings'),
            types.InlineKeyboardButton('📋 Plans', callback_data='admin_plan_management'),
            types.InlineKeyboardButton('📋 Pending Payments', callback_data='admin_pending_payments')
        ]
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], buttons[4])
        markup.add(buttons[5], buttons[6])
        markup.add(buttons[7])
        markup.add(admin_buttons[0], admin_buttons[2])
        markup.add(admin_buttons[1], admin_buttons[3])
        markup.add(admin_buttons[4], admin_buttons[5])
        markup.add(admin_buttons[6], admin_buttons[7])
        markup.add(admin_buttons[8], admin_buttons[9])
        markup.add(admin_buttons[10], admin_buttons[11])
        markup.add(admin_buttons[12], admin_buttons[13])
    else:
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], buttons[4])
        markup.add(buttons[5], buttons[6])
        markup.add(buttons[7])
    return markup

def create_wallet_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    balance = get_wallet_balance(user_id)
    markup.add(types.InlineKeyboardButton(f"💰 Balance: ₹{balance:.2f}", callback_data='wallet_balance'))
    markup.add(types.InlineKeyboardButton("➕ Add Balance", callback_data='add_balance'))
    markup.add(types.InlineKeyboardButton("📊 Transactions", callback_data='wallet_transactions'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_to_main'))
    return markup

def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    user_buttons = [
        ["📢 Updates Channel"],
        ["📤 Upload File", "📂 Check Files"],
        ["⚡ Bot Speed", "📊 Statistics"],
        ["💰 Balance"],
        ["📦 Manual Install", "🆘 Help"],
        ["📋 View Plans", "🛒 Purchase Plan"],
        ["📅 My Subscription"],
        ["🎁 Get Trial"],
        ["🤖 Available Bots"]
    ]
    if user_id in admin_ids:
        admin_buttons = [
            ["📢 Updates Channel"],
            ["📤 Upload File", "📂 Check Files"],
            ["⚡ Bot Speed", "📊 Statistics"],
            ["💳 Subscriptions", "📢 Broadcast"],
            ["🔒 Lock Bot", "🟢 Running All Code"],
            ["👑 Admin Panel"],
            ["📢 Channel Add", "🛠️ Manual Install"],
            ["👥 User Management", "⚙️ Settings"],
            ["💲 Payment Settings", "📋 Plan Management"],
            ["💰 Wallet Management"],
            ["📋 View Plans", "🛒 Purchase Plan"],
            ["🤖 Available Bots"],
            ["📦 Manage Templates"],
            ["📋 Pending Payments"]
        ]
        for row in admin_buttons:
            markup.add(*[types.KeyboardButton(text) for text in row])
    else:
        for row in user_buttons:
            markup.add(*[types.KeyboardButton(text) for text in row])
    return markup

def create_control_buttons(script_owner_id, file_name, is_running=True, is_template=False, purchase_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.row(types.InlineKeyboardButton("🔴 Stop", callback_data=f'stop_{script_owner_id}_{file_name}'),
                   types.InlineKeyboardButton("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}'))
        markup.row(types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}'),
                   types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}'))
    else:
        markup.row(types.InlineKeyboardButton("🟢 Start", callback_data=f'start_{script_owner_id}_{file_name}'),
                   types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}'))
        markup.row(types.InlineKeyboardButton("📜 View Logs", callback_data=f'logs_{script_owner_id}_{file_name}'))
    markup.add(types.InlineKeyboardButton("🔙 Back to Files", callback_data='check_files'))
    return markup

def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Add Admin', callback_data='add_admin'),
               types.InlineKeyboardButton('➖ Remove Admin', callback_data='remove_admin'))
    markup.row(types.InlineKeyboardButton('📋 List Admins', callback_data='list_admins'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_user_management_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('🚫 Ban User', callback_data='ban_user'),
               types.InlineKeyboardButton('✅ Unban User', callback_data='unban_user'))
    markup.row(types.InlineKeyboardButton('📊 User Info', callback_data='user_info'),
               types.InlineKeyboardButton('👥 All Users', callback_data='all_users'))
    markup.row(types.InlineKeyboardButton('🔧 Set User Limit', callback_data='set_user_limit'),
               types.InlineKeyboardButton('🗑️ Remove User Limit', callback_data='remove_user_limit'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Add Subscription', callback_data='add_subscription'),
               types.InlineKeyboardButton('➖ Remove Subscription', callback_data='remove_subscription'))
    markup.row(types.InlineKeyboardButton('🔍 Check Subscription', callback_data='check_subscription'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_admin_settings_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('📊 System Info', callback_data='system_info'),
               types.InlineKeyboardButton('📈 Bot Performance', callback_data='bot_performance'))
    markup.row(types.InlineKeyboardButton('🧹 Cleanup Files', callback_data='cleanup_files'),
               types.InlineKeyboardButton('📋 Installation Logs', callback_data='install_logs'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_wallet_management_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Add Balance', callback_data='admin_add_balance'),
               types.InlineKeyboardButton('➖ Deduct Balance', callback_data='admin_deduct_balance'))
    markup.row(types.InlineKeyboardButton('💰 Check Balance', callback_data='admin_check_balance'),
               types.InlineKeyboardButton('📊 Wallet Transactions', callback_data='admin_wallet_transactions'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_add_balance_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('💲 Pay via Zapupi', callback_data='add_balance_zapupi'))
    if binance_manual_settings.get('enabled'):
        markup.row(types.InlineKeyboardButton('🔶 Binance Manual', callback_data='add_balance_binance_manual'))
    markup.row(types.InlineKeyboardButton('🔙 Back', callback_data='wallet_menu'))
    return markup

def create_plan_management_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Create Plan Group', callback_data='admin_create_plan_group'),
               types.InlineKeyboardButton('📋 View Plan Groups', callback_data='admin_view_plan_groups'))
    markup.row(types.InlineKeyboardButton('✏️ Edit Plan Group', callback_data='admin_edit_plan_group'),
               types.InlineKeyboardButton('🗑 Delete Plan Group', callback_data='admin_delete_plan_group'))
    markup.row(types.InlineKeyboardButton('➕ Add Price', callback_data='admin_add_plan_price'),
               types.InlineKeyboardButton('📋 View Prices', callback_data='admin_view_plan_prices'))
    markup.row(types.InlineKeyboardButton('✏️ Edit Price', callback_data='admin_edit_plan_price'),
               types.InlineKeyboardButton('🗑 Delete Price', callback_data='admin_delete_plan_price'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_payment_settings_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('💲 Zapupi Settings', callback_data='admin_zapupi_settings'))
    markup.row(types.InlineKeyboardButton('🔶 Binance Manual Settings', callback_data='admin_binance_manual_settings'))
    markup.row(types.InlineKeyboardButton('📊 Transactions', callback_data='admin_transactions'),
               types.InlineKeyboardButton('📈 Revenue', callback_data='admin_revenue'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_binance_manual_settings_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Set Address', callback_data='binance_manual_set_address'),
               types.InlineKeyboardButton('🔄 Toggle Enable', callback_data='binance_manual_toggle'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Payment Settings', callback_data='admin_payment_settings'))
    return markup

def create_manage_templates_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Add Template', callback_data='admin_add_template'),
               types.InlineKeyboardButton('📋 List Templates', callback_data='admin_list_templates'))
    markup.row(types.InlineKeyboardButton('✏️ Edit Template', callback_data='admin_edit_template'),
               types.InlineKeyboardButton('🗑 Delete Template', callback_data='admin_delete_template'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_pending_payments_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('📋 View Pending', callback_data='view_pending_payments'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

# --- Security Bypass Functions ---
def create_security_bypass_request(user_id, file_name, file_path, reason):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''INSERT INTO security_bypass_requests (user_id, file_name, file_path, reason, status)
                 VALUES (?, ?, ?, ?, 'pending')''', (user_id, file_name, file_path, reason))
    req_id = c.lastrowid
    conn.commit()
    conn.close()
    security_bypass_requests[req_id] = {
        'id': req_id,
        'user_id': user_id,
        'file_name': file_name,
        'file_path': file_path,
        'reason': reason,
        'status': 'pending'
    }
    for admin in admin_ids:
        try:
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_bypass_{req_id}"),
                       types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_bypass_{req_id}"))
            bot.send_message(admin, f"🔐 Security Bypass Request #{req_id}\nUser: {user_id}\nFile: {file_name}\nReason: {reason}", reply_markup=markup)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin}: {e}")
    return req_id

def approve_bypass_request(req_id, admin_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT user_id, file_name, file_path FROM security_bypass_requests WHERE id = ?', (req_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Request not found"
    user_id, file_name, file_path = row
    c.execute('UPDATE security_bypass_requests SET status = "approved", resolved_at = datetime("now"), resolved_by = ? WHERE id = ?', (admin_id, req_id))
    conn.commit()
    conn.close()
    if req_id in security_bypass_requests:
        del security_bypass_requests[req_id]
    user_folder = get_user_folder(user_id)
    file_type = os.path.splitext(file_name)[1][1:]
    dest_path = os.path.join(user_folder, file_name)
    if os.path.exists(dest_path):
        os.remove(dest_path)
    shutil.move(file_path, dest_path)
    save_user_file(user_id, file_name, file_type)
    if file_type == 'py':
        threading.Thread(target=run_script, args=(dest_path, user_id, user_folder, file_name, None, 1, True)).start()
    elif file_type == 'js':
        threading.Thread(target=run_js_script, args=(dest_path, user_id, user_folder, file_name, None, 1, True)).start()
    try:
        bot.send_message(user_id, f"✅ Your file '{file_name}' has been approved by admin and is now running.")
    except:
        pass
    return True, "Approved and started"

def reject_bypass_request(req_id, admin_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT user_id, file_name FROM security_bypass_requests WHERE id = ?', (req_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Request not found"
    user_id, file_name = row
    c.execute('UPDATE security_bypass_requests SET status = "rejected", resolved_at = datetime("now"), resolved_by = ? WHERE id = ?', (admin_id, req_id))
    conn.commit()
    conn.close()
    if req_id in security_bypass_requests:
        del security_bypass_requests[req_id]
    user_folder = get_user_folder(user_id)
    file_path = os.path.join(user_folder, file_name)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except:
            pass
    try:
        bot.send_message(user_id, f"❌ Your file '{file_name}' was rejected by admin due to security concerns.")
    except:
        pass
    return True, "Rejected and deleted"

# --- File handling (modified) ---
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file:
            new_file.write(downloaded_file_content)
        is_safe, security_msg = scan_zip_security(zip_path)
        if not is_safe:
            bypass_dir = os.path.join(IROTECH_DIR, 'pending_bypass')
            os.makedirs(bypass_dir, exist_ok=True)
            import hashlib
            zip_hash = hashlib.md5(downloaded_file_content).hexdigest()[:8]
            pending_zip_path = os.path.join(bypass_dir, f"{user_id}_{zip_hash}_{file_name_zip}")
            shutil.copy(zip_path, pending_zip_path)
            req_id = create_security_bypass_request(user_id, file_name_zip, pending_zip_path, security_msg)
            bot.reply_to(message, f"⚠️ Your zip file contains potentially dangerous code. It has been sent for admin approval. You'll be notified once approved or rejected.\nRequest ID: {req_id}")
            return
        process_zip_file(zip_path, user_id, user_folder, file_name_zip, message, temp_dir)
    except zipfile.BadZipFile as e:
        logger.error(f"Bad zip file from {user_id}: {e}")
        bot.reply_to(message, f"❌ Error: Invalid/corrupted ZIP. {e}")
    except Exception as e:
        logger.error(f"❌ Error processing zip for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing zip: {str(e)}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.error(f"Failed to clean temp dir {temp_dir}: {e}", exc_info=True)

def process_zip_file(zip_path, user_id, user_folder, file_name_zip, message, temp_dir=None, allow_bypass=False):
    cleanup_temp = False
    if temp_dir is None:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        cleanup_temp = True
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"Zip has unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)
        extracted_items = os.listdir(temp_dir)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = 'requirements.txt' if 'requirements.txt' in extracted_items else None
        pkg_json = 'package.json' if 'package.json' in extracted_items else None
        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            bot.reply_to(message, f"🔄 Installing Python deps from `{req_file}`...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Python deps from `{req_file}` installed.")
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ Failed to install Python deps from `{req_file}`.\nLog:\n```\n{e.stderr or e.stdout}\n```"
                if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
                bot.reply_to(message, error_msg, parse_mode='Markdown')
                return
            except Exception as e:
                bot.reply_to(message, f"❌ Unexpected error installing Python deps: {e}")
                return
        if pkg_json:
            bot.reply_to(message, f"🔄 Installing Node deps from `{pkg_json}`...")
            try:
                command = ['npm', 'install']
                result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=temp_dir, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Node deps from `{pkg_json}` installed.")
            except (FileNotFoundError, subprocess.CalledProcessError) as e:
                if isinstance(e, FileNotFoundError):
                    bot.reply_to(message, "❌ 'npm' not found. Cannot install Node deps.")
                    return
                error_msg = f"❌ Failed to install Node deps from `{pkg_json}`.\nLog:\n```\n{e.stderr or e.stdout}\n```"
                if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
                bot.reply_to(message, error_msg, parse_mode='Markdown')
                return
            except Exception as e:
                bot.reply_to(message, f"❌ Unexpected error installing Node deps: {e}")
                return
        main_script_name = None
        file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']
        preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files:
                main_script_name = p
                file_type = 'py'
                break
        if not main_script_name:
            for p in preferred_js:
                if p in js_files:
                    main_script_name = p
                    file_type = 'js'
                    break
        if not main_script_name:
            if py_files:
                main_script_name = py_files[0]
                file_type = 'py'
            elif js_files:
                main_script_name = js_files[0]
                file_type = 'js'
        if not main_script_name:
            bot.reply_to(message, "❌ No `.py` or `.js` script found in archive!")
            return
        for item_name in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path):
                shutil.rmtree(dest_path)
            elif os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(src_path, dest_path)
        save_user_file(user_id, main_script_name, file_type)
        main_script_path = os.path.join(user_folder, main_script_name)
        bot.reply_to(message, f"✅ Files extracted. Starting main script: `{main_script_name}`...", parse_mode='Markdown')
        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message, 1, allow_bypass)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message, 1, allow_bypass)).start()
    except Exception as e:
        logger.error(f"Error processing zip file: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing zip: {str(e)}")
    finally:
        if cleanup_temp and temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.error(f"Failed to clean temp dir {temp_dir}: {e}", exc_info=True)

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message, allow_bypass=False):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message, 1, allow_bypass)).start()
    except Exception as e:
        logger.error(f"❌ Error processing JS file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing JS file: {str(e)}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message, allow_bypass=False):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message, 1, allow_bypass)).start()
    except Exception as e:
        logger.error(f"❌ Error processing Python file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing Python file: {str(e)}")

# --- run_script and run_js_script (modified) ---
def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1, allow_bypass=False):
    max_attempts = 2
    if attempt > max_attempts:
        if message_obj_for_reply:
            bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        else:
            chat_id = None
            script_key = f"{script_owner_id}_{file_name}"
            if script_key in bot_scripts:
                chat_id = bot_scripts[script_key].get('chat_id')
            if not chat_id:
                logger.error(f"Cannot send message for {script_key}: no chat_id")
            else:
                bot.send_message(chat_id, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        return
    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run Python script: {script_path} (Key: {script_key}) for user {script_owner_id}")
    try:
        if not os.path.exists(script_path):
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, f"❌ Error: Script '{file_name}' not found at '{script_path}'!")
            logger.error(f"Script not found: {script_path} for user {script_owner_id}")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return
        if attempt == 1:
            check_command = [sys.executable, script_path]
            logger.info(f"Running Python pre-check: {' '.join(check_command)}")
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        logger.info(f"Detected missing Python module: {module_name}")
                        if message_obj_for_reply:
                            success, _ = attempt_install_pip(module_name, message_obj_for_reply)
                            if success:
                                logger.info(f"Install OK for {module_name}. Retrying run_script...")
                                bot.reply_to(message_obj_for_reply, f"🔄 Install successful. Retrying '{file_name}'...")
                                time.sleep(2)
                                threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1, allow_bypass)).start()
                                return
                            else:
                                bot.reply_to(message_obj_for_reply, f"❌ Install failed. Cannot run '{file_name}'.")
                                return
                        else:
                            chat_id = None
                            if script_key in bot_scripts:
                                chat_id = bot_scripts[script_key].get('chat_id')
                            if chat_id:
                                bot.send_message(chat_id, f"🔄 Missing module '{module_name}' detected. Please install it manually using /manualinstall.")
                            return
                    else:
                        error_summary = stderr[:500]
                        if message_obj_for_reply:
                            bot.reply_to(message_obj_for_reply, f"❌ Error in script pre-check for '{file_name}':\n```\n{error_summary}\n```\nFix the script.", parse_mode='Markdown')
                        else:
                            chat_id = None
                            if script_key in bot_scripts:
                                chat_id = bot_scripts[script_key].get('chat_id')
                            if chat_id:
                                bot.send_message(chat_id, f"❌ Error in script pre-check for '{file_name}':\n```\n{error_summary}\n```\nFix the script.", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                logger.info("Python Pre-check timed out (>5s), imports likely OK. Killing check process.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                logger.error(f"Python interpreter not found: {sys.executable}")
                if message_obj_for_reply:
                    bot.reply_to(message_obj_for_reply, f"❌ Error: Python interpreter '{sys.executable}' not found.")
                else:
                    chat_id = None
                    if script_key in bot_scripts:
                        chat_id = bot_scripts[script_key].get('chat_id')
                    if chat_id:
                        bot.send_message(chat_id, f"❌ Error: Python interpreter '{sys.executable}' not found.")
                return
            except Exception as e:
                logger.error(f"Error in Python pre-check for {script_key}: {e}", exc_info=True)
                if message_obj_for_reply:
                    bot.reply_to(message_obj_for_reply, f"❌ Unexpected error in script pre-check for '{file_name}': {e}")
                else:
                    chat_id = None
                    if script_key in bot_scripts:
                        chat_id = bot_scripts[script_key].get('chat_id')
                    if chat_id:
                        bot.send_message(chat_id, f"❌ Unexpected error in script pre-check for '{file_name}': {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    logger.warning(f"Python Check process {check_proc.pid} still running. Killing.")
                    check_proc.kill()
                    check_proc.communicate()
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to open log file '{log_file_path}' for {script_key}: {e}", exc_info=True)
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file '{log_file_path}': {e}")
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, f"❌ Failed to open log file '{log_file_path}': {e}")
            return
        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                [sys.executable, script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            logger.info(f"Started Python process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id if message_obj_for_reply else None,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'py', 'script_key': script_key,
                'allow_bypass': allow_bypass
            }
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, f"✅ Python script '{file_name}' started! (PID: {process.pid}) (For User: {script_owner_id})")
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, f"✅ Python script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            logger.error(f"Python interpreter {sys.executable} not found for long run {script_key}")
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, f"❌ Error: Python interpreter '{sys.executable}' not found.")
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, f"❌ Error: Python interpreter '{sys.executable}' not found.")
            if log_file and not log_file.closed:
                log_file.close()
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            error_msg = f"❌ Error starting Python script '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, error_msg)
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, error_msg)
            if process and process.poll() is None:
                logger.warning(f"Killing potentially started Python process {process.pid} for {script_key}")
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ Unexpected error running Python script '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        if message_obj_for_reply:
            bot.reply_to(message_obj_for_reply, error_msg)
        else:
            chat_id = None
            if script_key in bot_scripts:
                chat_id = bot_scripts[script_key].get('chat_id')
            if chat_id:
                bot.send_message(chat_id, error_msg)
        if script_key in bot_scripts:
            logger.warning(f"Cleaning up {script_key} due to error in run_script.")
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1, allow_bypass=False):
    max_attempts = 2
    if attempt > max_attempts:
        if message_obj_for_reply:
            bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        else:
            script_key = f"{script_owner_id}_{file_name}"
            chat_id = None
            if script_key in bot_scripts:
                chat_id = bot_scripts[script_key].get('chat_id')
            if chat_id:
                bot.send_message(chat_id, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        return
    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run JS script: {script_path} (Key: {script_key}) for user {script_owner_id}")
    try:
        if not os.path.exists(script_path):
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, f"❌ Error: Script '{file_name}' not found at '{script_path}'!")
            logger.error(f"JS Script not found: {script_path} for user {script_owner_id}")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return
        if attempt == 1:
            check_command = ['node', script_path]
            logger.info(f"Running JS pre-check: {' '.join(check_command)}")
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            logger.info(f"Detected missing Node module: {module_name}")
                            if message_obj_for_reply:
                                success, _ = attempt_install_npm(module_name, user_folder, message_obj_for_reply)
                                if success:
                                    logger.info(f"NPM Install OK for {module_name}. Retrying run_js_script...")
                                    bot.reply_to(message_obj_for_reply, f"🔄 NPM Install successful. Retrying '{file_name}'...")
                                    time.sleep(2)
                                    threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1, allow_bypass)).start()
                                    return
                                else:
                                    bot.reply_to(message_obj_for_reply, f"❌ NPM Install failed. Cannot run '{file_name}'.")
                                    return
                            else:
                                chat_id = None
                                if script_key in bot_scripts:
                                    chat_id = bot_scripts[script_key].get('chat_id')
                                if chat_id:
                                    bot.send_message(chat_id, f"🔄 Missing Node module '{module_name}'. Please install manually via /manualinstall.")
                                return
                    error_summary = stderr[:500]
                    if message_obj_for_reply:
                        bot.reply_to(message_obj_for_reply, f"❌ Error in JS script pre-check for '{file_name}':\n```\n{error_summary}\n```\nFix script or install manually.", parse_mode='Markdown')
                    else:
                        chat_id = None
                        if script_key in bot_scripts:
                            chat_id = bot_scripts[script_key].get('chat_id')
                        if chat_id:
                            bot.send_message(chat_id, f"❌ Error in JS script pre-check for '{file_name}':\n```\n{error_summary}\n```\nFix script or install manually.", parse_mode='Markdown')
                    return
            except subprocess.TimeoutExpired:
                logger.info("JS Pre-check timed out (>5s), imports likely OK. Killing check process.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                error_msg = "❌ Error: 'node' not found. Ensure Node.js is installed for JS files."
                logger.error(error_msg)
                if message_obj_for_reply:
                    bot.reply_to(message_obj_for_reply, error_msg)
                else:
                    chat_id = None
                    if script_key in bot_scripts:
                        chat_id = bot_scripts[script_key].get('chat_id')
                    if chat_id:
                        bot.send_message(chat_id, error_msg)
                return
            except Exception as e:
                logger.error(f"Error in JS pre-check for {script_key}: {e}", exc_info=True)
                if message_obj_for_reply:
                    bot.reply_to(message_obj_for_reply, f"❌ Unexpected error in JS pre-check for '{file_name}': {e}")
                else:
                    chat_id = None
                    if script_key in bot_scripts:
                        chat_id = bot_scripts[script_key].get('chat_id')
                    if chat_id:
                        bot.send_message(chat_id, f"❌ Unexpected error in JS pre-check for '{file_name}': {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    logger.warning(f"JS Check process {check_proc.pid} still running. Killing.")
                    check_proc.kill()
                    check_proc.communicate()
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to open log file '{log_file_path}' for JS script {script_key}: {e}", exc_info=True)
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file '{log_file_path}': {e}")
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, f"❌ Failed to open log file '{log_file_path}': {e}")
            return
        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                ['node', script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            logger.info(f"Started JS process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id if message_obj_for_reply else None,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'js', 'script_key': script_key,
                'allow_bypass': allow_bypass
            }
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, f"✅ JS script '{file_name}' started! (PID: {process.pid}) (For User: {script_owner_id})")
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, f"✅ JS script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            error_msg = "❌ Error: 'node' not found for long run. Ensure Node.js is installed."
            logger.error(error_msg)
            if log_file and not log_file.closed:
                log_file.close()
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, error_msg)
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, error_msg)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            error_msg = f"❌ Error starting JS script '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            if message_obj_for_reply:
                bot.reply_to(message_obj_for_reply, error_msg)
            else:
                chat_id = None
                if script_key in bot_scripts:
                    chat_id = bot_scripts[script_key].get('chat_id')
                if chat_id:
                    bot.send_message(chat_id, error_msg)
            if process and process.poll() is None:
                logger.warning(f"Killing potentially started JS process {process.pid} for {script_key}")
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ Unexpected error running JS script '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        if message_obj_for_reply:
            bot.reply_to(message_obj_for_reply, error_msg)
        else:
            chat_id = None
            if script_key in bot_scripts:
                chat_id = bot_scripts[script_key].get('chat_id')
            if chat_id:
                bot.send_message(chat_id, error_msg)
        if script_key in bot_scripts:
            logger.warning(f"Cleaning up {script_key} due to error in run_js_script.")
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

# --- Core logic functions ---
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    logger.info(f"Welcome request from user_id: {user_id}")

    if is_user_banned(user_id):
        bot.send_message(chat_id, "❌ You are banned from using this bot.")
        return

    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT phone FROM active_users WHERE user_id = ?', (user_id,))
    phone_row = c.fetchone()
    conn.close()
    phone = phone_row[0] if phone_row and phone_row[0] else None

    if not phone:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button = types.KeyboardButton("📱 Share Contact", request_contact=True)
        markup.add(button)
        bot.send_message(chat_id, "📱 **Please share your contact to continue.**\nTap the button below.", reply_markup=markup, parse_mode='Markdown')
        bot.register_next_step_handler(message, process_contact_for_welcome)
        return

    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.send_message(chat_id, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return

    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked by admin. Try later.")
        return

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            owner_notification = (f"🎉 New user!\n👤 Name: {user_name}\n🆔 ID: `{user_id}`\n📱 Phone: {phone}")
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"⚠️ Failed to notify owner about new user {user_id}: {e}")

    expiry_info = ""
    limit_str = "Unlimited"
    ram_str = "N/A"

    active_plan = get_user_active_plan(user_id)
    if active_plan:
        expiry_date = active_plan['expiry_date']
        days_left = (expiry_date - datetime.now()).days
        group = get_plan_group(active_plan['plan_id'])
        group_name = group['name'] if group else f"Plan {active_plan['plan_id']}"
        user_status = f"⭐ Premium ({group_name})"
        expiry_info = f"\n⏳ Expires in: {days_left} days"
        limit_str = str(active_plan['bot_limit'])
        ram_str = f"{active_plan['ram_limit']} MiB"
    else:
        trial_expiry = get_user_trial(user_id)
        if trial_expiry:
            remaining = (trial_expiry - datetime.now()).seconds // 60
            user_status = f"🎁 Trial (1 hour) - {remaining} min left"
            limit_str = str(TRIAL_BOT_LIMIT)
            ram_str = "128 MiB"
        else:
            if user_id == OWNER_ID:
                user_status = "👑 Owner"
            elif user_id in admin_ids:
                user_status = "🛡️ Admin"
            elif user_id in user_subscriptions:
                expiry_date = user_subscriptions[user_id].get('expiry')
                if expiry_date and expiry_date > datetime.now():
                    user_status = "⭐ Premium (Legacy)"
                    days_left = (expiry_date - datetime.now()).days
                    expiry_info = f"\n⏳ Subscription expires in: {days_left} days"
                else:
                    user_status = "🆓 Free User (Expired Sub)"
                    remove_subscription_db(user_id)
            else:
                user_status = "🆓 Free User"
            limit = get_user_file_limit(user_id)
            limit_str = str(limit) if limit != float('inf') else "Unlimited"
            ram_str = str(get_user_ram_limit(user_id)) + " MiB"

    current_files = get_user_file_count(user_id)
    wallet_balance = get_wallet_balance(user_id)

    welcome_msg_text = (f"〽️ Welcome, {user_name}!\n\n🆔 Your User ID: `{user_id}`\n"
                        f"📱 Phone: {phone}\n"
                        f"🔰 Your Status: {user_status}{expiry_info}\n"
                        f"📁 Files Uploaded: {current_files} / {limit_str}\n"
                        f"🧠 RAM Limit: {ram_str}\n"
                        f"💰 Balance: ₹{wallet_balance:.2f}\n\n"
                        f"🤖 Host & run Python (`.py`) or JS (`.js`) scripts.\n"
                        f"   Upload single scripts or `.zip` archives.\n"
                        f"📦 Manual module installation available\n"
                        f"💳 To buy a plan, use /plans or the button below.\n"
                        f"🎁 To get a 1-hour trial, use /trial.\n"
                        f"💵 To add balance, use Balance button.\n"
                        f"🤖 Check available bots with 'Available Bots' button.\n\n"
                        f"👇 Use buttons or type commands.")

    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error sending welcome to {user_id}: {e}", exc_info=True)

def process_contact_for_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    if message.contact:
        phone = message.contact.phone_number
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('UPDATE active_users SET phone = ? WHERE user_id = ?', (phone, user_id))
        if c.rowcount == 0:
            join_date = datetime.now().isoformat()
            c.execute('INSERT OR REPLACE INTO active_users (user_id, join_date, last_seen, phone) VALUES (?, ?, ?, ?)',
                      (user_id, join_date, join_date, phone))
        conn.commit()
        conn.close()
        logger.info(f"Phone saved for user {user_id}: {phone}")
        bot.reply_to(message, "✅ Contact received. Welcome!")
        _logic_send_welcome(message)
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button = types.KeyboardButton("📱 Share Contact", request_contact=True)
        markup.add(button)
        bot.send_message(chat_id, "⚠️ Please share your contact using the button below.", reply_markup=markup)
        bot.register_next_step_handler(message, process_contact_for_welcome)

def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=f'https://t.me/{UPDATE_CHANNEL.replace("@", "")}'))
    bot.reply_to(message, "Visit our Updates Channel:", reply_markup=markup)

def _logic_upload_file(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked by admin, cannot accept files.")
        return
    file_limit = get_user_file_limit(user_id)
    if file_limit <= 0:
        bot.reply_to(message, "🚫 You have no upload quota. Please purchase a plan or start a trial using /trial.")
        return
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{limit_str}) reached. Delete files first.")
        return
    bot.reply_to(message, "📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.")

def _logic_check_files(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 Your files:\n\n(No files uploaded yet)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        callback_data = f"file_{user_id}_{file_name}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
    bot.reply_to(message, "📂 Your files:\nClick to manage.", reply_markup=markup, parse_mode='Markdown')

def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "🏃 Testing speed...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID:
            user_level = "👑 Owner"
        elif user_id in admin_ids:
            user_level = "🛡️ Admin"
        elif get_user_active_plan(user_id):
            user_level = "⭐ Premium"
        elif get_user_trial(user_id):
            user_level = "🎁 Trial"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            user_level = "⭐ Premium (Legacy)"
        else:
            user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     f"👤 Your Level: {user_level}\n"
                     f"💰 Balance: ₹{get_wallet_balance(user_id):.2f}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Error during speed test (cmd): {e}", exc_info=True)
        bot.edit_message_text("❌ Error during speed test.", chat_id, wait_msg.message_id)

def _logic_balance(message):
    user_id = message.from_user.id
    balance = get_wallet_balance(user_id)
    bot.reply_to(message, f"💰 Your balance: ₹{balance:.2f}")

def _logic_manual_install(message):
    manual_install_module_init(message)

def _logic_help(message):
    help_text = """
🤖 **XM HOSTING BOT Help Guide**

**📌 Basic Commands:**
• /start - Start the bot
• /help - Show this help message
• /status - Show bot statistics
• /plans - View available subscription plans
• /buy - Purchase a plan
• /myplan - Check your current subscription
• /trial - Activate 1-hour free trial (1 bot, once per month)
• /balance - Check your wallet balance
• /addbalance - Add balance to your wallet (via Zapupi/Binance Manual)
• /availablebots - View and purchase template bots

**📁 File Management:**
• Upload `.py` or `.js` files directly
• Upload `.zip` archives with multiple files
• Auto-installs dependencies from `requirements.txt` or `package.json`
• If your code contains blocked commands, it will be sent for admin approval

**📦 Module Installation:**
• Auto-install missing Python/Node modules
• Manual install via "📦 Manual Install" button
• Admin can install modules for users

**💳 Subscription & Payments:**
• View available plans with /plans
• Purchase a plan with /buy
• Pay via Zapupi, Binance Manual, or **Wallet Balance**
• Automatic activation after payment (webhook + manual verify)
• Check your subscription with /myplan
• Auto-renewal from wallet when plan expires
• **Grace period:** After plan expiry, your files will be automatically deleted after 14 days. You will receive reminders at 10 and 5 days before deletion.

**💰 Wallet System:**
• Check balance with /balance or via Balance menu
• Add balance via Balance menu (minimum ₹10)
• Auto-renewal: When your plan expires, funds are automatically deducted from wallet
• Admin can add/deduct balance
• Transaction history available

**🎁 Trial:**
• Use /trial to get 1 hour free (1 bot)
• Only once per 30 days
• After 1 hour, your files will be deleted

**🤖 Template Bots:**
• Browse available pre-built bots with "Available Bots" button
• Each bot has a price and demo video
• Purchase a bot, provide required credentials (token, admin ID, etc.)
• Your bot is automatically generated and started
• **IMPORTANT:** Once you provide credentials and deploy, you **cannot** edit them later. If you need to change any parameter, you must purchase a new template (no refunds).

**👑 Admin Features:**
• User management (ban/unban)
• Set custom file limits
• Manage mandatory channels
• Broadcast messages
• Run all user scripts
• Create, edit, delete subscription plan groups and prices (with RAM limits)
• Configure payment gateways (Zapupi, Binance manual)
• View transactions and revenue
• Wallet management (add/deduct balance, view transactions)
• **Template Management**: Add/Edit/Delete template bots, set price, demo video, required parameters
• **Security Bypass**: Approve or reject scripts that contain blocked commands
• **Advanced Edit**: Edit plans and templates with user‑friendly inline buttons

⚙️ **Tips:**
1. Make sure your scripts don't contain dangerous commands (auto-blocked)
2. Join all required channels
3. Contact owner for support

**Support:** {support}
**Updates:** {updates}
""".format(support=SUPPORT_USERNAME, updates=UPDATE_CHANNEL)
    bot.reply_to(message, help_text, parse_mode='Markdown')

def _logic_subscriptions_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "💳 Subscription Management\nUse inline buttons from /start or admin command menu.", reply_markup=create_subscription_menu())

def _logic_statistics(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    # Show only user's own stats
    user_files_list = user_files.get(user_id, [])
    total_files = len(user_files_list)
    running_bots = 0
    for file_name, _ in user_files_list:
        if is_bot_running(user_id, file_name):
            running_bots += 1
    stats_msg = (f"📊 **Your Statistics**\n\n"
                 f"📁 Total Files: {total_files}\n"
                 f"🟢 Running Bots: {running_bots}\n"
                 f"💰 Balance: ₹{get_wallet_balance(user_id):.2f}\n")
    active_plan = get_user_active_plan(user_id)
    if active_plan:
        group = get_plan_group(active_plan['plan_id'])
        group_name = group['name'] if group else "Plan"
        stats_msg += f"📅 Active Plan: {group_name} (expires {active_plan['expiry_date'].strftime('%Y-%m-%d')})\n"
    bot.reply_to(message, stats_msg, parse_mode='Markdown')

def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    msg = bot.reply_to(message, "📢 Send message to broadcast to all active users.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def _logic_toggle_lock_bot(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    global bot_locked
    bot_locked = not bot_locked
    status = "locked" if bot_locked else "unlocked"
    logger.warning(f"Bot {status} by Admin {message.from_user.id} via command/button.")
    bot.reply_to(message, f"🔒 Bot has been {status}.")

def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "👑 Admin Panel\nManage admins. Use inline buttons from /start or admin menu.",
                 reply_markup=create_admin_panel())

def _logic_user_management(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "👥 User Management\nManage users, set limits, ban/unban.",
                 reply_markup=create_user_management_menu())

def _logic_admin_settings(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "⚙️ Admin Settings\nSystem information and management.",
                 reply_markup=create_admin_settings_menu())

def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.chat.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.message.chat.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(admin_chat_id, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call.message
    else:
        logger.error("Invalid argument for _logic_run_all_scripts")
        return
    if admin_user_id not in admin_ids:
        reply_func("⚠️ Admin permissions required.")
        return
    reply_func("⏳ Starting process to run all user scripts. This may take a while...")
    started_count = 0
    attempted_users = 0
    skipped_files = 0
    error_files_details = []
    all_user_files_snapshot = dict(user_files)
    for target_user_id, files_for_user in all_user_files_snapshot.items():
        if not files_for_user:
            continue
        attempted_users += 1
        user_folder = get_user_folder(target_user_id)
        for file_name, file_type in files_for_user:
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner, 1, False)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner, 1, False)).start()
                            started_count += 1
                        else:
                            logger.warning(f"Unknown file type '{file_type}' for {file_name} (user {target_user_id}). Skipping.")
                            error_files_details.append(f"`{file_name}` (User {target_user_id}) - Unknown type")
                            skipped_files += 1
                        time.sleep(0.7)
                    except Exception as e:
                        logger.error(f"Error queueing start for '{file_name}' (user {target_user_id}): {e}")
                        error_files_details.append(f"`{file_name}` (User {target_user_id}) - Start error")
                        skipped_files += 1
                else:
                    logger.warning(f"File '{file_name}' for user {target_user_id} not found at '{file_path}'. Skipping.")
                    error_files_details.append(f"`{file_name}` (User {target_user_id}) - File not found")
                    skipped_files += 1
    summary_msg = (f"✅ All Users' Scripts - Processing Complete:\n\n"
                   f"▶️ Attempted to start: {started_count} scripts.\n"
                   f"👥 Users processed: {attempted_users}.\n")
    if skipped_files > 0:
        summary_msg += f"⚠️ Skipped/Error files: {skipped_files}\n"
        if error_files_details:
            summary_msg += "Details (first 5):\n" + "\n".join([f"  - {err}" for err in error_files_details[:5]])
            if len(error_files_details) > 5:
                summary_msg += "\n  ... and more (check logs)."
    reply_func(summary_msg, parse_mode='Markdown')

def _logic_manage_mandatory_channels(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "📢 Manage Mandatory Channels\nUse the buttons below:", reply_markup=create_mandatory_channels_menu())

def _logic_admin_install(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    msg = bot.reply_to(message, "🛠️ Admin Module Installation\nSend user ID and module name (e.g., `12345678 requests`)\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_admin_install)

def process_admin_install(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Installation cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Format: `user_id module_name`\nExample: `12345678 requests`")
            return
        user_id = int(parts[0])
        module_name = ' '.join(parts[1:])
        if module_name.lower().startswith('npm:'):
            module_name = module_name[4:].strip()
            user_folder = get_user_folder(user_id)
            success, log = attempt_install_npm(module_name, user_folder, message, manual_request=True)
        else:
            success, log = attempt_install_pip(module_name, message, manual_request=True)
        if success:
            logger.info(f"Admin {admin_id} installed module {module_name} for user {user_id}")
            try:
                bot.send_message(user_id, f"📦 Admin installed module `{module_name}` for you.")
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid user ID. Must be a number.")
    except Exception as e:
        logger.error(f"Error in admin install: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['phone'])
def command_phone(message):
    bot.reply_to(message, "Please use the contact share button on start.")

def _logic_wallet_management(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "💰 Wallet Management\nManage user wallets.", reply_markup=create_wallet_management_menu())

def _logic_wallet_balance(message):
    user_id = message.from_user.id
    balance = get_wallet_balance(user_id)
    bot.reply_to(message, f"💰 Your balance: ₹{balance:.2f}")

def _logic_add_balance(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    msg = bot.reply_to(message, "💵 Enter amount to add (minimum ₹10):\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_add_balance_amount)

def process_add_balance_amount(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled.")
        return
    try:
        amount = float(message.text.strip())
        if amount < 10:
            bot.reply_to(message, "⚠️ Minimum amount is ₹10. Enter a larger amount or /cancel.")
            return
        pending_add_balance[user_id] = amount
        markup = create_add_balance_menu()
        bot.reply_to(message, f"💰 Amount: ₹{amount:.2f}\nChoose payment method:", reply_markup=markup)
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid amount. Enter a number (e.g., 100).")
        return

def initiate_add_balance_payment(user_id, amount, gateway, chat_id):
    order_id = generate_transaction_id()
    txn_db_id = create_transaction(user_id, amount, gateway, order_id, txn_type='balance')
    if gateway == 'zapupi':
        txn_id, payment_url = create_zapupi_order(user_id, amount, order_id, txn_type='balance')
        if not txn_id:
            bot.send_message(chat_id, f"❌ Failed to create Zapupi order: {payment_url}")
            return
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('UPDATE transactions SET payment_details = ? WHERE id = ?', (json.dumps({'gateway_txn': txn_id}), txn_db_id))
        conn.commit()
        conn.close()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Pay Now", url=payment_url))
        markup.add(types.InlineKeyboardButton("✅ I've Paid (Verify)", callback_data=f"verify_balance_zapupi_{order_id}"))
        try:
            qr = qrcode.QRCode(box_size=4, border=2)
            qr.add_data(payment_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            bio = BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            bot.send_photo(chat_id, photo=bio, caption=f"Scan QR or click below to pay ₹{amount:.2f}\nOrder ID: `{order_id}`", reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"QR generation error: {e}")
            bot.send_message(chat_id, f"🔗 Pay using link: {payment_url}\nOrder ID: `{order_id}`\nAfter payment, click 'I've Paid'.", reply_markup=markup, parse_mode='Markdown')
    elif gateway == 'binance_manual':
        address = binance_manual_settings.get('address', 'Not set')
        binance_id = binance_manual_settings.get('binance_id', 'Not set')
        trc_address = binance_manual_settings.get('trc_address', 'Not set')
        if not address:
            bot.send_message(chat_id, "❌ Binance manual payment is not configured by admin.")
            return
        markup = types.InlineKeyboardMarkup()
        if binance_id and binance_id != 'Not set':
            markup.add(types.InlineKeyboardButton("📋 Copy Binance ID", callback_data=f"copy_binance_id_{order_id}"))
        if trc_address and trc_address != 'Not set':
            markup.add(types.InlineKeyboardButton("📋 Copy TRC Address", callback_data=f"copy_trc_address_{order_id}"))
        markup.add(types.InlineKeyboardButton("✅ I've Paid (Submit TXID)", callback_data=f"submit_binance_manual_{order_id}"))
        text = f"💳 **Binance Manual Payment**\n\nSend ₹{amount:.2f} (≈ ${amount/EXCHANGE_RATE:.2f} USDT) to the following Binance address:\n`{address}`\n\n"
        if binance_id and binance_id != 'Not set':
            text += f"Binance ID: `{binance_id}`\n"
        if trc_address and trc_address != 'Not set':
            text += f"TRC Address: `{trc_address}`\n"
        text += "\nAfter payment, click the button below and provide the transaction ID and screenshot."
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, "❌ Unsupported gateway.")

def _logic_manage_plans(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "📋 Plan Management\nCreate, edit, delete plan groups and prices.", reply_markup=create_plan_management_menu())

def _logic_payment_settings(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "💲 Payment Settings\nConfigure payment gateways.", reply_markup=create_payment_settings_menu())

def _logic_admin_pending_payments(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    show_pending_payments(message.chat.id)

def show_pending_payments(chat_id):
    pending = get_pending_transactions()
    if not pending:
        bot.send_message(chat_id, "📋 No pending payments.")
        return
    text = "📋 **Pending Payments**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    for txn in pending:
        txn_id, user_id, plan_id, amount, transaction_id, gateway, txn_type = txn
        text += f"ID: {txn_id} | User: {user_id} | Gateway: {gateway} | Amount: ₹{amount} | Type: {txn_type}\n"
        markup.add(types.InlineKeyboardButton(f"Approve {txn_id}", callback_data=f"approve_payment_{txn_id}"),
                   types.InlineKeyboardButton(f"Reject {txn_id}", callback_data=f"reject_payment_{txn_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['trial'])
def command_trial(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    if get_user_active_plan(user_id):
        bot.reply_to(message, "✅ You already have an active paid plan. No trial needed.")
        return
    if get_user_trial(user_id):
        bot.reply_to(message, "⏳ You already have an active trial. Use /myplan to check expiry.")
        return
    can, msg = can_start_trial(user_id)
    if not can:
        bot.reply_to(message, f"❌ {msg}")
        return
    activate_trial(user_id)
    bot.reply_to(message, f"🎁 Your 1-hour trial has been activated!\nYou can upload up to {TRIAL_BOT_LIMIT} bot.\nExpires in 1 hour. Use /myplan to check remaining time.")

@bot.message_handler(commands=['myplan'])
def command_myplan(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    plan = get_user_active_plan(user_id)
    if plan:
        expiry = plan['expiry_date']
        days_left = (expiry - datetime.now()).days
        group = get_plan_group(plan['plan_id'])
        group_name = group['name'] if group else f"Plan {plan['plan_id']}"
        text = f"📅 **Your Subscription:**\n\nPlan: {group_name}\nBot Limit: {plan['bot_limit']}\nRAM Limit: {plan['ram_limit']} MiB\nExpires: {expiry.strftime('%Y-%m-%d %H:%M:%S')}\nDays left: {days_left}\n\nUse /plans to renew or upgrade."
        bot.reply_to(message, text, parse_mode='Markdown')
        return
    trial = get_user_trial(user_id)
    if trial:
        remaining = (trial - datetime.now()).seconds // 60
        text = f"🎁 **Trial Active**\n\nBot Limit: {TRIAL_BOT_LIMIT}\nRAM Limit: 128 MiB\nTime remaining: {remaining} minutes\nExpires at: {trial.strftime('%Y-%m-%d %H:%M:%S')}"
        bot.reply_to(message, text, parse_mode='Markdown')
        return
    bot.reply_to(message, "❌ You don't have an active subscription or trial.\nUse /trial to start a free trial or /plans to purchase.")

@bot.message_handler(commands=['balance'])
def command_balance(message):
    _logic_wallet_balance(message)

@bot.message_handler(commands=['addbalance'])
def command_add_balance(message):
    _logic_add_balance(message)

@bot.message_handler(commands=['plans'])
def command_plans(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    show_plans_to_user(message.chat.id, user_id)

@bot.message_handler(commands=['buy'])
def command_buy(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    show_plans_to_user(message.chat.id, user_id)

@bot.message_handler(commands=['manageplans'])
def command_manageplans(message):
    _logic_manage_plans(message)

@bot.message_handler(commands=['paymentsettings'])
def command_paymentsettings(message):
    _logic_payment_settings(message)

@bot.message_handler(commands=['walletmanagement'])
def command_walletmanagement(message):
    _logic_wallet_management(message)

@bot.message_handler(commands=['adminpending'])
def command_admin_pending(message):
    _logic_admin_pending_payments(message)

@bot.message_handler(commands=['availablebots'])
def command_available_bots(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    show_available_templates(message.chat.id, user_id)

@bot.message_handler(commands=['managetemplates'])
def command_manage_templates(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    bot.reply_to(message, "📦 Manage Templates\nUse buttons below:", reply_markup=create_manage_templates_menu())

@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message):
    if message.text == '/help':
        _logic_help(message)
    else:
        _logic_send_welcome(message)

@bot.message_handler(commands=['status'])
def command_show_status(message):
    _logic_statistics(message)

BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "💰 Balance": _logic_balance,
    "📊 Statistics": _logic_statistics,
    "💳 Subscriptions": _logic_subscriptions_panel,
    "📢 Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot,
    "🟢 Running All Code": _logic_run_all_scripts,
    "👑 Admin Panel": _logic_admin_panel,
    "📢 Channel Add": _logic_manage_mandatory_channels,
    "👥 User Management": _logic_user_management,
    "🛠️ Manual Install": _logic_manual_install,
    "⚙️ Settings": _logic_admin_settings,
    "📦 Manual Install": _logic_manual_install,
    "🆘 Help": _logic_help,
    "📋 View Plans": command_plans,
    "🛒 Purchase Plan": command_buy,
    "📅 My Subscription": command_myplan,
    "💲 Payment Settings": _logic_payment_settings,
    "📋 Plan Management": _logic_manage_plans,
    "🎁 Get Trial": command_trial,
    "💰 Wallet Management": _logic_wallet_management,
    "🤖 Available Bots": command_available_bots,
    "📦 Manage Templates": command_manage_templates,
    "📋 Pending Payments": _logic_admin_pending_payments,
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func:
        if message.text == "💰 Balance":
            user_id = message.from_user.id
            markup = create_wallet_menu(user_id)
            bot.reply_to(message, "💰 Balance Menu:", reply_markup=markup)
            return
        logic_func(message)
    else:
        logger.warning(f"Button text '{message.text}' matched but no logic func.")

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.from_user.id
    if message.contact:
        phone = message.contact.phone_number
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('UPDATE active_users SET phone = ? WHERE user_id = ?', (phone, user_id))
        if c.rowcount == 0:
            join_date = datetime.now().isoformat()
            c.execute('INSERT OR REPLACE INTO active_users (user_id, join_date, last_seen, phone) VALUES (?, ?, ?, ?)',
                      (user_id, join_date, join_date, phone))
        conn.commit()
        conn.close()
        bot.reply_to(message, "✅ Contact saved.")
    else:
        bot.reply_to(message, "Please share your contact using the button.")

@bot.message_handler(commands=['updateschannel'])
def command_updates_channel(message):
    _logic_updates_channel(message)
@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message):
    _logic_upload_file(message)
@bot.message_handler(commands=['checkfiles'])
def command_check_files(message):
    _logic_check_files(message)
@bot.message_handler(commands=['botspeed'])
def command_bot_speed(message):
    _logic_bot_speed(message)
@bot.message_handler(commands=['contactowner'])
def command_contact_owner(message):
    _logic_balance(message)
@bot.message_handler(commands=['subscriptions'])
def command_subscriptions(message):
    _logic_subscriptions_panel(message)
@bot.message_handler(commands=['statistics'])
def command_statistics(message):
    _logic_statistics(message)
@bot.message_handler(commands=['broadcast'])
def command_broadcast(message):
    _logic_broadcast_init(message)
@bot.message_handler(commands=['lockbot'])
def command_lock_bot(message):
    _logic_toggle_lock_bot(message)
@bot.message_handler(commands=['adminpanel'])
def command_admin_panel(message):
    _logic_admin_panel(message)
@bot.message_handler(commands=['runningallcode'])
def command_run_all_code(message):
    _logic_run_all_scripts(message)
@bot.message_handler(commands=['managechannels'])
def command_manage_channels(message):
    _logic_manage_mandatory_channels(message)
@bot.message_handler(commands=['usermanagement'])
def command_user_management(message):
    _logic_user_management(message)
@bot.message_handler(commands=['manualinstall'])
def command_manual_install(message):
    _logic_manual_install(message)
@bot.message_handler(commands=['admininstall'])
def command_admin_install(message):
    _logic_admin_install(message)

@bot.message_handler(commands=['ping'])
def ping(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    start_ping_time = time.time()
    msg = bot.reply_to(message, "Pong!")
    latency = round((time.time() - start_ping_time) * 1000, 2)
    bot.edit_message_text(f"Pong! Latency: {latency} ms", message.chat.id, msg.message_id)

@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.reply_to(message, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    doc = message.document
    logger.info(f"Doc from {user_id}: {doc.file_name} ({doc.mime_type}), Size: {doc.file_size}")
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked, cannot accept files.")
        return
    file_limit = get_user_file_limit(user_id)
    if file_limit <= 0:
        bot.reply_to(message, "🚫 You have no upload quota. Please purchase a plan or start a trial using /trial.")
        return
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{limit_str}) reached. Delete files via /checkfiles.")
        return
    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "⚠️ No file name. Ensure file has a name.")
        return
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Unsupported type! Only `.py`, `.js`, `.zip` allowed.")
        return
    max_file_size = 20 * 1024 * 1024
    if doc.file_size > max_file_size:
        bot.reply_to(message, f"⚠️ File too large (Max: {max_file_size // 1024 // 1024} MB).")
        return
    try:
        try:
            # Forward without parse_mode to avoid markdown errors
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT phone FROM active_users WHERE user_id = ?', (user_id,))
            phone_row = c.fetchone()
            conn.close()
            phone = phone_row[0] if phone_row and phone_row[0] else "Not set"
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)\n📱 Phone: {phone}", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to forward uploaded file to OWNER_ID {OWNER_ID}: {e}")
        download_wait_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", chat_id, download_wait_msg.message_id)
        logger.info(f"Downloaded {file_name} for user {user_id}")
        user_folder = get_user_folder(user_id)
        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            temp_file_path = os.path.join(user_folder, file_name)
            with open(temp_file_path, 'wb') as f:
                f.write(downloaded_file_content)
            is_safe, security_msg = check_code_security(temp_file_path, file_ext[1:])
            if not is_safe:
                req_id = create_security_bypass_request(user_id, file_name, temp_file_path, security_msg)
                bot.reply_to(message, f"⚠️ Your file contains potentially dangerous code. It has been sent for admin approval. You'll be notified once approved or rejected.\nRequest ID: {req_id}")
                return
            if file_ext == '.js':
                handle_js_file(temp_file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py':
                handle_py_file(temp_file_path, user_id, user_folder, file_name, message)
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"Telegram API Error handling file for {user_id}: {e}", exc_info=True)
        if "file is too big" in str(e).lower():
            bot.reply_to(message, f"❌ Telegram API Error: File too large to download (~20MB limit).")
        else:
            bot.reply_to(message, f"❌ Telegram API Error: {str(e)}. Try later.")
    except Exception as e:
        logger.error(f"❌ General error handling file for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Unexpected error: {str(e)}")

# --- Callback query handler ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    logger.info(f"Callback: User={user_id}, Data='{data}'")
    if is_user_banned(user_id) and data not in ['back_to_main', 'wallet_menu']:
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return
    if data not in ['check_subscription_status', 'back_to_main', 'manual_install', 'wallet_balance', 'add_balance', 'wallet_menu']:
        is_subscribed, not_joined = check_mandatory_subscription(user_id)
        if not is_subscribed and user_id not in admin_ids:
            subscription_message, markup = create_subscription_check_message(not_joined)
            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_text(subscription_message, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
            except:
                bot.send_message(call.message.chat.id, subscription_message, reply_markup=markup, parse_mode='Markdown')
            return
    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats', 'check_subscription_status', 'manual_install', 'wallet_balance', 'add_balance', 'wallet_menu']:
        bot.answer_callback_query(call.id, "⚠️ Bot locked by admin.", show_alert=True)
        return
    try:
        if data == 'upload':
            upload_callback(call)
        elif data == 'check_files':
            check_files_callback(call)
        elif data.startswith('file_'):
            file_control_callback(call)
        elif data.startswith('start_'):
            start_bot_callback(call)
        elif data.startswith('stop_'):
            stop_bot_callback(call)
        elif data.startswith('restart_'):
            restart_bot_callback(call)
        elif data.startswith('delete_'):
            delete_bot_callback(call)
        elif data.startswith('logs_'):
            logs_bot_callback(call)
        elif data == 'speed':
            speed_callback(call)
        elif data == 'back_to_main':
            back_to_main_callback(call)
        elif data.startswith('confirm_broadcast_'):
            handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast':
            handle_cancel_broadcast(call)
        elif data == 'manual_install':
            manual_install_callback(call)
        elif data == 'subscription':
            admin_required_callback(call, subscription_management_callback)
        elif data == 'stats':
            stats_callback(call)
        elif data == 'lock_bot':
            admin_required_callback(call, lock_bot_callback)
        elif data == 'unlock_bot':
            admin_required_callback(call, unlock_bot_callback)
        elif data == 'run_all_scripts':
            admin_required_callback(call, run_all_scripts_callback)
        elif data == 'broadcast':
            admin_required_callback(call, broadcast_init_callback)
        elif data == 'admin_panel':
            admin_required_callback(call, admin_panel_callback)
        elif data == 'add_admin':
            owner_required_callback(call, add_admin_init_callback)
        elif data == 'remove_admin':
            owner_required_callback(call, remove_admin_init_callback)
        elif data == 'list_admins':
            admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription':
            admin_required_callback(call, add_subscription_init_callback)
        elif data == 'remove_subscription':
            admin_required_callback(call, remove_subscription_init_callback)
        elif data == 'check_subscription':
            admin_required_callback(call, check_subscription_init_callback)
        elif data == 'user_management':
            admin_required_callback(call, user_management_callback)
        elif data == 'ban_user':
            admin_required_callback(call, ban_user_callback)
        elif data == 'unban_user':
            admin_required_callback(call, unban_user_callback)
        elif data == 'user_info':
            admin_required_callback(call, user_info_callback)
        elif data == 'all_users':
            admin_required_callback(call, all_users_callback)
        elif data == 'set_user_limit':
            admin_required_callback(call, set_user_limit_callback)
        elif data == 'remove_user_limit':
            admin_required_callback(call, remove_user_limit_callback)
        elif data == 'admin_settings':
            admin_required_callback(call, admin_settings_callback)
        elif data == 'system_info':
            admin_required_callback(call, system_info_callback)
        elif data == 'bot_performance':
            admin_required_callback(call, bot_performance_callback)
        elif data == 'cleanup_files':
            admin_required_callback(call, cleanup_files_callback)
        elif data == 'install_logs':
            admin_required_callback(call, install_logs_callback)
        elif data == 'admin_install':
            admin_required_callback(call, admin_install_callback)
        elif data == 'manage_mandatory_channels':
            admin_required_callback(call, manage_mandatory_channels_callback)
        elif data == 'add_mandatory_channel':
            admin_required_callback(call, add_mandatory_channel_callback)
        elif data == 'remove_mandatory_channel':
            admin_required_callback(call, remove_mandatory_channel_callback)
        elif data == 'list_mandatory_channels':
            admin_required_callback(call, list_mandatory_channels_callback)
        elif data.startswith('remove_channel_'):
            admin_required_callback(call, process_remove_channel)
        elif data == 'check_subscription_status':
            check_subscription_status_callback(call)
        # Plan purchase callbacks
        elif data.startswith('buy_plan_group_'):
            callback_buy_plan_group(call)
        elif data.startswith('buy_duration_'):
            callback_buy_duration(call)
        elif data.startswith('pay_zapupi_'):
            callback_pay_zapupi(call)
        elif data.startswith('pay_binance_manual_'):
            callback_pay_binance_manual(call)
        elif data.startswith('pay_wallet_'):
            callback_pay_wallet(call)
        elif data.startswith('verify_zapupi_'):
            callback_verify_zapupi(call)
        elif data == 'cancel_purchase':
            callback_cancel_purchase(call)
        # Admin plan management
        elif data == 'admin_create_plan_group':
            admin_required_callback(call, callback_admin_create_plan_group)
        elif data == 'admin_view_plan_groups':
            admin_required_callback(call, callback_admin_view_plan_groups)
        elif data == 'admin_edit_plan_group':
            admin_required_callback(call, callback_admin_edit_plan_group)
        elif data == 'admin_delete_plan_group':
            admin_required_callback(call, callback_admin_delete_plan_group)
        elif data == 'admin_add_plan_price':
            admin_required_callback(call, callback_admin_add_plan_price)
        elif data == 'admin_view_plan_prices':
            admin_required_callback(call, callback_admin_view_plan_prices)
        elif data == 'admin_edit_plan_price':
            admin_required_callback(call, callback_admin_edit_plan_price)
        elif data == 'admin_delete_plan_price':
            admin_required_callback(call, callback_admin_delete_plan_price)
        elif data == 'admin_plan_management':
            admin_required_callback(call, admin_plan_management_callback)
        elif data == 'admin_payment_settings':
            admin_required_callback(call, admin_payment_settings_callback)
        # Edit plan group detail
        elif data.startswith('edit_plan_group_detail_'):
            admin_required_callback(call, handle_edit_plan_group_detail)
        elif data.startswith('plan_group_edit_field_'):
            admin_required_callback(call, handle_plan_group_edit_field)
        # Edit price detail
        elif data.startswith('edit_plan_price_detail_'):
            admin_required_callback(call, handle_edit_plan_price_detail)
        elif data.startswith('plan_price_edit_field_'):
            admin_required_callback(call, handle_plan_price_edit_field)
        # Payment settings
        elif data == 'admin_zapupi_settings':
            admin_required_callback(call, callback_admin_zapupi_settings)
        elif data == 'admin_transactions':
            admin_required_callback(call, callback_admin_transactions)
        elif data == 'admin_revenue':
            admin_required_callback(call, callback_admin_revenue)
        elif data == 'zapupi_set_key':
            admin_required_callback(call, callback_zapupi_set_key)
        elif data == 'zapupi_toggle':
            admin_required_callback(call, callback_zapupi_toggle)
        elif data == 'zapupi_delete':
            admin_required_callback(call, callback_zapupi_delete)
        # Wallet callbacks
        elif data == 'admin_wallet_management':
            admin_required_callback(call, callback_admin_wallet_management)
        elif data == 'admin_add_balance':
            admin_required_callback(call, callback_admin_add_balance)
        elif data == 'admin_deduct_balance':
            admin_required_callback(call, callback_admin_deduct_balance)
        elif data == 'admin_check_balance':
            admin_required_callback(call, callback_admin_check_balance)
        elif data == 'admin_wallet_transactions':
            admin_required_callback(call, callback_admin_wallet_transactions)
        elif data == 'wallet_balance':
            callback_wallet_balance(call)
        elif data == 'add_balance':
            callback_add_balance(call)
        elif data == 'wallet_menu':
            callback_wallet_menu(call)
        elif data == 'wallet_transactions':
            callback_wallet_transactions(call)
        elif data == 'add_balance_zapupi':
            callback_add_balance_zapupi(call)
        elif data == 'add_balance_binance_manual':
            callback_add_balance_binance_manual(call)
        elif data.startswith('verify_balance_zapupi_'):
            callback_verify_balance_zapupi(call)
        # Binance manual copy buttons
        elif data.startswith('copy_binance_id_'):
            binance_id = binance_manual_settings.get('binance_id', 'Not set')
            bot.answer_callback_query(call.id, f"Binance ID: {binance_id}", show_alert=True)
        elif data.startswith('copy_trc_address_'):
            trc = binance_manual_settings.get('trc_address', 'Not set')
            bot.answer_callback_query(call.id, f"TRC Address: {trc}", show_alert=True)
        # Template callbacks
        elif data == 'available_bots':
            available_bots_callback(call)
        elif data == 'manage_templates':
            admin_required_callback(call, manage_templates_callback)
        elif data == 'admin_add_template':
            admin_required_callback(call, admin_add_template_callback)
        elif data == 'admin_list_templates':
            admin_required_callback(call, admin_list_templates_callback)
        elif data == 'admin_edit_template':
            admin_required_callback(call, admin_edit_template_callback)
        elif data == 'admin_delete_template':
            admin_required_callback(call, admin_delete_template_callback)
        elif data.startswith('buy_template_'):
            buy_template_callback(call)
        elif data.startswith('template_info_'):
            template_info_callback(call)
        elif data.startswith('pay_template_zapupi_'):
            pay_template_zapupi(call)
        elif data.startswith('pay_template_wallet_'):
            pay_template_wallet(call)
        elif data.startswith('pay_template_binance_manual_'):
            pay_template_binance_manual(call)
        elif data.startswith('verify_template_zapupi_'):
            verify_template_zapupi(call)
        elif data.startswith('submit_binance_manual_'):
            submit_binance_manual(call)
        elif data == 'admin_binance_manual_settings':
            admin_required_callback(call, admin_binance_manual_settings_callback)
        elif data == 'binance_manual_set_address':
            admin_required_callback(call, binance_manual_set_address_callback)
        elif data == 'binance_manual_toggle':
            admin_required_callback(call, binance_manual_toggle_callback)
        elif data.startswith('approve_binance_manual_'):
            admin_required_callback(call, approve_binance_manual_callback)
        elif data.startswith('reject_binance_manual_'):
            admin_required_callback(call, reject_binance_manual_callback)
        # Security Bypass callbacks
        elif data.startswith('approve_bypass_'):
            admin_required_callback(call, approve_bypass_callback)
        elif data.startswith('reject_bypass_'):
            admin_required_callback(call, reject_bypass_callback)
        # Pending payments
        elif data.startswith('approve_payment_'):
            admin_required_callback(call, approve_payment_callback)
        elif data.startswith('reject_payment_'):
            admin_required_callback(call, reject_payment_callback)
        # Edit template detail (admin)
        elif data.startswith('edit_template_detail_'):
            admin_required_callback(call, handle_edit_template_detail)
        elif data.startswith('template_edit_field_'):
            admin_required_callback(call, handle_template_edit_field)
        # View pending payments
        elif data == 'view_pending_payments':
            admin_required_callback(call, view_pending_payments_callback)
        elif data == 'admin_pending_payments':
            admin_required_callback(call, admin_pending_payments_callback)
        # Template param edit (admin)
        elif data.startswith('edit_template_param_'):
            admin_required_callback(call, handle_edit_template_param)
        elif data.startswith('template_param_edit_field_'):
            admin_required_callback(call, handle_template_param_edit_field_callback)
        elif data.startswith('template_add_param_'):
            admin_required_callback(call, handle_template_add_param)
        elif data.startswith('template_remove_param_'):
            admin_required_callback(call, handle_template_remove_param)
        elif data.startswith('template_remove_param_confirm_'):
            admin_required_callback(call, handle_template_remove_param_confirm)
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
            logger.warning(f"Unhandled callback data: {data} from user {user_id}")
    except Exception as e:
        logger.error(f"Error handling callback '{data}' for {user_id}: {e}", exc_info=True)
        try:
            bot.answer_callback_query(call.id, "Error processing request.", show_alert=True)
        except Exception as e_ans:
            logger.error(f"Failed to answer callback after error: {e_ans}")

def admin_required_callback(call, func_to_run):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin permissions required.", show_alert=True)
        return
    func_to_run(call)

def owner_required_callback(call, func_to_run):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "⚠️ Owner permissions required.", show_alert=True)
        return
    func_to_run(call)

# --- Callbacks for pending payments ---
def admin_pending_payments_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    show_pending_payments(call.message.chat.id)
    bot.answer_callback_query(call.id)

def view_pending_payments_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    show_pending_payments(call.message.chat.id)
    bot.answer_callback_query(call.id)

def approve_payment_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    txn_id = int(call.data.split('_')[2])
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT user_id, plan_id, amount, transaction_id, type, payment_details FROM transactions WHERE id = ? AND status = "pending"', (txn_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        bot.answer_callback_query(call.id, "Transaction not found or already processed.")
        return
    user_id, plan_id, amount, transaction_id, txn_type, payment_details = row
    details = json.loads(payment_details) if payment_details else {}
    duration_months = details.get('duration_months', 1)
    group_id = details.get('group_id', plan_id)
    if not group_id:
        conn2 = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c2 = conn2.cursor()
        c2.execute('SELECT group_id FROM plan_prices WHERE id = ?', (plan_id,))
        row2 = c2.fetchone()
        conn2.close()
        if row2:
            group_id = row2[0]
    update_transaction_status(txn_id, 'completed', {'admin_approved': True})
    success, result = complete_transaction(transaction_id, user_id, group_id, amount, txn_type, duration_months)
    if success:
        bot.send_message(call.message.chat.id, f"✅ Payment #{txn_id} approved and completed.")
        try:
            bot.send_message(user_id, f"✅ Your payment of ₹{amount} has been approved by admin. {result}")
        except:
            pass
    else:
        bot.send_message(call.message.chat.id, f"❌ Failed to complete payment: {result}")
    bot.answer_callback_query(call.id, "Payment approved.")

def reject_payment_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    txn_id = int(call.data.split('_')[2])
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT user_id, amount FROM transactions WHERE id = ? AND status = "pending"', (txn_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        bot.answer_callback_query(call.id, "Transaction not found.")
        return
    user_id, amount = row
    update_transaction_status(txn_id, 'failed', {'admin_rejected': True})
    bot.send_message(call.message.chat.id, f"❌ Payment #{txn_id} rejected.")
    try:
        bot.send_message(user_id, f"❌ Your payment of ₹{amount} has been rejected by admin. Please contact support.")
    except:
        pass
    bot.answer_callback_query(call.id, "Payment rejected.")

# --- Callbacks for wallet balance verification ---
def callback_verify_balance_zapupi(call):
    user_id = call.from_user.id
    order_id = call.data.split('_')[3]
    verify_payment_manually(user_id, order_id, 'zapupi', call.message.chat.id)
    bot.answer_callback_query(call.id)

# --- Callbacks for wallet menu ---
def callback_wallet_menu(call):
    user_id = call.from_user.id
    markup = create_wallet_menu(user_id)
    bot.edit_message_text("💰 Balance Menu:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def manual_install_callback(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    manual_install_module_init(call.message)

def upload_callback(call):
    user_id = call.from_user.id
    if is_user_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(subscription_message, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            bot.send_message(call.message.chat.id, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    file_limit = get_user_file_limit(user_id)
    if file_limit <= 0:
        bot.answer_callback_query(call.id, "🚫 No upload quota. Use /trial or buy a plan.", show_alert=True)
        return
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"⚠️ File limit ({current_files}/{limit_str}) reached.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.")

def check_files_callback(call):
    user_id = call.from_user.id
    if is_user_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(subscription_message, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            bot.send_message(call.message.chat.id, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    chat_id = call.message.chat.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.answer_callback_query(call.id, "⚠️ No files uploaded.", show_alert=True)
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
            bot.edit_message_text("📂 Your files:\n\n(No files uploaded)", chat_id, call.message.message_id, reply_markup=markup)
        except Exception as e:
            logger.error(f"Error editing msg for empty file list: {e}")
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        callback_data = f"file_{user_id}_{file_name}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
    markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
    try:
        bot.edit_message_text("📂 Your files:\nClick to manage.", chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            logger.warning("Msg not modified (files).")
        else:
            logger.error(f"Error editing msg for file list: {e}")
    except Exception as e:
        logger.error(f"Unexpected error editing msg for file list: {e}", exc_info=True)

def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            logger.warning(f"User {requesting_user_id} tried to access file '{file_name}' of user {script_owner_id} without permission.")
            bot.answer_callback_query(call.id, "⚠️ You can only manage your own files.", show_alert=True)
            check_files_callback(call)
            return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            logger.warning(f"File '{file_name}' not found for user {script_owner_id} during control.")
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            check_files_callback(call)
            return
        bot.answer_callback_query(call.id)
        is_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_running else '🔴 Stopped'
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?')
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_running, False, None),
                parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                logger.warning(f"Msg not modified (controls for {file_name})")
            else:
                raise
    except (ValueError, IndexError) as ve:
        logger.error(f"Error parsing file control callback: {ve}. Data: '{call.data}'")
        bot.answer_callback_query(call.id, "Error: Invalid action data.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in file_control_callback for data '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "An error occurred.", show_alert=True)

def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied to start this script.", show_alert=True)
            return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            check_files_callback(call)
            return
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ Error: File `{file_name}` missing! Re-upload.", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            check_files_callback(call)
            return
        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"⚠️ Script '{file_name}' already running.", show_alert=True)
            try:
                bot.edit_message_reply_markup(chat_id_for_reply, call.message.message_id, reply_markup=create_control_buttons(script_owner_id, file_name, True))
            except Exception as e:
                logger.error(f"Error updating buttons (already running): {e}")
            return
        bot.answer_callback_query(call.id, f"⏳ Attempting to start {file_name} for user {script_owner_id}...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message, 1, False)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message, 1, False)).start()
        else:
            bot.send_message(chat_id_for_reply, f"❌ Error: Unknown file type '{file_type}' for '{file_name}'.")
            return
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_now_running else '🟡 Starting (or failed, check logs/replies)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                logger.warning(f"Msg not modified after starting {file_name}")
            else:
                raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing start callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid start command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in start_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error starting script.", show_alert=True)
        try:
            _, script_owner_id_err_str, file_name_err = call.data.split('_', 2)
            script_owner_id_err = int(script_owner_id_err_str)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id_err, file_name_err, False))
        except Exception as e_btn:
            logger.error(f"Failed to update buttons after start error: {e_btn}")

def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            check_files_callback(call)
            return
        file_type = file_info[1]
        script_key = f"{script_owner_id}_{file_name}"
        if not is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"⚠️ Script '{file_name}' already stopped.", show_alert=True)
            try:
                bot.edit_message_text(
                    f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                    chat_id_for_reply, call.message.message_id,
                    reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Error updating buttons (already stopped): {e}")
            return
        bot.answer_callback_query(call.id, f"⏳ Stopping {file_name} for user {script_owner_id}...")
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        else:
            logger.warning(f"Script {script_key} running by psutil but not in bot_scripts dict.")
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                logger.warning(f"Msg not modified after stopping {file_name}")
            else:
                raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing stop callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid stop command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in stop_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error stopping script.", show_alert=True)

def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            check_files_callback(call)
            return
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        script_key = f"{script_owner_id}_{file_name}"
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ Error: File `{file_name}` missing! Re-upload.", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            check_files_callback(call)
            return
        bot.answer_callback_query(call.id, f"⏳ Restarting {file_name} for user {script_owner_id}...")
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            time.sleep(1.5)
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message, 1, False)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message, 1, False)).start()
        else:
            bot.send_message(chat_id_for_reply, f"❌ Unknown type '{file_type}' for '{file_name}'.")
            return
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_now_running else '🟡 Starting (or failed)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                logger.warning(f"Msg not modified (restart {file_name})")
            else:
                raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing restart callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid restart command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in restart_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error restarting.", show_alert=True)
        try:
            _, script_owner_id_err_str, file_name_err = call.data.split('_', 2)
            script_owner_id_err = int(script_owner_id_err_str)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id_err, file_name_err, False))
        except Exception as e_btn:
            logger.error(f"Failed to update buttons after restart error: {e_btn}")

def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            check_files_callback(call)
            return
        bot.answer_callback_query(call.id, f"🗑️ Deleting {file_name} for user {script_owner_id}...")
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            time.sleep(0.5)
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        deleted_disk = []
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                deleted_disk.append(file_name)
            except OSError as e:
                logger.error(f"Error deleting {file_path}: {e}")
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
                deleted_disk.append(os.path.basename(log_path))
            except OSError as e:
                logger.error(f"Error deleting log {log_path}: {e}")
        remove_user_file_db(script_owner_id, file_name)
        deleted_str = ", ".join(f"`{f}`" for f in deleted_disk) if deleted_disk else "associated files"
        try:
            bot.edit_message_text(
                f"🗑️ Record `{file_name}` (User `{script_owner_id}`) and {deleted_str} deleted!",
                chat_id_for_reply, call.message.message_id, reply_markup=None, parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error editing msg after delete: {e}")
            bot.send_message(chat_id_for_reply, f"🗑️ Record `{file_name}` deleted.", parse_mode='Markdown')
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing delete callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid delete command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in delete_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error deleting.", show_alert=True)

def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            check_files_callback(call)
            return
        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, f"⚠️ No logs for '{file_name}'.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        try:
            log_content = ""
            file_size = os.path.getsize(log_path)
            max_log_kb = 100
            max_tg_msg = 4096
            if file_size == 0:
                log_content = "(Log empty)"
            elif file_size > max_log_kb * 1024:
                with open(log_path, 'rb') as f:
                    f.seek(-max_log_kb * 1024, os.SEEK_END)
                    log_bytes = f.read()
                log_content = log_bytes.decode('utf-8', errors='ignore')
                log_content = f"(Last {max_log_kb} KB)\n...\n" + log_content
            else:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read()
            if len(log_content) > max_tg_msg:
                log_content = log_content[-max_tg_msg:]
                first_nl = log_content.find('\n')
                if first_nl != -1:
                    log_content = "...\n" + log_content[first_nl+1:]
                else:
                    log_content = "...\n" + log_content
            if not log_content.strip():
                log_content = "(No visible content)"
            bot.send_message(chat_id_for_reply, f"📜 Logs for `{file_name}` (User `{script_owner_id}`):\n```\n{log_content}\n```", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error reading/sending log {log_path}: {e}", exc_info=True)
            bot.send_message(chat_id_for_reply, f"❌ Error reading log for `{file_name}`.")
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing logs callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid logs command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in logs_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error fetching logs.", show_alert=True)

def speed_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if is_user_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(subscription_message, chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            bot.send_message(chat_id, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    start_cb_ping_time = time.time()
    try:
        bot.edit_message_text("🏃 Testing speed...", chat_id, call.message.message_id)
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_cb_ping_time) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID:
            user_level = "👑 Owner"
        elif user_id in admin_ids:
            user_level = "🛡️ Admin"
        elif get_user_active_plan(user_id):
            user_level = "⭐ Premium"
        elif get_user_trial(user_id):
            user_level = "🎁 Trial"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            user_level = "⭐ Premium (Legacy)"
        else:
            user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     f"👤 Your Level: {user_level}\n"
                     f"💰 Balance: ₹{get_wallet_balance(user_id):.2f}")
        bot.answer_callback_query(call.id)
        bot.edit_message_text(speed_msg, chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
    except Exception as e:
        logger.error(f"Error during speed test (cb): {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error in speed test.", show_alert=True)
        try:
            bot.edit_message_text("〽️ Main Menu", chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
        except Exception:
            pass

def back_to_main_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if is_user_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return

    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(subscription_message, chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            bot.send_message(chat_id, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return

    expiry_info = ""
    limit_str = "Unlimited"
    ram_str = "N/A"
    wallet_balance = get_wallet_balance(user_id)

    active_plan = get_user_active_plan(user_id)
    if active_plan:
        group = get_plan_group(active_plan['plan_id'])
        group_name = group['name'] if group else f"Plan {active_plan['plan_id']}"
        user_status = f"⭐ Premium ({group_name})"
        days_left = (active_plan['expiry_date'] - datetime.now()).days
        expiry_info = f"\n⏳ Expires in: {days_left} days"
        limit_str = str(active_plan['bot_limit'])
        ram_str = f"{active_plan['ram_limit']} MiB"
    else:
        trial_expiry = get_user_trial(user_id)
        if trial_expiry:
            remaining = (trial_expiry - datetime.now()).seconds // 60
            user_status = f"🎁 Trial (1 hour) - {remaining} min left"
            limit_str = str(TRIAL_BOT_LIMIT)
            ram_str = "128 MiB"
        else:
            if user_id == OWNER_ID:
                user_status = "👑 Owner"
            elif user_id in admin_ids:
                user_status = "🛡️ Admin"
            elif user_id in user_subscriptions:
                expiry_date = user_subscriptions[user_id].get('expiry')
                if expiry_date and expiry_date > datetime.now():
                    user_status = "⭐ Premium (Legacy)"
                    days_left = (expiry_date - datetime.now()).days
                    expiry_info = f"\n⏳ Subscription expires in: {days_left} days"
                else:
                    user_status = "🆓 Free User (Expired Sub)"
                    remove_subscription_db(user_id)
            else:
                user_status = "🆓 Free User"
            limit = get_user_file_limit(user_id)
            limit_str = str(limit) if limit != float('inf') else "Unlimited"
            ram_str = str(get_user_ram_limit(user_id)) + " MiB"

    current_files = get_user_file_count(user_id)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT phone FROM active_users WHERE user_id = ?', (user_id,))
    phone_row = c.fetchone()
    conn.close()
    phone = phone_row[0] if phone_row and phone_row[0] else "Not set"

    main_menu_text = (f"〽️ Welcome back, {call.from_user.first_name}!\n\n🆔 ID: `{user_id}`\n"
                      f"📱 Phone: {phone}\n"
                      f"🔰 Status: {user_status}{expiry_info}\n📁 Files: {current_files} / {limit_str}\n"
                      f"🧠 RAM: {ram_str}\n💰 Balance: ₹{wallet_balance:.2f}\n\n"
                      f"👇 Use buttons or type commands.")
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(main_menu_text, chat_id, call.message.message_id,
                              reply_markup=create_main_menu_inline(user_id), parse_mode='Markdown')
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            logger.warning("Msg not modified (back_to_main).")
        else:
            logger.error(f"API error on back_to_main: {e}")
    except Exception as e:
        logger.error(f"Error handling back_to_main: {e}", exc_info=True)

def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("💳 Subscription Management\nSelect action:",
                              call.message.chat.id, call.message.message_id, reply_markup=create_subscription_menu())
    except Exception as e:
        logger.error(f"Error showing sub menu: {e}")

def stats_callback(call):
    bot.answer_callback_query(call.id)
    _logic_statistics(call.message)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e:
        logger.error(f"Error updating menu after stats_callback: {e}")

def lock_bot_callback(call):
    global bot_locked
    bot_locked = True
    logger.warning(f"Bot locked by Admin {call.from_user.id}")
    bot.answer_callback_query(call.id, "🔒 Bot locked.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e:
        logger.error(f"Error updating menu (lock): {e}")

def unlock_bot_callback(call):
    global bot_locked
    bot_locked = False
    logger.warning(f"Bot unlocked by Admin {call.from_user.id}")
    bot.answer_callback_query(call.id, "🔓 Bot unlocked.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e:
        logger.error(f"Error updating menu (unlock): {e}")

def run_all_scripts_callback(call):
    _logic_run_all_scripts(call)

def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Broadcast cancelled.")
        return
    broadcast_content = message.text
    if not broadcast_content and not (message.photo or message.video or message.document or message.sticker or message.voice or message.audio):
        bot.reply_to(message, "⚠️ Cannot broadcast empty message. Send text or media, or /cancel.")
        msg = bot.send_message(message.chat.id, "📢 Send broadcast message or /cancel.")
        bot.register_next_step_handler(msg, process_broadcast_message)
        return
    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("✅ Confirm & Send", callback_data=f"confirm_broadcast_{message.message_id}"),
               types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast"))
    preview_text = broadcast_content[:1000].strip() if broadcast_content else "(Media message)"
    bot.reply_to(message, f"⚠️ Confirm Broadcast:\n\n```\n{preview_text}\n```\n"
                          f"To **{target_count}** users. Sure?", reply_markup=markup, parse_mode='Markdown')

def handle_confirm_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
        return
    try:
        original_message = call.message.reply_to_message
        if not original_message:
            raise ValueError("Could not retrieve original message.")
        broadcast_text = None
        broadcast_photo_id = None
        broadcast_video_id = None
        if original_message.text:
            broadcast_text = original_message.text
        elif original_message.photo:
            broadcast_photo_id = original_message.photo[-1].file_id
        elif original_message.video:
            broadcast_video_id = original_message.video.file_id
        else:
            raise ValueError("Message has no text or supported media for broadcast.")
        bot.answer_callback_query(call.id, "🚀 Starting broadcast...")
        bot.edit_message_text(f"📢 Broadcasting to {len(active_users)} users...",
                              chat_id, call.message.message_id, reply_markup=None)
        thread = threading.Thread(target=execute_broadcast, args=(
            broadcast_text, broadcast_photo_id, broadcast_video_id,
            original_message.caption if (broadcast_photo_id or broadcast_video_id) else None,
            chat_id))
        thread.start()
    except ValueError as ve:
        logger.error(f"Error retrieving msg for broadcast confirm: {ve}")
        bot.edit_message_text(f"❌ Error starting broadcast: {ve}", chat_id, call.message.message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Error in handle_confirm_broadcast: {e}", exc_info=True)
        bot.edit_message_text("❌ Unexpected error during broadcast confirm.", chat_id, call.message.message_id, reply_markup=None)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Broadcast cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    if call.message.reply_to_message:
        try:
            bot.delete_message(call.message.chat.id, call.message.reply_to_message.message_id)
        except:
            pass

def execute_broadcast(broadcast_text, photo_id, video_id, caption, admin_chat_id):
    sent_count = 0
    failed_count = 0
    blocked_count = 0
    start_exec_time = time.time()
    users_to_broadcast = list(active_users)
    total_users = len(users_to_broadcast)
    logger.info(f"Executing broadcast to {total_users} users.")
    batch_size = 25
    delay_batches = 1.5
    for i, user_id_bc in enumerate(users_to_broadcast):
        try:
            if broadcast_text:
                bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            elif photo_id:
                bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
            elif video_id:
                bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
            sent_count += 1
        except telebot.apihelper.ApiTelegramException as e:
            err_desc = str(e).lower()
            if any(s in err_desc for s in ["bot was blocked", "user is deactivated", "chat not found", "kicked from", "restricted"]):
                logger.warning(f"Broadcast failed to {user_id_bc}: User blocked/inactive.")
                blocked_count += 1
            elif "flood control" in err_desc or "too many requests" in err_desc:
                retry_after = 5
                match = re.search(r"retry after (\d+)", err_desc)
                if match:
                    retry_after = int(match.group(1)) + 1
                logger.warning(f"Flood control. Sleeping {retry_after}s...")
                time.sleep(retry_after)
                try:
                    if broadcast_text:
                        bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
                    elif photo_id:
                        bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
                    elif video_id:
                        bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
                    sent_count += 1
                except Exception as e_retry:
                    logger.error(f"Broadcast retry failed to {user_id_bc}: {e_retry}")
                    failed_count += 1
            else:
                logger.error(f"Broadcast failed to {user_id_bc}: {e}")
                failed_count += 1
        except Exception as e:
            logger.error(f"Unexpected error broadcasting to {user_id_bc}: {e}")
            failed_count += 1
        if (i + 1) % batch_size == 0 and i < total_users - 1:
            logger.info(f"Broadcast batch {i//batch_size + 1} sent. Sleeping {delay_batches}s...")
            time.sleep(delay_batches)
        elif i % 5 == 0:
            time.sleep(0.2)
    duration = round(time.time() - start_exec_time, 2)
    result_msg = (f"📢 Broadcast Complete!\n\n✅ Sent: {sent_count}\n❌ Failed: {failed_count}\n"
                  f"🚫 Blocked/Inactive: {blocked_count}\n👥 Targets: {total_users}\n⏱️ Duration: {duration}s")
    logger.info(result_msg)
    try:
        bot.send_message(admin_chat_id, result_msg)
    except Exception as e:
        logger.error(f"Failed to send broadcast result to admin {admin_chat_id}: {e}")

def admin_panel_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("👑 Admin Panel\nManage admins (Owner actions may be restricted).",
                              call.message.chat.id, call.message.message_id, reply_markup=create_admin_panel())
    except Exception as e:
        logger.error(f"Error showing admin panel: {e}")

def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to promote to Admin.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_admin_id)

def process_add_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Admin promotion cancelled.")
        return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id <= 0:
            raise ValueError("ID must be positive")
        if new_admin_id == OWNER_ID:
            bot.reply_to(message, "⚠️ Owner is already Owner.")
            return
        if new_admin_id in admin_ids:
            bot.reply_to(message, f"⚠️ User `{new_admin_id}` already Admin.")
            return
        add_admin_db(new_admin_id, owner_id_check)
        logger.warning(f"Admin {new_admin_id} added by Owner {owner_id_check}.")
        bot.reply_to(message, f"✅ User `{new_admin_id}` promoted to Admin.")
        try:
            bot.send_message(new_admin_id, "🎉 Congrats! You are now an Admin.")
        except Exception as e:
            logger.error(f"Failed to notify new admin {new_admin_id}: {e}")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "👑 Enter User ID to promote or /cancel.")
        bot.register_next_step_handler(msg, process_add_admin_id)
    except Exception as e:
        logger.error(f"Error processing add admin: {e}", exc_info=True)
        bot.reply_to(message, "Error.")

def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID of Admin to remove.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_admin_id)

def process_remove_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Admin removal cancelled.")
        return
    try:
        admin_id_remove = int(message.text.strip())
        if admin_id_remove <= 0:
            raise ValueError("ID must be positive")
        if admin_id_remove == OWNER_ID:
            bot.reply_to(message, "⚠️ Owner cannot remove self.")
            return
        if admin_id_remove not in admin_ids:
            bot.reply_to(message, f"⚠️ User `{admin_id_remove}` not Admin.")
            return
        if remove_admin_db(admin_id_remove):
            logger.warning(f"Admin {admin_id_remove} removed by Owner {owner_id_check}.")
            bot.reply_to(message, f"✅ Admin `{admin_id_remove}` removed.")
            try:
                bot.send_message(admin_id_remove, "ℹ️ You are no longer an Admin.")
            except Exception as e:
                logger.error(f"Failed to notify removed admin {admin_id_remove}: {e}")
        else:
            bot.reply_to(message, f"❌ Failed to remove admin `{admin_id_remove}`. Check logs.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "👑 Enter Admin ID to remove or /cancel.")
        bot.register_next_step_handler(msg, process_remove_admin_id)
    except Exception as e:
        logger.error(f"Error processing remove admin: {e}", exc_info=True)
        bot.reply_to(message, "Error.")

def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    try:
        admin_list_str = "\n".join(f"- `{aid}` {'(Owner)' if aid == OWNER_ID else ''}" for aid in sorted(list(admin_ids)))
        if not admin_list_str:
            admin_list_str = "(No Owner/Admins configured!)"
        bot.edit_message_text(f"👑 Current Admins:\n\n{admin_list_str}", call.message.chat.id,
                              call.message.message_id, reply_markup=create_admin_panel(), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error listing admins: {e}")

def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID & days (e.g., `12345678 30`).\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_subscription_details)

def process_add_subscription_details(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Sub add cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError("Incorrect format")
        sub_user_id = int(parts[0].strip())
        days = int(parts[1].strip())
        if sub_user_id <= 0 or days <= 0:
            raise ValueError("User ID/days must be positive")
        current_expiry = user_subscriptions.get(sub_user_id, {}).get('expiry')
        start_date_new_sub = datetime.now()
        if current_expiry and current_expiry > start_date_new_sub:
            start_date_new_sub = current_expiry
        new_expiry = start_date_new_sub + timedelta(days=days)
        save_subscription(sub_user_id, new_expiry)
        logger.info(f"Sub for {sub_user_id} by admin {admin_id_check}. Expiry: {new_expiry:%Y-%m-%d}")
        bot.reply_to(message, f"✅ Sub for `{sub_user_id}` by {days} days.\nNew expiry: {new_expiry:%Y-%m-%d}")
        try:
            bot.send_message(sub_user_id, f"🎉 Sub activated/extended by {days} days! Expires: {new_expiry:%Y-%m-%d}.")
        except Exception as e:
            logger.error(f"Failed to notify {sub_user_id} of new sub: {e}")
    except ValueError as e:
        bot.reply_to(message, f"⚠️ Invalid: {e}. Format: `ID days` or /cancel.")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID & days, or /cancel.")
        bot.register_next_step_handler(msg, process_add_subscription_details)
    except Exception as e:
        logger.error(f"Error processing add sub: {e}", exc_info=True)
        bot.reply_to(message, "Error.")

def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to remove sub.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_subscription_id)

def process_remove_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Sub removal cancelled.")
        return
    try:
        sub_user_id_remove = int(message.text.strip())
        if sub_user_id_remove <= 0:
            raise ValueError("ID must be positive")
        if sub_user_id_remove not in user_subscriptions:
            bot.reply_to(message, f"⚠️ User `{sub_user_id_remove}` no active sub in memory.")
            return
        remove_subscription_db(sub_user_id_remove)
        logger.warning(f"Sub removed for {sub_user_id_remove} by admin {admin_id_check}.")
        bot.reply_to(message, f"✅ Sub for `{sub_user_id_remove}` removed.")
        try:
            bot.send_message(sub_user_id_remove, "ℹ️ Your subscription removed by admin.")
        except Exception as e:
            logger.error(f"Failed to notify {sub_user_id_remove} of sub removal: {e}")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID to remove sub from, or /cancel.")
        bot.register_next_step_handler(msg, process_remove_subscription_id)
    except Exception as e:
        logger.error(f"Error processing remove sub: {e}", exc_info=True)
        bot.reply_to(message, "Error.")

def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to check sub.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_check_subscription_id)

def process_check_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Sub check cancelled.")
        return
    try:
        sub_user_id_check = int(message.text.strip())
        if sub_user_id_check <= 0:
            raise ValueError("ID must be positive")
        if sub_user_id_check in user_subscriptions:
            expiry_dt = user_subscriptions[sub_user_id_check].get('expiry')
            if expiry_dt:
                if expiry_dt > datetime.now():
                    days_left = (expiry_dt - datetime.now()).days
                    bot.reply_to(message, f"✅ User `{sub_user_id_check}` active sub.\nExpires: {expiry_dt:%Y-%m-%d %H:%M:%S} ({days_left} days left).")
                else:
                    bot.reply_to(message, f"⚠️ User `{sub_user_id_check}` expired sub (On: {expiry_dt:%Y-%m-%d %H:%M:%S}).")
                    remove_subscription_db(sub_user_id_check)
            else:
                bot.reply_to(message, f"⚠️ User `{sub_user_id_check}` in sub list, but expiry missing. Re-add if needed.")
        else:
            bot.reply_to(message, f"ℹ️ User `{sub_user_id_check}` no active sub record.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID to check, or /cancel.")
        bot.register_next_step_handler(msg, process_check_subscription_id)
    except Exception as e:
        logger.error(f"Error processing check sub: {e}", exc_info=True)
        bot.reply_to(message, "Error.")

def user_management_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("👥 User Management\nSelect action:", call.message.chat.id,
                              call.message.message_id, reply_markup=create_user_management_menu())
    except Exception as e:
        logger.error(f"Error showing user management menu: {e}")

def ban_user_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🚫 Enter User ID to ban and reason (e.g., `12345678 Spamming`)\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_ban_user)

def process_ban_user(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Ban cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Format: `user_id reason`\nExample: `12345678 Spamming`")
            return
        user_id = int(parts[0])
        reason = ' '.join(parts[1:])
        if user_id <= 0:
            raise ValueError("ID must be positive")
        if user_id == OWNER_ID:
            bot.reply_to(message, "⚠️ Cannot ban owner.")
            return
        if user_id in admin_ids:
            bot.reply_to(message, "⚠️ Cannot ban admin.")
            return
        if ban_user_db(user_id, reason, admin_id):
            bot.reply_to(message, f"✅ User `{user_id}` banned.\nReason: {reason}")
            for file_name, _ in user_files.get(user_id, []):
                script_key = f"{user_id}_{file_name}"
                if script_key in bot_scripts:
                    kill_process_tree(bot_scripts[script_key])
                    del bot_scripts[script_key]
            try:
                bot.send_message(user_id, f"🚫 You have been banned from using this bot.\nReason: {reason}")
            except Exception as e:
                logger.error(f"Failed to notify banned user {user_id}: {e}")
        else:
            bot.reply_to(message, "❌ Failed to ban user.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid user ID. Must be a number.")
    except Exception as e:
        logger.error(f"Error banning user: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")

def unban_user_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "✅ Enter User ID to unban\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_unban_user)

def process_unban_user(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Unban cancelled.")
        return
    try:
        user_id = int(message.text.strip())
        if user_id <= 0:
            raise ValueError("ID must be positive")
        if user_id not in banned_users:
            bot.reply_to(message, f"ℹ️ User `{user_id}` is not banned.")
            return
        if unban_user_db(user_id):
            bot.reply_to(message, f"✅ User `{user_id}` unbanned.")
            try:
                bot.send_message(user_id, "✅ Your ban has been lifted. You can now use the bot again.")
            except Exception as e:
                logger.error(f"Failed to notify unbanned user {user_id}: {e}")
        else:
            bot.reply_to(message, "❌ Failed to unban user.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid user ID. Must be a number.")
    except Exception as e:
        logger.error(f"Error unbanning user: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")

def user_info_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👤 Enter User ID to get info\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_user_info)

def process_user_info(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Info request cancelled.")
        return
    try:
        user_id = int(message.text.strip())
        if user_id <= 0:
            raise ValueError("ID must be positive")
        info_parts = []
        info_parts.append(f"👤 **User ID:** `{user_id}`")
        active_plan = get_user_active_plan(user_id)
        if active_plan:
            group = get_plan_group(active_plan['plan_id'])
            group_name = group['name'] if group else f"Plan {active_plan['plan_id']}"
            info_parts.append(f"⭐ **Plan:** {group_name} (Bot limit: {active_plan['bot_limit']}, RAM: {active_plan['ram_limit']} MiB)")
            info_parts.append(f"📅 **Expiry:** {active_plan['expiry_date'].strftime('%Y-%m-%d %H:%M:%S')}")
            days_left = (active_plan['expiry_date'] - datetime.now()).days
            info_parts.append(f"⏳ **Days left:** {days_left}")
        else:
            trial_expiry = get_user_trial(user_id)
            if trial_expiry:
                remaining = (trial_expiry - datetime.now()).seconds // 60
                info_parts.append(f"🎁 **Trial:** {remaining} minutes left")
            else:
                if user_id == OWNER_ID:
                    info_parts.append("👑 **Status:** Owner")
                elif user_id in admin_ids:
                    info_parts.append("🛡️ **Status:** Admin")
                elif user_id in banned_users:
                    info_parts.append("🚫 **Status:** Banned")
                elif user_id in user_subscriptions:
                    expiry = user_subscriptions[user_id].get('expiry')
                    if expiry and expiry > datetime.now():
                        days_left = (expiry - datetime.now()).days
                        info_parts.append(f"⭐ **Status:** Premium (Legacy, expires in {days_left} days)")
                    else:
                        info_parts.append("🆓 **Status:** Free User (Expired subscription)")
                else:
                    info_parts.append("🆓 **Status:** Free User")
        file_count = get_user_file_count(user_id)
        file_limit = get_user_file_limit(user_id)
        info_parts.append(f"📁 **Files:** {file_count}/{file_limit if file_limit != float('inf') else 'Unlimited'}")
        if user_id in user_limits:
            info_parts.append(f"⚙️ **Custom Limit:** {user_limits[user_id]}")
        running_scripts = 0
        for file_name, _ in user_files.get(user_id, []):
            if is_bot_running(user_id, file_name):
                running_scripts += 1
        info_parts.append(f"🤖 **Running Scripts:** {running_scripts}")
        wallet_balance = get_wallet_balance(user_id)
        info_parts.append(f"💰 **Balance:** ₹{wallet_balance:.2f}")
        if user_id in active_users:
            info_parts.append("🟢 **Status:** Active")
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT phone FROM active_users WHERE user_id = ?', (user_id,))
        phone_row = c.fetchone()
        conn.close()
        phone = phone_row[0] if phone_row and phone_row[0] else "Not set"
        info_parts.append(f"📱 **Phone:** {phone}")

        info_text = "\n".join(info_parts)
        bot.reply_to(message, info_text, parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid user ID. Must be a number.")
    except Exception as e:
        logger.error(f"Error getting user info: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")

def all_users_callback(call):
    bot.answer_callback_query(call.id)
    try:
        if not active_users:
            bot.edit_message_text("👥 No active users yet.", call.message.chat.id, call.message.message_id)
            return
        users_list = list(active_users)
        chunk_size = 20
        total_pages = (len(users_list) + chunk_size - 1) // chunk_size
        current_page = 0
        display_users_list(call.message.chat.id, call.message.message_id, users_list, current_page, total_pages, chunk_size)
    except Exception as e:
        logger.error(f"Error displaying all users: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error displaying users.", show_alert=True)

def display_users_list(chat_id, message_id, users_list, page, total_pages, chunk_size):
    start_idx = page * chunk_size
    end_idx = min(start_idx + chunk_size, len(users_list))
    user_chunk = users_list[start_idx:end_idx]
    message_text = f"👥 **Active Users** (Page {page + 1}/{total_pages})\n\n"
    for i, user_id in enumerate(user_chunk, start=start_idx + 1):
        status = ""
        if user_id == OWNER_ID:
            status = "👑"
        elif user_id in admin_ids:
            status = "🛡️"
        elif user_id in banned_users:
            status = "🚫"
        elif get_user_active_plan(user_id):
            status = "⭐"
        elif get_user_trial(user_id):
            status = "🎁"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            status = "⭐"
        else:
            status = "🆓"
        message_text += f"{i}. `{user_id}` {status}\n"
    markup = types.InlineKeyboardMarkup(row_width=3)
    if total_pages > 1:
        page_buttons = []
        if page > 0:
            page_buttons.append(types.InlineKeyboardButton("⬅️ Previous", callback_data=f"users_page_{page-1}"))
        page_buttons.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            page_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"users_page_{page+1}"))
        markup.row(*page_buttons)
    markup.row(types.InlineKeyboardButton("🔙 Back to User Management", callback_data='user_management'))
    try:
        bot.edit_message_text(message_text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error editing users list: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('users_page_'))
def handle_users_page(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
        return
    try:
        page = int(call.data.split('_')[2])
        users_list = list(active_users)
        chunk_size = 20
        total_pages = (len(users_list) + chunk_size - 1) // chunk_size
        if 0 <= page < total_pages:
            bot.answer_callback_query(call.id)
            display_users_list(call.message.chat.id, call.message.message_id, users_list, page, total_pages, chunk_size)
    except Exception as e:
        logger.error(f"Error handling users page: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

def set_user_limit_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🔧 Enter User ID and new limit (e.g., `12345678 50`)\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_set_user_limit)

def process_set_user_limit(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Limit set cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError("Format: user_id limit")
        user_id = int(parts[0])
        limit = int(parts[1])
        if user_id <= 0 or limit <= 0:
            raise ValueError("ID and limit must be positive")
        if set_user_limit_db(user_id, limit, admin_id):
            bot.reply_to(message, f"✅ Set file limit {limit} for user `{user_id}`")
            try:
                bot.send_message(user_id, f"⚙️ Your file upload limit has been set to {limit}")
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
        else:
            bot.reply_to(message, "❌ Failed to set limit.")
    except ValueError as e:
        bot.reply_to(message, f"⚠️ Invalid input: {e}\nFormat: `user_id limit`")
    except Exception as e:
        logger.error(f"Error setting user limit: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")

def remove_user_limit_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🗑️ Enter User ID to remove custom limit\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_remove_user_limit)

def process_remove_user_limit(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Limit removal cancelled.")
        return
    try:
        user_id = int(message.text.strip())
        if user_id <= 0:
            raise ValueError("ID must be positive")
        if user_id not in user_limits:
            bot.reply_to(message, f"ℹ️ User `{user_id}` has no custom limit.")
            return
        if remove_user_limit_db(user_id):
            bot.reply_to(message, f"✅ Removed custom limit for user `{user_id}`")
            try:
                bot.send_message(user_id, "⚙️ Your custom file limit has been removed")
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
        else:
            bot.reply_to(message, "❌ Failed to remove limit.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid user ID. Must be a number.")
    except Exception as e:
        logger.error(f"Error removing user limit: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")

def admin_settings_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("⚙️ Admin Settings\nSelect action:", call.message.chat.id,
                              call.message.message_id, reply_markup=create_admin_settings_menu())
    except Exception as e:
        logger.error(f"Error showing admin settings: {e}")

def system_info_callback(call):
    bot.answer_callback_query(call.id)
    try:
        import platform
        info_parts = []
        info_parts.append("🤖 **Bot Information:**")
        info_parts.append(f"• Python: {platform.python_version()}")
        info_parts.append(f"• Platform: {platform.platform()}")
        info_parts.append(f"• Uptime: {time.strftime('%H:%M:%S', time.gmtime(time.time() - psutil.boot_time()))}")
        info_parts.append("\n💻 **System Information:**")
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            info_parts.append(f"• CPU Usage: {cpu_percent}%")
            info_parts.append(f"• Memory: {memory.percent}% used ({memory.used//1024//1024}MB/{memory.total//1024//1024}MB)")
            info_parts.append(f"• Disk: {disk.percent}% used ({disk.used//1024//1024}MB/{disk.total//1024//1024}MB)")
        except Exception as e:
            info_parts.append(f"• System stats error: {str(e)}")
        info_parts.append("\n📊 **Bot Statistics:**")
        info_parts.append(f"• Active Users: {len(active_users)}")
        info_parts.append(f"• Running Scripts: {len(bot_scripts)}")
        info_parts.append(f"• Total Files: {sum(len(files) for files in user_files.values())}")
        info_parts.append(f"• Bot Status: {'🔒 Locked' if bot_locked else '🔓 Unlocked'}")
        info_parts.append(f"• Plan Groups: {len(plan_groups_cache)}")
        info_parts.append(f"• Plan Prices: {len(plan_prices_cache)}")
        info_parts.append(f"• Wallets: {len(user_wallets)}")
        info_parts.append(f"• Templates: {len(templates_cache)}")
        info_parts.append(f"• Pending Bypass Requests: {len(security_bypass_requests)}")
        info_parts.append(f"• Active Subscriptions: {len(user_subscriptions)}")
        info_text = "\n".join(info_parts)
        bot.edit_message_text(info_text, call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_settings_menu())
    except Exception as e:
        logger.error(f"Error showing system info: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error showing system info.", show_alert=True)

def bot_performance_callback(call):
    bot.answer_callback_query(call.id)
    try:
        performance_parts = []
        running_scripts = len(bot_scripts)
        total_files = sum(len(files) for files in user_files.values())
        performance_parts.append("📈 Bot Performance Metrics:")
        performance_parts.append(f"• Running Scripts: {running_scripts}")
        performance_parts.append(f"• Total Scripts: {total_files}")
        if total_files > 0:
            performance_parts.append(f"• Uptime Ratio: {running_scripts}/{total_files} ({running_scripts/total_files*100:.1f}%)")
        else:
            performance_parts.append("• Uptime Ratio: No scripts")
        try:
            bot_process = psutil.Process()
            memory_usage = bot_process.memory_info().rss / 1024 / 1024
            cpu_usage = bot_process.cpu_percent(interval=0.5)
            performance_parts.append("\n💾 Resource Usage:")
            performance_parts.append(f"• Memory: {memory_usage:.1f} MB")
            performance_parts.append(f"• CPU: {cpu_usage:.1f}%")
        except Exception as e:
            performance_parts.append(f"\n⚠️ Resource stats error: {str(e)}")
        performance_parts.append("\n🗄️ Database:")
        performance_parts.append(f"• Active Users: {len(active_users)}")
        performance_parts.append(f"• Subscriptions: {len(user_subscriptions)}")
        performance_parts.append(f"• Banned Users: {len(banned_users)}")
        performance_parts.append(f"• Custom Limits: {len(user_limits)}")
        performance_parts.append(f"• Plan Groups: {len(plan_groups_cache)}")
        performance_parts.append(f"• Plan Prices: {len(plan_prices_cache)}")
        performance_parts.append(f"• Wallets: {len(user_wallets)}")
        performance_parts.append(f"• Templates: {len(templates_cache)}")
        performance_text = "\n".join(performance_parts)
        bot.edit_message_text(performance_text, call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_settings_menu())
    except Exception as e:
        logger.error(f"Error showing performance: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error showing performance.", show_alert=True)

def cleanup_files_callback(call):
    bot.answer_callback_query(call.id, "🧹 Cleaning up temporary files...")
    try:
        cleaned_dirs = 0
        cleaned_files = 0
        for user_dir in os.listdir(UPLOAD_BOTS_DIR):
            user_path = os.path.join(UPLOAD_BOTS_DIR, user_dir)
            if os.path.isdir(user_path):
                if not os.listdir(user_path):
                    try:
                        os.rmdir(user_path)
                        cleaned_dirs += 1
                    except Exception as e:
                        logger.error(f"Error removing empty dir {user_path}: {e}")
                else:
                    for file_name in os.listdir(user_path):
                        if file_name.endswith('.log'):
                            file_path = os.path.join(user_path, file_name)
                            try:
                                file_age = time.time() - os.path.getmtime(file_path)
                                if file_age > 7 * 24 * 3600:
                                    os.remove(file_path)
                                    cleaned_files += 1
                            except Exception as e:
                                logger.error(f"Error cleaning log file {file_path}: {e}")
        result_msg = f"🧹 **Cleanup Complete:**\n• Removed empty directories: {cleaned_dirs}\n• Cleared old log files: {cleaned_files}"
        bot.edit_message_text(result_msg, call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_settings_menu(), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        bot.edit_message_text(f"❌ Cleanup error: {str(e)}", call.message.chat.id, call.message.message_id)

def install_logs_callback(call):
    bot.answer_callback_query(call.id)
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT user_id, module_name, package_name, status, install_date FROM install_logs ORDER BY install_date DESC LIMIT 20')
            logs = c.fetchall()
            conn.close()
        if not logs:
            bot.edit_message_text("📋 **No installation logs found**", call.message.chat.id,
                                  call.message.message_id, reply_markup=create_admin_settings_menu())
            return
        log_text = "📋 **Recent Installation Logs (Last 20):**\n\n"
        for user_id, module_name, package_name, status, install_date in logs:
            status_icon = "✅" if status == "success" else "❌" if status == "failed" else "⚠️"
            log_text += f"{status_icon} `{user_id}`: {module_name} -> {package_name}\n"
            log_text += f"   📅 {install_date[:19]}\n\n"
        bot.edit_message_text(log_text, call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_settings_menu(), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error showing install logs: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error showing logs.", show_alert=True)

def admin_install_callback(call):
    bot.answer_callback_query(call.id)
    _logic_admin_install(call.message)

def manage_mandatory_channels_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("📢 Manage Mandatory Channels\nChoose desired action:",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=create_mandatory_channels_menu())
    except Exception as e:
        logger.error(f"Error showing channel management menu: {e}")

def add_mandatory_channel_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 Send channel ID or username (example: @channel_username or -1001234567890)\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_add_channel)

def process_add_channel(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Channel addition cancelled.")
        return
    channel_identifier = message.text.strip()
    try:
        chat = bot.get_chat(channel_identifier)
        channel_id = str(chat.id)
        channel_username = f"@{chat.username}" if chat.username else ""
        channel_name = chat.title
        try:
            bot_member = bot.get_chat_member(channel_id, bot.get_me().id)
            if bot_member.status not in ['administrator', 'creator']:
                bot.reply_to(message, f"❌ Bot is not admin in the channel! Must be promoted first.")
                return
        except Exception as e:
            bot.reply_to(message, f"❌ Bot is not admin in the channel or cannot access it!")
            return
        if save_mandatory_channel(channel_id, channel_username, channel_name, admin_id):
            bot.reply_to(message, f"✅ Mandatory channel added:\n**{channel_name}**\n{channel_username or channel_id}")
        else:
            bot.reply_to(message, "❌ Failed to add channel. Try again.")
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        bot.reply_to(message, f"❌ Error adding channel: {str(e)}")

def remove_mandatory_channel_callback(call):
    if not mandatory_channels:
        bot.answer_callback_query(call.id, "❌ No mandatory channels.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    for channel_id, channel_info in mandatory_channels.items():
        channel_name = channel_info.get('name', 'Unknown')
        button_text = f"🗑️ {channel_name}"
        markup.add(types.InlineKeyboardButton(button_text, callback_data=f'remove_channel_{channel_id}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='manage_mandatory_channels'))
    try:
        bot.edit_message_text("📢 Choose channel to delete:",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=markup)
    except Exception as e:
        logger.error(f"Error showing remove channel menu: {e}")

def process_remove_channel(call):
    channel_id = call.data.replace('remove_channel_', '')
    if channel_id in mandatory_channels:
        channel_name = mandatory_channels[channel_id].get('name', 'Unknown')
        if remove_mandatory_channel_db(channel_id):
            bot.answer_callback_query(call.id, f"✅ Channel deleted: {channel_name}")
            try:
                bot.edit_message_text(f"✅ Mandatory channel deleted: **{channel_name}**",
                                      call.message.chat.id, call.message.message_id,
                                      reply_markup=create_mandatory_channels_menu(), parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Error updating message after channel removal: {e}")
        else:
            bot.answer_callback_query(call.id, "❌ Failed to delete channel.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "❌ Channel not found.", show_alert=True)

def list_mandatory_channels_callback(call):
    bot.answer_callback_query(call.id)
    if not mandatory_channels:
        message_text = "📢 **No mandatory channels currently**"
    else:
        message_text = "📢 **Mandatory Channels:**\n\n"
        for channel_id, channel_info in mandatory_channels.items():
            channel_name = channel_info.get('name', 'Unknown')
            channel_username = channel_info.get('username', 'No username')
            message_text += f"• **{channel_name}**\n  {channel_username or channel_id}\n\n"
    try:
        bot.edit_message_text(message_text, call.message.chat.id, call.message.message_id,
                              reply_markup=create_mandatory_channels_menu(), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error listing channels: {e}")

def check_subscription_status_callback(call):
    user_id = call.from_user.id
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if is_subscribed or user_id in admin_ids:
        bot.answer_callback_query(call.id, "✅ You are subscribed to all required channels!", show_alert=True)
        try:
            _logic_send_welcome(call.message)
        except:
            back_to_main_callback(call)
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined all required channels yet!", show_alert=True)
        subscription_message, markup = create_subscription_check_message(not_joined)
        try:
            bot.edit_message_text(subscription_message, call.message.chat.id,
                                  call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error updating subscription message: {e}")

def approve_bypass_callback(call):
    req_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    success, msg = approve_bypass_request(req_id, admin_id)
    if success:
        bot.answer_callback_query(call.id, "✅ Approved and started.")
        bot.edit_message_text(f"✅ Bypass request #{req_id} approved and started.", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, f"❌ Failed: {msg}", show_alert=True)

def reject_bypass_callback(call):
    req_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id
    success, msg = reject_bypass_request(req_id, admin_id)
    if success:
        bot.answer_callback_query(call.id, "❌ Rejected and deleted.")
        bot.edit_message_text(f"❌ Bypass request #{req_id} rejected.", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, f"❌ Failed: {msg}", show_alert=True)

# --- Plan system: show plans to user ---
def show_plans_to_user(chat_id, user_id):
    groups = [g for g in plan_groups_cache.values() if g['status'] == 'active']
    if not groups:
        bot.send_message(chat_id, "❌ No plans available at the moment.")
        return
    text = "📋 **Available Plans:**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for group in groups:
        prices = get_plan_prices_for_group(group['id'])
        if not prices:
            continue
        text += f"*{group['name']}* (Bots: {group['bot_limit']}, RAM: {group['ram_limit']} MiB)\n"
        text += f"📝 {group['description']}\n"
        markup.add(types.InlineKeyboardButton(f"View {group['name']} Plans", callback_data=f"buy_plan_group_{group['id']}"))
        text += "\n"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

def callback_buy_plan_group(call):
    user_id = call.from_user.id
    parts = call.data.split('_')
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid callback data.")
        return
    group_id = int(parts[3])
    group = get_plan_group(group_id)
    if not group or group['status'] != 'active':
        bot.answer_callback_query(call.id, "Plan not available.")
        return
    prices = get_plan_prices_for_group(group_id)
    if not prices:
        bot.answer_callback_query(call.id, "No prices for this plan.")
        return
    text = f"📋 **{group['name']} Plans**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    for price in prices:
        duration = price['duration_months']
        price_display = get_price_display(price['price_inr'])
        text += f"• {duration} month(s): {price_display}\n"
        markup.add(types.InlineKeyboardButton(f"{duration} month(s)", callback_data=f"buy_duration_{group_id}_{price['id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_buy_duration(call):
    user_id = call.from_user.id
    parts = call.data.split('_')
    # Format: buy_duration_{group_id}_{price_id}
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid callback data.")
        return
    group_id = int(parts[2])
    price_id = int(parts[3])
    group = get_plan_group(group_id)
    if not group or group['status'] != 'active':
        bot.answer_callback_query(call.id, "Plan not available.")
        return
    price = None
    for p in plan_prices_cache.values():
        if p['id'] == price_id:
            price = p
            break
    if not price:
        bot.answer_callback_query(call.id, "Price not found.")
        return
    amount = price['price_inr']
    duration_months = price['duration_months']
    initiate_purchase(user_id, group_id, price_id, amount, duration_months, call.message.chat.id)
    bot.answer_callback_query(call.id)

def initiate_purchase(user_id, group_id, price_id, amount, duration_months, chat_id):
    group = get_plan_group(group_id)
    if not group:
        bot.send_message(chat_id, "❌ Plan not available.")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    balance = get_wallet_balance(user_id)
    if balance >= amount:
        markup.add(types.InlineKeyboardButton("💳 Pay from Wallet", callback_data=f"pay_wallet_{group_id}_{price_id}"))
    if zapupi_settings.get('enabled'):
        markup.add(types.InlineKeyboardButton("💲 Pay with Zapupi", callback_data=f"pay_zapupi_{group_id}_{price_id}"))
    if binance_manual_settings.get('enabled'):
        markup.add(types.InlineKeyboardButton("🔶 Binance Manual", callback_data=f"pay_binance_manual_{group_id}_{price_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Cancel", callback_data="cancel_purchase"))
    price_display = get_price_display(amount)
    text = f"💳 **Purchase {group['name']} ({duration_months} months)**\nPrice: {price_display}\nChoose payment method:"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

def handle_payment_gateway(user_id, group_id, price_id, gateway, chat_id):
    group = get_plan_group(group_id)
    if not group:
        bot.send_message(chat_id, "❌ Plan not found.")
        return
    price = None
    for p in plan_prices_cache.values():
        if p['id'] == price_id:
            price = p
            break
    if not price:
        bot.send_message(chat_id, "❌ Price not found.")
        return
    amount = price['price_inr']
    duration_months = price['duration_months']
    order_id = generate_transaction_id()
    txn_db_id = create_transaction(user_id, amount, gateway, order_id, plan_id=price_id, txn_type='plan', duration_months=duration_months, group_id=group_id)
    if gateway == 'zapupi':
        txn_id, payment_url = create_zapupi_order(user_id, amount, order_id, plan_id=group_id, txn_type='plan', duration_months=duration_months)
        if not txn_id:
            bot.send_message(chat_id, f"❌ Failed to create Zapupi order: {payment_url}")
            return
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Pay Now", url=payment_url))
        markup.add(types.InlineKeyboardButton("✅ I've Paid (Verify)", callback_data=f"verify_zapupi_{order_id}"))
        bot.send_message(chat_id, f"🔗 Pay via Zapupi: {payment_url}\nOrder ID: `{order_id}`\nAfter payment, click 'I've Paid'.", reply_markup=markup, parse_mode='Markdown')
    elif gateway == 'binance_manual':
        address = binance_manual_settings.get('address', 'Not set')
        binance_id = binance_manual_settings.get('binance_id', 'Not set')
        trc_address = binance_manual_settings.get('trc_address', 'Not set')
        if not address:
            bot.send_message(chat_id, "❌ Binance manual payment is not configured by admin.")
            return
        markup = types.InlineKeyboardMarkup()
        if binance_id and binance_id != 'Not set':
            markup.add(types.InlineKeyboardButton("📋 Copy Binance ID", callback_data=f"copy_binance_id_{order_id}"))
        if trc_address and trc_address != 'Not set':
            markup.add(types.InlineKeyboardButton("📋 Copy TRC Address", callback_data=f"copy_trc_address_{order_id}"))
        markup.add(types.InlineKeyboardButton("✅ I've Paid (Submit TXID)", callback_data=f"submit_binance_manual_{order_id}"))
        text = f"💳 **Binance Manual Payment**\n\nSend ₹{amount:.2f} (≈ ${amount/EXCHANGE_RATE:.2f} USDT) to the following Binance address:\n`{address}`\n\n"
        if binance_id and binance_id != 'Not set':
            text += f"Binance ID: `{binance_id}`\n"
        if trc_address and trc_address != 'Not set':
            text += f"TRC Address: `{trc_address}`\n"
        text += "\nAfter payment, click the button below and provide the transaction ID and screenshot."
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
    elif gateway == 'wallet':
        success, msg = deduct_wallet(user_id, amount, f"Plan purchase: {group['name']} {duration_months} months")
        if not success:
            bot.send_message(chat_id, f"❌ Wallet payment failed: {msg}")
            return
        update_transaction_status(txn_db_id, 'completed', {'payment_method': 'wallet'})
        success2, result = complete_transaction(order_id, user_id, group_id, amount, 'plan', duration_months)
        if success2:
            bot.send_message(chat_id, f"✅ Payment successful! {result}")
            for admin in admin_ids:
                try:
                    bot.send_message(admin, f"💰 Plan purchase: User {user_id} bought {group['name']} {duration_months} months via wallet.")
                except:
                    pass
        else:
            bot.send_message(chat_id, f"❌ Failed to activate: {result}")

# --- Payment callbacks for plan purchase ---
def callback_pay_wallet(call):
    user_id = call.from_user.id
    parts = call.data.split('_')
    group_id = int(parts[2])
    price_id = int(parts[3])
    handle_payment_gateway(user_id, group_id, price_id, 'wallet', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_pay_zapupi(call):
    user_id = call.from_user.id
    parts = call.data.split('_')
    group_id = int(parts[2])
    price_id = int(parts[3])
    handle_payment_gateway(user_id, group_id, price_id, 'zapupi', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_pay_binance_manual(call):
    user_id = call.from_user.id
    parts = call.data.split('_')
    group_id = int(parts[2])
    price_id = int(parts[3])
    handle_payment_gateway(user_id, group_id, price_id, 'binance_manual', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_verify_zapupi(call):
    user_id = call.from_user.id
    order_id = call.data.split('_')[2]
    verify_payment_manually(user_id, order_id, 'zapupi', call.message.chat.id)
    bot.answer_callback_query(call.id)

def verify_payment_manually(user_id, transaction_id, gateway, chat_id):
    txn = get_transaction_by_id(transaction_id)
    if not txn:
        bot.send_message(chat_id, "❌ Transaction not found.")
        return
    txn_db_id, user_id_db, plan_id, amount, status, txn_type = txn
    if status == 'completed':
        bot.send_message(chat_id, "✅ This transaction is already completed.")
        return
    if gateway == 'zapupi':
        success, msg = verify_zapupi_order(transaction_id)
    else:
        bot.send_message(chat_id, "❌ Unsupported gateway.")
        return
    if success:
        update_transaction_status(txn_db_id, 'completed')
        # Get duration and group_id from payment_details
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT payment_details FROM transactions WHERE id = ?', (txn_db_id,))
        row = c.fetchone()
        conn.close()
        details = json.loads(row[0]) if row and row[0] else {}
        duration_months = details.get('duration_months', 1)
        group_id = details.get('group_id', plan_id)
        if not group_id:
            conn2 = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c2 = conn2.cursor()
            c2.execute('SELECT group_id FROM plan_prices WHERE id = ?', (plan_id,))
            row2 = c2.fetchone()
            conn2.close()
            if row2:
                group_id = row2[0]
        success2, result = complete_transaction(transaction_id, user_id_db, group_id, amount, txn_type, duration_months)
        if success2:
            bot.send_message(chat_id, f"✅ Payment verified! {result}")
            for admin in admin_ids:
                try:
                    bot.send_message(admin, f"💰 Payment verified: User {user_id_db}, Plan {plan_id}, Amount ₹{amount}")
                except:
                    pass
        else:
            bot.send_message(chat_id, f"❌ Failed to activate: {result}")
    else:
        bot.send_message(chat_id, f"❌ Payment not confirmed yet. Status: {msg}\nPlease wait or contact support.")

def callback_cancel_purchase(call):
    bot.answer_callback_query(call.id, "Purchase cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)

# --- Admin Plan Management Callbacks ---
def admin_plan_management_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    bot.edit_message_text("📋 Plan Management\nCreate, edit, delete plan groups and prices.", call.message.chat.id, call.message.message_id, reply_markup=create_plan_management_menu())
    bot.answer_callback_query(call.id)

def admin_payment_settings_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    bot.edit_message_text("💲 Payment Settings\nConfigure payment gateways.", call.message.chat.id, call.message.message_id, reply_markup=create_payment_settings_menu())
    bot.answer_callback_query(call.id)

# --- Create Plan Group ---
def callback_admin_create_plan_group(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "📝 Create new plan group.\nSend details in format:\n`name | bot_limit | ram_limit | description`\nExample: `Starter | 2 | 256 | 2 bots, 256 MiB RAM`\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_admin_create_plan_group)
    bot.answer_callback_query(call.id)

def process_admin_create_plan_group(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    parts = message.text.split('|')
    if len(parts) != 4:
        bot.reply_to(message, "❌ Invalid format. Use: `name | bot_limit | ram_limit | description`")
        return
    name = parts[0].strip()
    bot_limit = int(parts[1].strip())
    ram_limit = int(parts[2].strip())
    description = parts[3].strip()
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT INTO plan_groups (name, bot_limit, ram_limit, description, status) VALUES (?, ?, ?, ?, "active")',
              (name, bot_limit, ram_limit, description))
    conn.commit()
    conn.close()
    load_data()
    bot.reply_to(message, f"✅ Plan group '{name}' created!")

def callback_admin_view_plan_groups(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    groups = list(plan_groups_cache.values())
    if not groups:
        bot.edit_message_text("No plan groups.", call.message.chat.id, call.message.message_id)
        return
    text = "📋 **Plan Groups**\n\n"
    for g in groups:
        text += f"ID: {g['id']} - {g['name']} - Bots: {g['bot_limit']} - RAM: {g['ram_limit']}MiB - {g['status']}\n"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_admin_edit_plan_group(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    groups = list(plan_groups_cache.values())
    if not groups:
        bot.edit_message_text("No plan groups.", call.message.chat.id, call.message.message_id)
        return
    text = "📋 **Select a plan group to edit:**\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for g in groups:
        markup.add(types.InlineKeyboardButton(f"{g['name']} (ID: {g['id']})", callback_data=f"edit_plan_group_detail_{g['id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_plan_management"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def handle_edit_plan_group_detail(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    # Data: edit_plan_group_detail_{group_id}
    parts = call.data.split('_')
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    group_id = int(parts[4])
    group = plan_groups_cache.get(group_id)
    if not group:
        bot.answer_callback_query(call.id, "Plan group not found.")
        return
    text = f"✏️ **Edit Plan Group: {group['name']}**\n\n"
    text += f"ID: {group['id']}\n"
    text += f"Name: {group['name']}\n"
    text += f"Bot Limit: {group['bot_limit']}\n"
    text += f"RAM Limit: {group['ram_limit']} MiB\n"
    text += f"Description: {group['description']}\n"
    text += f"Status: {group['status']}\n\n"
    text += "Click a field to edit:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("Name", callback_data=f"plan_group_edit_field_{group_id}_name"),
               types.InlineKeyboardButton("Bot Limit", callback_data=f"plan_group_edit_field_{group_id}_bot_limit"))
    markup.add(types.InlineKeyboardButton("RAM Limit", callback_data=f"plan_group_edit_field_{group_id}_ram_limit"),
               types.InlineKeyboardButton("Description", callback_data=f"plan_group_edit_field_{group_id}_description"))
    markup.add(types.InlineKeyboardButton("Status", callback_data=f"plan_group_edit_field_{group_id}_status"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_edit_plan_group"))
    text = re.sub(r'([*_`\\])', r'\\\1', text)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def handle_plan_group_edit_field(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    parts = call.data.split('_')
    # Format: plan_group_edit_field_{group_id}_{field}
    if len(parts) != 6:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    group_id = int(parts[4])
    field = parts[5]
    field_map = {
        'bot_limit': 'bot_limit',
        'ram_limit': 'ram_limit',
        'description': 'description',
        'status': 'status',
        'name': 'name'
    }
    actual_field = field_map.get(field, field)
    msg = bot.send_message(call.message.chat.id, f"Send new value for **{field}**:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_plan_group_edit_field_value, group_id, actual_field, field, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

def process_plan_group_edit_field_value(message, group_id, actual_field, display_field, chat_id, msg_id):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Edit cancelled.")
        try:
            bot.delete_message(chat_id, msg_id)
        except:
            pass
        return
    value = message.text.strip()
    try:
        if actual_field in ['bot_limit', 'ram_limit']:
            value = int(value)
        elif actual_field == 'status':
            if value.lower() not in ['active', 'inactive']:
                bot.reply_to(message, "❌ Status must be 'active' or 'inactive'.")
                return
            value = value.lower()
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute(f'UPDATE plan_groups SET {actual_field} = ?, updated_at = datetime("now") WHERE id = ?', (value, group_id))
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Plan group field '{display_field}' updated.")
        # Refresh detail
        group = plan_groups_cache.get(group_id)
        if group:
            text = f"✏️ **Edit Plan Group: {group['name']}**\n\n"
            text += f"ID: {group['id']}\n"
            text += f"Name: {group['name']}\n"
            text += f"Bot Limit: {group['bot_limit']}\n"
            text += f"RAM Limit: {group['ram_limit']} MiB\n"
            text += f"Description: {group['description']}\n"
            text += f"Status: {group['status']}\n\n"
            text += "Click a field to edit:"
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("Name", callback_data=f"plan_group_edit_field_{group_id}_name"),
                       types.InlineKeyboardButton("Bot Limit", callback_data=f"plan_group_edit_field_{group_id}_bot_limit"))
            markup.add(types.InlineKeyboardButton("RAM Limit", callback_data=f"plan_group_edit_field_{group_id}_ram_limit"),
                       types.InlineKeyboardButton("Description", callback_data=f"plan_group_edit_field_{group_id}_description"))
            markup.add(types.InlineKeyboardButton("Status", callback_data=f"plan_group_edit_field_{group_id}_status"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_edit_plan_group"))
            text = re.sub(r'([*_`\\])', r'\\\1', text)
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def callback_admin_delete_plan_group(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "🗑 Enter plan group ID to delete:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_admin_delete_plan_group)
    bot.answer_callback_query(call.id)

def process_admin_delete_plan_group(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        group_id = int(message.text.strip())
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('DELETE FROM plan_groups WHERE id = ?', (group_id,))
        c.execute('DELETE FROM plan_prices WHERE group_id = ?', (group_id,))
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Plan group {group_id} deleted.")
    except ValueError:
        bot.reply_to(message, "❌ Invalid ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# --- Plan Price Management ---
def callback_admin_add_plan_price(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    groups = list(plan_groups_cache.values())
    if not groups:
        bot.edit_message_text("No plan groups. Create a group first.", call.message.chat.id, call.message.message_id)
        return
    text = "📋 **Select a plan group to add price:**\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for g in groups:
        markup.add(types.InlineKeyboardButton(f"{g['name']} (ID: {g['id']})", callback_data=f"add_price_group_{g['id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_plan_management"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_price_group_'))
def add_price_group_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    group_id = int(call.data.split('_')[3])
    msg = bot.send_message(call.message.chat.id, f"Send price details for group ID {group_id} in format:\n`duration_months | price_inr`\nExample: `1 | 60`\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_admin_add_plan_price, group_id)
    bot.answer_callback_query(call.id)

def process_admin_add_plan_price(message, group_id):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    parts = message.text.split('|')
    if len(parts) != 2:
        bot.reply_to(message, "❌ Invalid format. Use: `duration_months | price_inr`")
        return
    duration = int(parts[0].strip())
    price = float(parts[1].strip())
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO plan_prices (group_id, duration_months, price_inr) VALUES (?, ?, ?)',
                  (group_id, duration, price))
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Price added for group {group_id}: {duration} months for ₹{price}")
    except sqlite3.IntegrityError:
        bot.reply_to(message, "❌ Price for this duration already exists for this group.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def callback_admin_view_plan_prices(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    prices = list(plan_prices_cache.values())
    if not prices:
        bot.edit_message_text("No plan prices.", call.message.chat.id, call.message.message_id)
        return
    text = "📋 **Plan Prices**\n\n"
    for p in prices:
        group = plan_groups_cache.get(p['group_id'])
        group_name = group['name'] if group else f"Group {p['group_id']}"
        text += f"ID: {p['id']} - Group: {group_name} - {p['duration_months']} months - ₹{p['price_inr']}\n"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_admin_edit_plan_price(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    prices = list(plan_prices_cache.values())
    if not prices:
        bot.edit_message_text("No plan prices.", call.message.chat.id, call.message.message_id)
        return
    text = "📋 **Select a price to edit:**\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in prices:
        group = plan_groups_cache.get(p['group_id'])
        group_name = group['name'] if group else f"Group {p['group_id']}"
        markup.add(types.InlineKeyboardButton(f"{group_name} {p['duration_months']}m (ID:{p['id']})", callback_data=f"edit_plan_price_detail_{p['id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_plan_management"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def handle_edit_plan_price_detail(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    # Data: edit_plan_price_detail_{price_id}
    parts = call.data.split('_')
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    price_id = int(parts[4])
    price = plan_prices_cache.get(price_id)
    if not price:
        bot.answer_callback_query(call.id, "Price not found.")
        return
    group = plan_groups_cache.get(price['group_id'])
    group_name = group['name'] if group else f"Group {price['group_id']}"
    text = f"✏️ **Edit Price: {group_name} {price['duration_months']} months**\n\n"
    text += f"ID: {price['id']}\n"
    text += f"Duration: {price['duration_months']} months\n"
    text += f"Price: ₹{price['price_inr']}\n\n"
    text += "Click field to edit:"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Price", callback_data=f"plan_price_edit_field_{price_id}_price"))
    markup.add(types.InlineKeyboardButton("Duration", callback_data=f"plan_price_edit_field_{price_id}_duration"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_edit_plan_price"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def handle_plan_price_edit_field(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    parts = call.data.split('_')
    # Format: plan_price_edit_field_{price_id}_{field}
    if len(parts) != 6:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    price_id = int(parts[4])
    field = parts[5]
    msg = bot.send_message(call.message.chat.id, f"Send new value for **{field}**:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_plan_price_edit_field_value, price_id, field, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

def process_plan_price_edit_field_value(message, price_id, field, chat_id, msg_id):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Edit cancelled.")
        try:
            bot.delete_message(chat_id, msg_id)
        except:
            pass
        return
    value = message.text.strip()
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        if field == 'price':
            value = float(value)
            c.execute('UPDATE plan_prices SET price_inr = ? WHERE id = ?', (value, price_id))
        elif field == 'duration':
            value = int(value)
            # Check if another price with same group and duration exists
            c.execute('SELECT group_id FROM plan_prices WHERE id = ?', (price_id,))
            row = c.fetchone()
            if row:
                group_id = row[0]
                c.execute('SELECT id FROM plan_prices WHERE group_id = ? AND duration_months = ? AND id != ?', (group_id, value, price_id))
                if c.fetchone():
                    bot.reply_to(message, "❌ Another price with this duration already exists for this group.")
                    conn.close()
                    return
            c.execute('UPDATE plan_prices SET duration_months = ? WHERE id = ?', (value, price_id))
        else:
            bot.reply_to(message, "❌ Invalid field.")
            conn.close()
            return
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Price field '{field}' updated.")
        # Refresh detail
        price = plan_prices_cache.get(price_id)
        if price:
            group = plan_groups_cache.get(price['group_id'])
            group_name = group['name'] if group else f"Group {price['group_id']}"
            text = f"✏️ **Edit Price: {group_name} {price['duration_months']} months**\n\n"
            text += f"ID: {price['id']}\n"
            text += f"Duration: {price['duration_months']} months\n"
            text += f"Price: ₹{price['price_inr']}\n\n"
            text += "Click field to edit:"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Price", callback_data=f"plan_price_edit_field_{price_id}_price"))
            markup.add(types.InlineKeyboardButton("Duration", callback_data=f"plan_price_edit_field_{price_id}_duration"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_edit_plan_price"))
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def callback_admin_delete_plan_price(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "🗑 Enter plan price ID to delete:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_admin_delete_plan_price)
    bot.answer_callback_query(call.id)

def process_admin_delete_plan_price(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        price_id = int(message.text.strip())
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('DELETE FROM plan_prices WHERE id = ?', (price_id,))
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Plan price {price_id} deleted.")
    except ValueError:
        bot.reply_to(message, "❌ Invalid ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# --- Zapupi Settings ---
def callback_admin_zapupi_settings(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    current = zapupi_settings
    status = "✅ Enabled" if current.get('enabled') else "❌ Disabled"
    api_key = current.get('api_key')
    if api_key:
        masked_key = f"{api_key[:4]}...{api_key[-4:]}"
    else:
        masked_key = "N/A"
    text = f"💲 **Zapupi Settings**\n\nAPI Key: {masked_key}\nStatus: {status}\n\nChoose action:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ Set API Key", callback_data="zapupi_set_key"),
               types.InlineKeyboardButton("🔄 Toggle Enable", callback_data="zapupi_toggle"),
               types.InlineKeyboardButton("🗑 Delete Key", callback_data="zapupi_delete"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_zapupi_set_key(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "🔑 Send Zapupi API Key (zap_key):\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_zapupi_set_key)
    bot.answer_callback_query(call.id)

def process_zapupi_set_key(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    api_key = message.text.strip()
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM zapupi_settings')
    c.execute('INSERT INTO zapupi_settings (api_key, gateway_enabled) VALUES (?, 1)', (api_key,))
    conn.commit()
    conn.close()
    load_data()
    bot.reply_to(message, "✅ Zapupi API key saved and gateway enabled.")

def callback_zapupi_toggle(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    new_status = not zapupi_settings.get('enabled', False)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE zapupi_settings SET gateway_enabled = ?', (1 if new_status else 0,))
    conn.commit()
    conn.close()
    load_data()
    bot.answer_callback_query(call.id, f"Zapupi {'enabled' if new_status else 'disabled'}.")
    callback_admin_zapupi_settings(call)

def callback_zapupi_delete(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM zapupi_settings')
    conn.commit()
    conn.close()
    load_data()
    bot.answer_callback_query(call.id, "Zapupi API key deleted.")
    callback_admin_zapupi_settings(call)

# --- Binance Manual Settings ---
def admin_binance_manual_settings_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    current = binance_manual_settings
    status = "✅ Enabled" if current.get('enabled') else "❌ Disabled"
    address = current.get('address', 'Not set')
    binance_id = current.get('binance_id', 'Not set')
    trc_address = current.get('trc_address', 'Not set')
    text = f"🔶 **Binance Manual Settings**\n\nAddress: `{address}`\nBinance ID: `{binance_id}`\nTRC Address: `{trc_address}`\nStatus: {status}\n\nChoose action:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ Set Address", callback_data="binance_manual_set_address"),
               types.InlineKeyboardButton("🔄 Toggle Enable", callback_data="binance_manual_toggle"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_payment_settings"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def binance_manual_set_address_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "🔑 Send Binance address/account info for manual payments.\nFormat: `address | binance_id | trc_address` (use 'skip' for optional fields).\nExample: `your_binance_address | your_binance_id | TRC...`\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_binance_manual_set_address)
    bot.answer_callback_query(call.id)

def process_binance_manual_set_address(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    parts = message.text.split('|')
    if len(parts) != 3:
        bot.reply_to(message, "❌ Invalid format. Use: `address | binance_id | trc_address`")
        return
    address = parts[0].strip()
    binance_id = parts[1].strip()
    trc_address = parts[2].strip()
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM binance_manual_settings')
    c.execute('INSERT INTO binance_manual_settings (address, binance_id, trc_address, enabled) VALUES (?, ?, ?, 1)', (address, binance_id if binance_id != 'skip' else '', trc_address if trc_address != 'skip' else ''))
    conn.commit()
    conn.close()
    load_data()
    bot.reply_to(message, "✅ Binance manual settings saved and enabled.")

def binance_manual_toggle_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    new_status = not binance_manual_settings.get('enabled', False)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE binance_manual_settings SET enabled = ?', (1 if new_status else 0,))
    conn.commit()
    conn.close()
    load_data()
    bot.answer_callback_query(call.id, f"Binance manual {'enabled' if new_status else 'disabled'}.")
    admin_binance_manual_settings_callback(call)

# --- Transactions and Revenue ---
def callback_admin_transactions(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, user_id, gateway, amount, currency, status, created_at FROM transactions ORDER BY created_at DESC LIMIT 20')
    rows = c.fetchall()
    conn.close()
    if not rows:
        text = "No transactions found."
    else:
        text = "📊 **Recent Transactions**\n\n"
        for row in rows:
            text += f"ID: {row[0]}, User: {row[1]}, Gateway: {row[2]}, Amount: {row[3]} {row[4]}, Status: {row[5]}, Date: {row[6]}\n"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_admin_revenue(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT SUM(amount) FROM transactions WHERE status = "completed"')
    total = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(*) FROM transactions WHERE status = "completed"')
    count = c.fetchone()[0] or 0
    c.execute('SELECT SUM(amount) FROM transactions WHERE status = "completed" AND gateway = "zapupi"')
    zapupi_total = c.fetchone()[0] or 0
    c.execute('SELECT SUM(amount) FROM transactions WHERE status = "completed" AND gateway = "binance_manual"')
    manual_total = c.fetchone()[0] or 0
    conn.close()
    text = f"📈 **Revenue Report**\n\nTotal Revenue: ₹{total:.2f}\nTotal Transactions: {count}\n\nZapupi: ₹{zapupi_total:.2f}\nBinance Manual: ₹{manual_total:.2f}"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

# --- Wallet Management ---
def callback_admin_wallet_management(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    bot.edit_message_text("💰 Wallet Management\nChoose action:", call.message.chat.id, call.message.message_id, reply_markup=create_wallet_management_menu())
    bot.answer_callback_query(call.id)

def callback_admin_add_balance(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "➕ Enter User ID and amount to add (e.g., `12345678 100`)\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_admin_add_balance)
    bot.answer_callback_query(call.id)

def process_admin_add_balance(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError("Format: user_id amount")
        user_id = int(parts[0])
        amount = float(parts[1])
        if user_id <= 0 or amount <= 0:
            raise ValueError("ID and amount must be positive")
        update_wallet_balance(user_id, amount, f"Admin added ₹{amount:.2f}", 'credit')
        bot.reply_to(message, f"✅ Added ₹{amount:.2f} to user {user_id}'s wallet. New balance: ₹{get_wallet_balance(user_id):.2f}")
        try:
            bot.send_message(user_id, f"💰 Admin added ₹{amount:.2f} to your balance. New balance: ₹{get_wallet_balance(user_id):.2f}")
        except:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

def callback_admin_deduct_balance(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "➖ Enter User ID and amount to deduct (e.g., `12345678 50`)\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_admin_deduct_balance)
    bot.answer_callback_query(call.id)

def process_admin_deduct_balance(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError("Format: user_id amount")
        user_id = int(parts[0])
        amount = float(parts[1])
        if user_id <= 0 or amount <= 0:
            raise ValueError("ID and amount must be positive")
        success, msg = deduct_wallet(user_id, amount, f"Admin deducted ₹{amount:.2f}")
        if success:
            bot.reply_to(message, f"✅ Deducted ₹{amount:.2f} from user {user_id}'s wallet. New balance: ₹{get_wallet_balance(user_id):.2f}")
            try:
                bot.send_message(user_id, f"💰 Admin deducted ₹{amount:.2f} from your balance. New balance: ₹{get_wallet_balance(user_id):.2f}")
            except:
                pass
        else:
            bot.reply_to(message, f"❌ Failed: {msg}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

def callback_admin_check_balance(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "💰 Enter User ID to check wallet balance\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_admin_check_balance)
    bot.answer_callback_query(call.id)

def process_admin_check_balance(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        user_id = int(message.text.strip())
        if user_id <= 0:
            raise ValueError("ID must be positive")
        balance = get_wallet_balance(user_id)
        bot.reply_to(message, f"💰 User {user_id} wallet balance: ₹{balance:.2f}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

def callback_admin_wallet_transactions(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "📊 Enter User ID to view wallet transactions\n/cancel to cancel")
    bot.register_next_step_handler(msg, process_admin_wallet_transactions)
    bot.answer_callback_query(call.id)

def process_admin_wallet_transactions(message):
    admin_id = message.from_user.id
    if admin_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        user_id = int(message.text.strip())
        if user_id <= 0:
            raise ValueError("ID must be positive")
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT id, amount, type, description, created_at FROM wallet_transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 20', (user_id,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.reply_to(message, f"No transactions found for user {user_id}.")
            return
        text = f"📊 **Wallet Transactions for {user_id}**\n\n"
        for row in rows:
            text += f"ID: {row[0]}, Amount: {row[1]:.2f}, Type: {row[2]}, Desc: {row[3]}, Date: {row[4]}\n"
        bot.reply_to(message, text, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# --- User wallet callbacks ---
def callback_wallet_balance(call):
    user_id = call.from_user.id
    balance = get_wallet_balance(user_id)
    bot.answer_callback_query(call.id, f"💰 Balance: ₹{balance:.2f}", show_alert=True)

def callback_wallet_transactions(call):
    user_id = call.from_user.id
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, amount, type, description, created_at FROM wallet_transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10', (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        text = "No transactions found."
    else:
        text = "📊 **Your Wallet Transactions (Last 10)**\n\n"
        for row in rows:
            text += f"ID: {row[0]}, Amount: {row[1]:.2f}, Type: {row[2]}, Desc: {row[3]}, Date: {row[4]}\n"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_add_balance(call):
    user_id = call.from_user.id
    if is_user_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned.", show_alert=True)
        return
    is_subscribed, not_joined = check_mandatory_subscription(user_id)
    if not is_subscribed and user_id not in admin_ids:
        subscription_message, markup = create_subscription_check_message(not_joined)
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(subscription_message, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            bot.send_message(call.message.chat.id, subscription_message, reply_markup=markup, parse_mode='Markdown')
        return
    msg = bot.send_message(call.message.chat.id, "💵 Enter amount to add (minimum ₹10):\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_add_balance_amount_callback)

def process_add_balance_amount_callback(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled.")
        return
    try:
        amount = float(message.text.strip())
        if amount < 10:
            bot.reply_to(message, "⚠️ Minimum amount is ₹10. Enter a larger amount or /cancel.")
            return
        pending_add_balance[user_id] = amount
        markup = create_add_balance_menu()
        bot.reply_to(message, f"💰 Amount: ₹{amount:.2f}\nChoose payment method:", reply_markup=markup)
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid amount. Enter a number (e.g., 100).")
        return

def callback_add_balance_zapupi(call):
    user_id = call.from_user.id
    if user_id not in pending_add_balance:
        bot.answer_callback_query(call.id, "⚠️ No pending amount. Start again with /addbalance.", show_alert=True)
        return
    amount = pending_add_balance.pop(user_id)
    initiate_add_balance_payment(user_id, amount, 'zapupi', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_add_balance_binance_manual(call):
    user_id = call.from_user.id
    if user_id not in pending_add_balance:
        bot.answer_callback_query(call.id, "⚠️ No pending amount. Start again with /addbalance.", show_alert=True)
        return
    amount = pending_add_balance.pop(user_id)
    initiate_add_balance_payment(user_id, amount, 'binance_manual', call.message.chat.id)
    bot.answer_callback_query(call.id)

# --- Binance Manual submission callbacks (two-step flow) ---
def submit_binance_manual(call):
    user_id = call.from_user.id
    order_id = call.data.split('_')[3]
    if not hasattr(bot, 'binance_txid_pending'):
        bot.binance_txid_pending = {}
    bot.binance_txid_pending[user_id] = {'order_id': order_id, 'chat_id': call.message.chat.id}
    msg = bot.send_message(call.message.chat.id, "📤 Please send the transaction ID (TXID) as a text message.\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_binance_txid)
    bot.answer_callback_query(call.id)

def process_binance_txid(message):
    user_id = message.from_user.id
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        if hasattr(bot, 'binance_txid_pending') and user_id in bot.binance_txid_pending:
            del bot.binance_txid_pending[user_id]
        return
    txid = message.text.strip()
    if not txid:
        bot.reply_to(message, "❌ Please send a valid TXID.")
        return
    if user_id not in bot.binance_txid_pending:
        bot.reply_to(message, "❌ Session expired. Please start again.")
        return
    bot.binance_txid_pending[user_id]['txid'] = txid
    msg = bot.send_message(message.chat.id, "📸 Now send a screenshot of the payment (photo).\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_binance_screenshot)

def process_binance_screenshot(message):
    user_id = message.from_user.id
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        if hasattr(bot, 'binance_txid_pending') and user_id in bot.binance_txid_pending:
            del bot.binance_txid_pending[user_id]
        return
    if not message.photo:
        bot.reply_to(message, "❌ Please send a screenshot (photo).")
        return
    if not hasattr(bot, 'binance_txid_pending') or user_id not in bot.binance_txid_pending:
        bot.reply_to(message, "❌ Session expired. Please start again.")
        return
    data = bot.binance_txid_pending.pop(user_id)
    order_id = data['order_id']
    txid = data['txid']
    file_id = message.photo[-1].file_id

    # Get amount and type from DB
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT amount, type FROM transactions WHERE transaction_id = ?', (order_id,))
    row = c.fetchone()
    conn.close()
    amount = row[0] if row else 0
    txn_type = row[1] if row else 'unknown'
    usd_amount = amount / EXCHANGE_RATE

    if not hasattr(bot, 'pending_binance_manual'):
        bot.pending_binance_manual = {}
    bot.pending_binance_manual[order_id] = {
        'user_id': user_id,
        'txid': txid,
        'photo_id': file_id,
        'amount': amount,
        'usd_amount': usd_amount,
        'type': txn_type,
        'timestamp': datetime.now().isoformat()
    }

    # Notify admins with both currencies
    for admin in admin_ids:
        try:
            caption = (f"🔶 Binance Manual Payment\n"
                       f"Order: {order_id}\n"
                       f"User: {user_id}\n"
                       f"Amount: ₹{amount:.2f} (~ ${usd_amount:.2f} USDT)\n"
                       f"Type: {txn_type}\n"
                       f"TXID: {txid}\n\n"
                       f"Please approve or reject.")
            bot.send_photo(admin, file_id, caption=caption, parse_mode='Markdown')
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_binance_manual_{order_id}"),
                       types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_binance_manual_{order_id}"))
            bot.send_message(admin, "Choose action:", reply_markup=markup)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin}: {e}")
    bot.reply_to(message, "✅ Payment details submitted for admin verification.")

def approve_binance_manual_callback(call):
    order_id = call.data.split('_')[3]
    if not hasattr(bot, 'pending_binance_manual') or order_id not in bot.pending_binance_manual:
        bot.answer_callback_query(call.id, "No pending request.")
        return
    data = bot.pending_binance_manual.pop(order_id)
    user_id = data['user_id']
    amount = data.get('amount', 0)
    txn_type = data.get('type', 'unknown')
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, user_id, amount, type FROM transactions WHERE transaction_id = ? AND gateway = "binance_manual"', (order_id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Transaction not found.")
        return
    txn_id, db_user_id, db_amount, db_txn_type = row
    update_transaction_status(txn_id, 'completed', {'txid': data['txid'], 'admin_approved': True})
    if db_txn_type == 'balance':
        update_wallet_balance(user_id, db_amount, f"Added balance via Binance manual {order_id}", 'credit')
        bot.send_message(user_id, f"✅ Your Binance manual payment of ₹{db_amount:.2f} has been approved. Balance added.")
    elif db_txn_type == 'template':
        c.execute('SELECT id FROM template_purchases WHERE transaction_id = ?', (txn_id,))
        tp_row = c.fetchone()
        if tp_row:
            complete_template_purchase(tp_row[0], user_id, txn_id, db_amount)
        else:
            bot.send_message(user_id, "❌ Template purchase not found.")
    else:  # plan
        # get group_id and duration from payment_details
        c.execute('SELECT payment_details FROM transactions WHERE id = ?', (txn_id,))
        row_details = c.fetchone()
        details = json.loads(row_details[0]) if row_details and row_details[0] else {}
        duration_months = details.get('duration_months', 1)
        group_id = details.get('group_id')
        if not group_id:
            c.execute('SELECT group_id FROM plan_prices WHERE id = ?', (db_txn_type,))  # plan_id is stored as price id
            row2 = c.fetchone()
            if row2:
                group_id = row2[0]
        if group_id:
            success, result = complete_transaction(order_id, user_id, group_id, db_amount, 'plan', duration_months)
            if success:
                bot.send_message(user_id, f"✅ Your Binance manual payment of ₹{db_amount:.2f} has been approved. {result}")
            else:
                bot.send_message(user_id, f"❌ Failed to activate plan: {result}")
        else:
            bot.send_message(user_id, "❌ Could not determine plan group.")
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "Payment approved.")
    for admin in admin_ids:
        try:
            bot.send_message(admin, f"✅ Binance manual payment {order_id} approved for user {user_id}.")
        except:
            pass

def reject_binance_manual_callback(call):
    order_id = call.data.split('_')[3]
    if not hasattr(bot, 'pending_binance_manual') or order_id not in bot.pending_binance_manual:
        bot.answer_callback_query(call.id, "No pending request.")
        return
    data = bot.pending_binance_manual.pop(order_id)
    user_id = data['user_id']
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id FROM transactions WHERE transaction_id = ?', (order_id,))
    row = c.fetchone()
    if row:
        update_transaction_status(row[0], 'failed', {'reason': 'Rejected by admin'})
    conn.close()
    bot.send_message(user_id, "❌ Your Binance manual payment was rejected by admin.")
    bot.answer_callback_query(call.id, "Payment rejected.")
    for admin in admin_ids:
        try:
            bot.send_message(admin, f"❌ Binance manual payment {order_id} rejected.")
        except:
            pass

# --- Template System Functions (no edit after purchase) ---
def show_available_templates(chat_id, user_id):
    templates = [t for t in templates_cache.values() if t['status'] == 'active']
    if not templates:
        bot.send_message(chat_id, "❌ No templates available at the moment.")
        return
    text = "🤖 **Available Bots (Templates):**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    for t in templates:
        price_display = get_price_display(t['price_inr'])
        text += f"*{t['name']}*\n"
        text += f"💰 Price: {price_display}\n"
        text += f"📝 {t['description']}\n"
        if is_valid_url(t.get('demo_video_url')):
            text += f"🎥 [Watch Demo]({t['demo_video_url']})\n"
        text += "\n"
        row_buttons = [types.InlineKeyboardButton(f"View {t['name']}", callback_data=f"template_info_{t['id']}")]
        if is_valid_url(t.get('demo_video_url')):
            row_buttons.append(types.InlineKeyboardButton("🎬 Preview", url=t['demo_video_url']))
        markup.row(*row_buttons)
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

def template_info_callback(call):
    user_id = call.from_user.id
    template_id = int(call.data.split('_')[2])
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    price_display = get_price_display(template['price_inr'])
    text = f"**{template['name']}**\n\n"
    text += f"💰 Price: {price_display}\n"
    text += f"📝 {template['description']}\n"
    if is_valid_url(template.get('demo_video_url')):
        text += f"🎥 [Watch Demo]({template['demo_video_url']})\n"
    text += "\n**Required Information:**\n"
    for param in template['required_params']:
        text += f"• {param.get('label', param['name'])}: {param.get('description', '')}\n"
    text += "\n**IMPORTANT:** Once you purchase this bot and provide parameters, you **cannot** edit them later. If you need to change any parameter, you must purchase a new template (no refunds).\n\nClick below to purchase."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🛒 Purchase This Bot", callback_data=f"buy_template_{template_id}"))
    if is_valid_url(template.get('demo_video_url')):
        markup.add(types.InlineKeyboardButton("🎬 Preview", url=template['demo_video_url']))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="available_bots"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def buy_template_callback(call):
    user_id = call.from_user.id
    template_id = int(call.data.split('_')[2])
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return

    if not get_user_active_plan(user_id) and not get_user_trial(user_id):
        bot.answer_callback_query(call.id, "❌ You need an active hosting plan (or trial) to purchase a bot. Use /plans to buy a plan.", show_alert=True)
        return

    file_limit = get_user_file_limit(user_id)
    if file_limit <= 0:
        bot.answer_callback_query(call.id, "❌ Your current plan has 0 bot slots. Please upgrade.", show_alert=True)
        return
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"⚠️ Bot limit reached ({current_files}/{limit_str}). Delete a bot or upgrade your plan.", show_alert=True)
        return

    required_params = template['required_params']
    if not required_params:
        initiate_template_payment(user_id, template_id, call.message.chat.id, {})
        return
    bot.answer_callback_query(call.id)
    if not hasattr(bot, 'template_purchase_data'):
        bot.template_purchase_data = {}
    bot.template_purchase_data[user_id] = {
        'template_id': template_id,
        'params': {},
        'step': 0,
        'chat_id': call.message.chat.id
    }
    ask_next_template_param(user_id, call.message)

def ask_next_template_param(user_id, message):
    data = bot.template_purchase_data.get(user_id)
    if not data:
        return
    template_id = data['template_id']
    template = templates_cache.get(template_id)
    if not template:
        bot.send_message(message.chat.id, "Template not found.")
        return
    params = template['required_params']
    step = data['step']
    if step >= len(params):
        initiate_template_payment(user_id, template_id, message.chat.id, data['params'])
        del bot.template_purchase_data[user_id]
        return
    param = params[step]
    bot.send_message(message.chat.id, f"Please provide **{param.get('label', param['name'])}**:\n{param.get('description', '')}\nType /cancel to cancel.")
    bot.register_next_step_handler(message, process_template_param, user_id)

def process_template_param(message, user_id):
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Purchase cancelled.")
        if user_id in bot.template_purchase_data:
            del bot.template_purchase_data[user_id]
        return
    data = bot.template_purchase_data.get(user_id)
    if not data:
        return
    param = templates_cache[data['template_id']]['required_params'][data['step']]
    data['params'][param['name']] = message.text.strip()
    data['step'] += 1
    ask_next_template_param(user_id, message)

def initiate_template_payment(user_id, template_id, chat_id, params):
    template = templates_cache.get(template_id)
    if not template:
        bot.send_message(chat_id, "Template not found.")
        return
    amount = template['price_inr']
    order_id = generate_transaction_id()
    txn_db_id = create_transaction(user_id, amount, 'pending', order_id, plan_id=None, txn_type='template')
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''INSERT INTO template_purchases (user_id, template_id, transaction_id, params, status, created_at)
                 VALUES (?, ?, ?, ?, 'pending', datetime("now"))''',
              (user_id, template_id, txn_db_id, json.dumps(params)))
    purchase_id = c.lastrowid
    conn.commit()
    conn.close()
    markup = types.InlineKeyboardMarkup(row_width=2)
    balance = get_wallet_balance(user_id)
    if balance >= amount:
        markup.add(types.InlineKeyboardButton("💳 Pay from Wallet", callback_data=f"pay_template_wallet_{template_id}_{purchase_id}"))
    if zapupi_settings.get('enabled'):
        markup.add(types.InlineKeyboardButton("💲 Pay with Zapupi", callback_data=f"pay_template_zapupi_{template_id}_{purchase_id}"))
    if binance_manual_settings.get('enabled'):
        markup.add(types.InlineKeyboardButton("🔶 Pay with Binance Manual", callback_data=f"pay_template_binance_manual_{template_id}_{purchase_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Cancel", callback_data="cancel_purchase"))
    price_display = get_price_display(amount)
    bot.send_message(chat_id, f"💳 **Purchase Template: {template['name']}**\nPrice: {price_display}\nChoose payment method:", reply_markup=markup, parse_mode='Markdown')

def pay_template_wallet(call):
    parts = call.data.split('_')
    template_id = int(parts[3])
    purchase_id = int(parts[4])
    user_id = call.from_user.id
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    amount = template['price_inr']
    success, msg = deduct_wallet(user_id, amount, f"Template purchase: {template['name']}")
    if not success:
        bot.answer_callback_query(call.id, f"❌ {msg}", show_alert=True)
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT transaction_id FROM template_purchases WHERE id = ?', (purchase_id,))
    row = c.fetchone()
    if row:
        txn_id = row[0]
        update_transaction_status(txn_id, 'completed', {'payment_method': 'wallet'})
        complete_template_purchase(purchase_id, user_id, txn_id, amount)
        bot.send_message(call.message.chat.id, f"✅ Payment successful! Your bot is being created...")
        for admin in admin_ids:
            try:
                bot.send_message(admin, f"💰 Template purchase: User {user_id} bought {template['name']} via wallet.")
            except:
                pass
    else:
        bot.send_message(call.message.chat.id, "❌ Error: Purchase record not found.")
    bot.answer_callback_query(call.id)

def pay_template_zapupi(call):
    parts = call.data.split('_')
    template_id = int(parts[3])
    purchase_id = int(parts[4])
    user_id = call.from_user.id
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    amount = template['price_inr']
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT transaction_id FROM template_purchases WHERE id = ?', (purchase_id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Purchase record not found.")
        return
    txn_db_id = row[0]
    order_id = generate_transaction_id()
    c.execute('UPDATE transactions SET gateway = "zapupi", transaction_id = ? WHERE id = ?', (order_id, txn_db_id))
    conn.commit()
    conn.close()
    txn_id, payment_url = create_zapupi_order(user_id, amount, order_id, plan_id=None, txn_type='template')
    if not txn_id:
        bot.send_message(call.message.chat.id, f"❌ Failed to create Zapupi order: {payment_url}")
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Pay Now", url=payment_url))
    markup.add(types.InlineKeyboardButton("✅ I've Paid (Verify)", callback_data=f"verify_template_zapupi_{order_id}_{purchase_id}"))
    bot.send_message(call.message.chat.id, f"🔗 Pay via Zapupi: {payment_url}\nOrder ID: `{order_id}`\nAfter payment, click 'I've Paid'.", reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def pay_template_binance_manual(call):
    parts = call.data.split('_')
    template_id = int(parts[4])
    purchase_id = int(parts[5])
    user_id = call.from_user.id
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    amount = template['price_inr']
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT transaction_id FROM template_purchases WHERE id = ?', (purchase_id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Purchase record not found.")
        return
    txn_db_id = row[0]
    order_id = generate_transaction_id()
    c.execute('UPDATE transactions SET gateway = "binance_manual", transaction_id = ? WHERE id = ?', (order_id, txn_db_id))
    conn.commit()
    conn.close()
    address = binance_manual_settings.get('address', 'Not set')
    if not address:
        bot.send_message(call.message.chat.id, "❌ Binance manual payment is not configured by admin.")
        return
    markup = types.InlineKeyboardMarkup()
    if binance_manual_settings.get('binance_id'):
        markup.add(types.InlineKeyboardButton("📋 Copy Binance ID", callback_data=f"copy_binance_id_{order_id}"))
    if binance_manual_settings.get('trc_address'):
        markup.add(types.InlineKeyboardButton("📋 Copy TRC Address", callback_data=f"copy_trc_address_{order_id}"))
    markup.add(types.InlineKeyboardButton("✅ I've Paid (Submit TXID)", callback_data=f"submit_binance_manual_{order_id}"))
    text = f"💳 **Binance Manual Payment**\n\nSend ₹{amount:.2f} (≈ ${amount/EXCHANGE_RATE:.2f} USDT) to the following Binance address:\n`{address}`\n\n"
    if binance_manual_settings.get('binance_id'):
        text += f"Binance ID: `{binance_manual_settings['binance_id']}`\n"
    if binance_manual_settings.get('trc_address'):
        text += f"TRC Address: `{binance_manual_settings['trc_address']}`\n"
    text += "\nAfter payment, click the button below and provide the transaction ID and screenshot."
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def verify_template_zapupi(call):
    parts = call.data.split('_')
    order_id = parts[3]
    purchase_id = int(parts[4])
    user_id = call.from_user.id
    verify_payment_manually(user_id, order_id, 'zapupi', call.message.chat.id)
    bot.answer_callback_query(call.id)

def complete_template_purchase(purchase_id, user_id, transaction_id, amount):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT template_id, params FROM template_purchases WHERE id = ?', (purchase_id,))
    row = c.fetchone()
    if not row:
        return False, "Purchase not found"
    template_id, params_json = row
    params = json.loads(params_json)
    template = templates_cache.get(template_id)
    if not template:
        return False, "Template not found"
    zip_path = os.path.join(TEMPLATES_DIR, template['zip_file_path'])
    if not os.path.exists(zip_path):
        return False, "Template zip file missing"

    purchase_folder = f"purchase_{purchase_id}"
    user_folder = get_user_folder(user_id)
    dest_folder = os.path.join(user_folder, purchase_folder)
    if os.path.exists(dest_folder):
        shutil.rmtree(dest_folder)
    os.makedirs(dest_folder, exist_ok=True)

    temp_dir = tempfile.mkdtemp(prefix=f"template_{user_id}_")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                for key, value in params.items():
                    content = content.replace(f"{{{{{key}}}}}", value)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

        for item in os.listdir(temp_dir):
            src = os.path.join(temp_dir, item)
            dst = os.path.join(dest_folder, item)
            shutil.move(src, dst)

        extracted_items = os.listdir(dest_folder)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        main_script_name = None
        file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']
        preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files:
                main_script_name = p
                file_type = 'py'
                break
        if not main_script_name:
            for p in preferred_js:
                if p in js_files:
                    main_script_name = p
                    file_type = 'js'
                    break
        if not main_script_name:
            if py_files:
                main_script_name = py_files[0]
                file_type = 'py'
            elif js_files:
                main_script_name = js_files[0]
                file_type = 'js'
        if not main_script_name:
            return False, "No main script found in template"

        new_script_name = f"purchase_{purchase_id}_{main_script_name}"
        old_path = os.path.join(dest_folder, main_script_name)
        new_path = os.path.join(dest_folder, new_script_name)
        os.rename(old_path, new_path)

        save_user_file(user_id, new_script_name, file_type)
        script_key = f"{user_id}_{new_script_name}"
        c.execute('''UPDATE template_purchases SET bot_script_key = ?, folder_name = ?, status = "active", updated_at = datetime("now") WHERE id = ?''',
                  (script_key, purchase_folder, purchase_id))
        conn.commit()
        conn.close()

        main_script_path = os.path.join(dest_folder, new_script_name)
        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, dest_folder, new_script_name, None, 1, False)).start()
        else:
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, dest_folder, new_script_name, None, 1, False)).start()

        bot.send_message(user_id, f"✅ Your purchased bot '{template['name']}' has been deployed and started!\nYou can manage it via /checkfiles.\n\n**Note:** Parameters cannot be changed after purchase. If you need changes, you must purchase a new template (no refunds).")
        return True, "Bot deployed successfully"
    except Exception as e:
        logger.error(f"Error deploying template: {e}", exc_info=True)
        return False, f"Error: {str(e)}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# --- Admin Template Management ---
def manage_templates_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    bot.edit_message_text("📦 Manage Templates\nChoose action:", call.message.chat.id, call.message.message_id, reply_markup=create_manage_templates_menu())
    bot.answer_callback_query(call.id)

def admin_add_template_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "📝 **Add New Template**\n\nSend template name:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_add_template_name)
    bot.answer_callback_query(call.id)

def process_add_template_name(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    name = message.text.strip()
    if not hasattr(bot, 'admin_template_data'):
        bot.admin_template_data = {}
    bot.admin_template_data[message.from_user.id] = {'name': name}
    msg = bot.send_message(message.chat.id, "📝 Send template description:")
    bot.register_next_step_handler(msg, process_add_template_desc)

def process_add_template_desc(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    desc = message.text.strip()
    bot.admin_template_data[message.from_user.id]['description'] = desc
    msg = bot.send_message(message.chat.id, "💰 Send price in INR (numeric):")
    bot.register_next_step_handler(msg, process_add_template_price)

def process_add_template_price(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
        bot.admin_template_data[message.from_user.id]['price_inr'] = price
    except:
        bot.reply_to(message, "❌ Invalid price. Send a positive number.")
        return
    msg = bot.send_message(message.chat.id, "🎥 Send demo video URL (or send 'skip'):")
    bot.register_next_step_handler(msg, process_add_template_video)

def process_add_template_video(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    video = message.text.strip()
    if video.lower() != 'skip':
        bot.admin_template_data[message.from_user.id]['demo_video_url'] = video
    else:
        bot.admin_template_data[message.from_user.id]['demo_video_url'] = ''
    msg = bot.send_message(message.chat.id, "📦 Upload the bot code as a ZIP file.\nThe ZIP should contain the bot code with placeholders like `{{BOT_TOKEN}}` and `{{ADMIN_ID}}`.\n\nSend the ZIP file now.")
    bot.register_next_step_handler(msg, process_add_template_zip, message.from_user.id)

def process_add_template_zip(message, admin_id):
    if message.from_user.id not in admin_ids:
        return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    if not message.document:
        bot.reply_to(message, "❌ Please send a ZIP file.")
        return
    doc = message.document
    if not doc.file_name.endswith('.zip'):
        bot.reply_to(message, "❌ Only ZIP files allowed.")
        return
    file_info = bot.get_file(doc.file_id)
    file_content = bot.download_file(file_info.file_path)
    zip_filename = f"template_{uuid.uuid4().hex[:8]}.zip"
    zip_path = os.path.join(TEMPLATES_DIR, zip_filename)
    with open(zip_path, 'wb') as f:
        f.write(file_content)
    bot.admin_template_data[admin_id]['zip_file_path'] = zip_filename
    msg = bot.send_message(message.chat.id, "📝 Now send the required parameters for users to fill.\nFormat: `name,label,type,description` one per line.\nExample:\n`bot_token, Bot Token, text, Enter your bot token`\n`admin_id, Admin ID, number, Enter your Telegram user ID`\nType 'done' when finished.\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_add_template_params, admin_id)

def process_add_template_params(message, admin_id):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    if message.text.lower() == 'done':
        data = bot.admin_template_data[admin_id]
        required_params = data.get('params', [])
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''INSERT INTO templates (name, description, price_inr, demo_video_url, zip_file_path, required_params, status)
                     VALUES (?, ?, ?, ?, ?, ?, 'active')''',
                  (data['name'], data['description'], data['price_inr'], data['demo_video_url'], data['zip_file_path'], json.dumps(required_params)))
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Template '{data['name']}' added successfully!")
        del bot.admin_template_data[admin_id]
        return
    parts = message.text.split(',')
    if len(parts) != 4:
        bot.reply_to(message, "❌ Invalid format. Use: `name,label,type,description`")
        return
    param = {
        'name': parts[0].strip(),
        'label': parts[1].strip(),
        'type': parts[2].strip(),
        'description': parts[3].strip()
    }
    if 'params' not in bot.admin_template_data[admin_id]:
        bot.admin_template_data[admin_id]['params'] = []
    bot.admin_template_data[admin_id]['params'].append(param)
    bot.reply_to(message, f"✅ Added param '{param['name']}'. Add more or type 'done'.")
    msg = bot.send_message(message.chat.id, "Next param or 'done':")
    bot.register_next_step_handler(msg, process_add_template_params, admin_id)

def admin_list_templates_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    if not templates_cache:
        bot.edit_message_text("No templates.", call.message.chat.id, call.message.message_id)
        return
    text = "📦 **Templates List**\n\n"
    for t in templates_cache.values():
        text += f"ID: {t['id']} - {t['name']} (₹{t['price_inr']}) - {t['status']}\n"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def admin_edit_template_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    if not templates_cache:
        bot.edit_message_text("No templates available.", call.message.chat.id, call.message.message_id)
        return
    text = "📦 **Select a template to edit:**\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for t in templates_cache.values():
        markup.add(types.InlineKeyboardButton(f"{t['name']} (ID: {t['id']})", callback_data=f"edit_template_detail_{t['id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="manage_templates"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def handle_edit_template_detail(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    # Data: edit_template_detail_{template_id}
    parts = call.data.split('_')
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    template_id = int(parts[3])
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    text = f"✏️ **Edit Template: {template['name']}**\n\n"
    text += f"ID: {template['id']}\n"
    text += f"Name: {template['name']}\n"
    text += f"Description: {template['description']}\n"
    text += f"Price: ₹{template['price_inr']}\n"
    text += f"Demo Video: {template['demo_video_url'] or 'None'}\n"
    text += f"Status: {template['status']}\n"
    text += f"Required Params: {json.dumps(template['required_params'])}\n\n"
    text += "Click a field to edit:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("Name", callback_data=f"template_edit_field_{template_id}_name"),
               types.InlineKeyboardButton("Description", callback_data=f"template_edit_field_{template_id}_description"))
    markup.add(types.InlineKeyboardButton("Price", callback_data=f"template_edit_field_{template_id}_price"),
               types.InlineKeyboardButton("Demo Video", callback_data=f"template_edit_field_{template_id}_demo_video_url"))
    markup.add(types.InlineKeyboardButton("Status", callback_data=f"template_edit_field_{template_id}_status"),
               types.InlineKeyboardButton("Required Params", callback_data=f"template_edit_field_{template_id}_required_params"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_edit_template"))
    text = re.sub(r'([*_`\\])', r'\\\1', text)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def handle_template_edit_field(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    parts = call.data.split('_')
    # Format: template_edit_field_{template_id}_{field}
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    template_id = int(parts[3])
    field = parts[4]
    field_map = {
        'demo': 'demo_video_url',
        'required': 'required_params',
        'price': 'price_inr',
        'status': 'status',
        'name': 'name',
        'description': 'description'
    }
    actual_field = field_map.get(field, field)
    if actual_field == 'required_params':
        # We'll handle this via separate param editor
        bot.answer_callback_query(call.id, "Please use the 'Required Params' edit option to add/remove/edit parameters.")
        return
    msg = bot.send_message(call.message.chat.id, f"Send new value for **{field}**:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_template_edit_field_value, template_id, actual_field, field, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

def process_template_edit_field_value(message, template_id, actual_field, display_field, chat_id, msg_id):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Edit cancelled.")
        try:
            bot.delete_message(chat_id, msg_id)
        except:
            pass
        return
    value = message.text.strip()
    try:
        if actual_field == 'price_inr':
            value = float(value)
        elif actual_field == 'status':
            if value.lower() not in ['active', 'inactive']:
                bot.reply_to(message, "❌ Status must be 'active' or 'inactive'.")
                return
            value = value.lower()
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute(f'UPDATE templates SET {actual_field} = ?, updated_at = datetime("now") WHERE id = ?', (value, template_id))
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Template field '{display_field}' updated.")
        # Refresh detail
        template = templates_cache.get(template_id)
        if template:
            text = f"✏️ **Edit Template: {template['name']}**\n\n"
            text += f"ID: {template['id']}\n"
            text += f"Name: {template['name']}\n"
            text += f"Description: {template['description']}\n"
            text += f"Price: ₹{template['price_inr']}\n"
            text += f"Demo Video: {template['demo_video_url'] or 'None'}\n"
            text += f"Status: {template['status']}\n"
            text += f"Required Params: {json.dumps(template['required_params'])}\n\n"
            text += "Click a field to edit:"
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("Name", callback_data=f"template_edit_field_{template_id}_name"),
                       types.InlineKeyboardButton("Description", callback_data=f"template_edit_field_{template_id}_description"))
            markup.add(types.InlineKeyboardButton("Price", callback_data=f"template_edit_field_{template_id}_price"),
                       types.InlineKeyboardButton("Demo Video", callback_data=f"template_edit_field_{template_id}_demo_video_url"))
            markup.add(types.InlineKeyboardButton("Status", callback_data=f"template_edit_field_{template_id}_status"),
                       types.InlineKeyboardButton("Required Params", callback_data=f"template_edit_field_{template_id}_required_params"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_edit_template"))
            text = re.sub(r'([*_`\\])', r'\\\1', text)
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# --- Advanced Required Params Editor ---
def handle_edit_template_param(call):
    # Called when admin wants to edit the params list of a template
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    template_id = int(call.data.split('_')[3])  # edit_template_param_{template_id}
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    params = template['required_params']
    text = f"✏️ **Edit Required Params for {template['name']}**\n\n"
    if not params:
        text += "No parameters defined.\n"
    else:
        for idx, p in enumerate(params):
            text += f"{idx+1}. {p.get('label', p['name'])} (type: {p.get('type','text')})\n"
            text += f"   {p.get('description', '')}\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ Add Parameter", callback_data=f"template_add_param_{template_id}"))
    if params:
        markup.add(types.InlineKeyboardButton("🗑 Remove Parameter", callback_data=f"template_remove_param_{template_id}"))
        markup.add(types.InlineKeyboardButton("✏️ Edit Parameter", callback_data=f"template_edit_param_choose_{template_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Edit Template", callback_data=f"edit_template_detail_{template_id}"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def handle_template_add_param(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    template_id = int(call.data.split('_')[3])
    template = templates_cache.get(template_id)
    if not template:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    msg = bot.send_message(call.message.chat.id, "Send new parameter in format: `name,label,type,description`\nExample: `bot_token, Bot Token, text, Enter your bot token`\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_add_param_to_template, template_id)
    bot.answer_callback_query(call.id)

def process_add_param_to_template(message, template_id):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    parts = message.text.split(',')
    if len(parts) != 4:
        bot.reply_to(message, "❌ Invalid format. Use: `name,label,type,description`")
        return
    new_param = {
        'name': parts[0].strip(),
        'label': parts[1].strip(),
        'type': parts[2].strip(),
        'description': parts[3].strip()
    }
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT required_params FROM templates WHERE id = ?', (template_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(message, "Template not found.")
        return
    params = json.loads(row[0]) if row[0] else []
    params.append(new_param)
    c.execute('UPDATE templates SET required_params = ?, updated_at = datetime("now") WHERE id = ?', (json.dumps(params), template_id))
    conn.commit()
    conn.close()
    load_data()
    bot.reply_to(message, f"✅ Parameter '{new_param['name']}' added.")
    # Refresh the param edit menu
    template = templates_cache.get(template_id)
    if template:
        handle_edit_template_param(call)  # re-display the param menu

def handle_edit_template_param_choose(call):
    # Let admin choose which param to edit
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    template_id = int(call.data.split('_')[4])  # template_edit_param_choose_{template_id}
    template = templates_cache.get(template_id)
    if not template or not template['required_params']:
        bot.answer_callback_query(call.id, "No parameters to edit.")
        return
    params = template['required_params']
    markup = types.InlineKeyboardMarkup()
    for idx, p in enumerate(params):
        markup.add(types.InlineKeyboardButton(f"Edit {p.get('label', p['name'])}", callback_data=f"template_param_edit_value_{template_id}_{idx}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"edit_template_param_{template_id}"))
    bot.edit_message_text("Select a parameter to edit:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def handle_template_param_edit_field_callback(call):
    # This is called when admin clicks "Edit" on a specific parameter -> show fields to edit.
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    parts = call.data.split('_')
    # Format: template_param_edit_field_{template_id}_{param_idx}
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    template_id = int(parts[4])
    param_idx = int(parts[5])
    template = templates_cache.get(template_id)
    if not template or param_idx >= len(template['required_params']):
        bot.answer_callback_query(call.id, "Parameter not found.")
        return
    param = template['required_params'][param_idx]
    text = f"✏️ Editing parameter:\n\n"
    text += f"Name: {param['name']}\n"
    text += f"Label: {param['label']}\n"
    text += f"Type: {param['type']}\n"
    text += f"Description: {param['description']}\n\n"
    text += "Click which field to edit:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("Name", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_name"),
               types.InlineKeyboardButton("Label", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_label"))
    markup.add(types.InlineKeyboardButton("Type", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_type"),
               types.InlineKeyboardButton("Description", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_description"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"edit_template_param_{template_id}"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def handle_template_param_edit_value_callback(call):
    # This is triggered when admin clicks a specific field to edit (e.g., Name)
    parts = call.data.split('_')
    # Format: template_param_edit_value_{template_id}_{param_idx}_{field}
    if len(parts) != 6:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    template_id = int(parts[4])
    param_idx = int(parts[5])
    field = parts[6]
    template = templates_cache.get(template_id)
    if not template or param_idx >= len(template['required_params']):
        bot.answer_callback_query(call.id, "Parameter not found.")
        return
    msg = bot.send_message(call.message.chat.id, f"Send new value for **{field}**:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_template_param_edit_value, template_id, param_idx, field, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

def process_template_param_edit_value(message, template_id, param_idx, field, chat_id, msg_id):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    new_value = message.text.strip()
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT required_params FROM templates WHERE id = ?', (template_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(message, "Template not found.")
        return
    params = json.loads(row[0]) if row[0] else []
    if param_idx >= len(params):
        bot.reply_to(message, "Parameter index out of range.")
        return
    params[param_idx][field] = new_value
    c.execute('UPDATE templates SET required_params = ?, updated_at = datetime("now") WHERE id = ?', (json.dumps(params), template_id))
    conn.commit()
    conn.close()
    load_data()
    bot.reply_to(message, f"✅ Parameter field '{field}' updated.")
    # Refresh the param edit detail
    template = templates_cache.get(template_id)
    if template:
        param = params[param_idx]
        text = f"✏️ Editing parameter:\n\n"
        text += f"Name: {param['name']}\n"
        text += f"Label: {param['label']}\n"
        text += f"Type: {param['type']}\n"
        text += f"Description: {param['description']}\n\n"
        text += "Click which field to edit:"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("Name", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_name"),
                   types.InlineKeyboardButton("Label", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_label"))
        markup.add(types.InlineKeyboardButton("Type", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_type"),
                   types.InlineKeyboardButton("Description", callback_data=f"template_param_edit_value_{template_id}_{param_idx}_description"))
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"edit_template_param_{template_id}"))
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')

def handle_template_remove_param(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    template_id = int(call.data.split('_')[3])
    template = templates_cache.get(template_id)
    if not template or not template['required_params']:
        bot.answer_callback_query(call.id, "No parameters to remove.")
        return
    params = template['required_params']
    markup = types.InlineKeyboardMarkup()
    for idx, p in enumerate(params):
        markup.add(types.InlineKeyboardButton(f"Remove {p.get('label', p['name'])}", callback_data=f"template_remove_param_confirm_{template_id}_{idx}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"edit_template_param_{template_id}"))
    bot.edit_message_text("Select a parameter to remove:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def handle_template_remove_param_confirm(call):
    # Actually remove the parameter
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    parts = call.data.split('_')
    # Format: template_remove_param_confirm_{template_id}_{param_idx}
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid callback format.")
        return
    template_id = int(parts[4])
    param_idx = int(parts[5])
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT required_params FROM templates WHERE id = ?', (template_id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Template not found.")
        return
    params = json.loads(row[0]) if row[0] else []
    if param_idx >= len(params):
        bot.answer_callback_query(call.id, "Parameter not found.")
        return
    removed = params.pop(param_idx)
    c.execute('UPDATE templates SET required_params = ?, updated_at = datetime("now") WHERE id = ?', (json.dumps(params), template_id))
    conn.commit()
    conn.close()
    load_data()
    bot.answer_callback_query(call.id, f"Removed parameter '{removed.get('name')}'.")
    # Refresh param list
    handle_edit_template_param(call)  # re-display the param menu

# --- Delete template ---
def admin_delete_template_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "🗑 Enter template ID to delete:\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_delete_template)
    bot.answer_callback_query(call.id)

def process_delete_template(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        template_id = int(message.text.strip())
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('DELETE FROM template_purchases WHERE template_id = ?', (template_id,))
        c.execute('DELETE FROM templates WHERE id = ?', (template_id,))
        conn.commit()
        conn.close()
        load_data()
        bot.reply_to(message, f"✅ Template {template_id} deleted.")
    except ValueError:
        bot.reply_to(message, "❌ Invalid ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def available_bots_callback(call):
    user_id = call.from_user.id
    show_available_templates(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)

# --- Auto-verify transactions ---
def auto_verify_transactions():
    while True:
        try:
            time.sleep(60)
            pending = get_pending_transactions()
            for txn_id, user_id, plan_id, amount, transaction_id, gateway, txn_type in pending:
                if gateway == 'zapupi':
                    success, msg = verify_zapupi_order(transaction_id)
                else:
                    continue
                if success:
                    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('SELECT payment_details FROM transactions WHERE id = ?', (txn_id,))
                    row = c.fetchone()
                    conn.close()
                    details = json.loads(row[0]) if row and row[0] else {}
                    duration_months = details.get('duration_months', 1)
                    group_id = details.get('group_id', plan_id)
                    if not group_id:
                        conn2 = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                        c2 = conn2.cursor()
                        c2.execute('SELECT group_id FROM plan_prices WHERE id = ?', (plan_id,))
                        row2 = c2.fetchone()
                        conn2.close()
                        if row2:
                            group_id = row2[0]
                    update_transaction_status(txn_id, 'completed')
                    success2, result = complete_transaction(transaction_id, user_id, group_id, amount, txn_type, duration_months)
                    if success2:
                        logger.info(f"Auto-verified transaction {transaction_id} for user {user_id}. Result: {result}")
                        try:
                            bot.send_message(user_id, f"✅ Your payment has been auto-verified! {result}")
                        except:
                            pass
                    else:
                        logger.error(f"Auto-verify failed to activate for {transaction_id}: {result}")
                else:
                    logger.debug(f"Auto-verify pending for {transaction_id}: {msg}")
        except Exception as e:
            logger.error(f"Error in auto_verify_transactions: {e}", exc_info=True)

auto_verify_thread = threading.Thread(target=auto_verify_transactions, daemon=True)
auto_verify_thread.start()

# --- Zapupi webhook processing ---
def process_zapupi_webhook(data):
    order_id = data.get('order_id')
    status = data.get('status')
    if status != 'success':
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, user_id, plan_id, amount, type FROM transactions WHERE transaction_id = ? AND gateway = "zapupi"', (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        logger.warning(f"Transaction not found for order_id {order_id}")
        return
    trans_id, user_id, plan_id, amount, txn_type = row
    update_transaction_status(trans_id, 'completed', data)
    # Get duration
    conn2 = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c2 = conn2.cursor()
    c2.execute('SELECT payment_details FROM transactions WHERE id = ?', (trans_id,))
    row2 = c2.fetchone()
    conn2.close()
    details = json.loads(row2[0]) if row2 and row2[0] else {}
    duration_months = details.get('duration_months', 1)
    group_id = details.get('group_id', plan_id)
    if not group_id:
        conn3 = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c3 = conn3.cursor()
        c3.execute('SELECT group_id FROM plan_prices WHERE id = ?', (plan_id,))
        row3 = c3.fetchone()
        conn3.close()
        if row3:
            group_id = row3[0]
    success, result = complete_transaction(order_id, user_id, group_id, amount, txn_type, duration_months)
    if success:
        bot.send_message(user_id, f"✅ Webhook confirmed payment! {result}")
        logger.info(f"Webhook processed for user {user_id}, order {order_id}")
    else:
        logger.error(f"Webhook activation failed: {result}")

# --- Ensure node installed ---
def ensure_node_installed():
    try:
        subprocess.run(['node', '--version'], capture_output=True, check=True)
        logger.info("Node.js found.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("Node.js not found. JS scripts will not run.")

# --- Cleanup ---
def cleanup():
    logger.info("Cleaning up...")
    for script_key, script_info in list(bot_scripts.items()):
        try:
            kill_process_tree(script_info)
        except Exception as e:
            logger.error(f"Error killing {script_key}: {e}")
    logger.info("Cleanup complete.")

atexit.register(cleanup)

if __name__ == '__main__':
    ensure_node_installed()
    logger.info("="*50 + "\n🤖 XM HOSTING BOT Starting Up... (All Features Fixed & Enhanced)\n" + "="*50)
    keep_alive()
    logger.info("🚀 Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("Polling ReadTimeout. Restarting in 5s...")
            time.sleep(5)
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"Polling ConnectionError: {ce}. Retrying in 15s...")
            time.sleep(15)
        except Exception as e:
            logger.critical(f"💥 Unrecoverable polling error: {e}", exc_info=True)
            logger.info("Restarting polling in 30s due to critical error...")
            time.sleep(30)
        finally:
            logger.warning("Polling attempt finished. Will restart if in loop.")
            time.sleep(1)
