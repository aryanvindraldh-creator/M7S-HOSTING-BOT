# -*- coding: utf-8 -*-
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

# --- Load environment variables ---
load_dotenv()

# --- Flask Keep Alive & Webhooks ---
from flask import Flask, request, jsonify
from threading import Thread

app = Flask('')

@app.route('/webhook/zapupi', methods=['POST'])
def zapupi_webhook():
    data = request.get_json()
    logger.info(f"Zapupi webhook received: {data}")
    threading.Thread(target=process_zapupi_webhook, args=(data,)).start()
    return jsonify({"status": "ok"}), 200

@app.route('/webhook/binance', methods=['POST'])
def binance_webhook():
    data = request.get_json()
    logger.info(f"Binance webhook received: {data}")
    threading.Thread(target=process_binance_webhook, args=(data,)).start()
    return jsonify({"status": "ok"}), 200

@app.route('/')
def home():
    return "𝑴7𝑺 𝑻𝑬𝑳𝑬 𝑩𝑶𝑻 - Paid Hosting Platform"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive & Webhook server started.")

# --- Configuration ---
TOKEN = os.getenv('TOKEN', '8285024887:AAEaoF6e2TBL92eXVpT0cA_RTbkARQeDrWo')
OWNER_ID = int(os.getenv('OWNER_ID', 6893661111))
ADMIN_ID = int(os.getenv('ADMIN_ID', 6893661111))
YOUR_USERNAME = os.getenv('YOUR_USERNAME', '@M7S_BOT')
UPDATE_CHANNEL = os.getenv('UPDATE_CHANNEL', '@M7S_TECH_LAB')

FREE_USER_LIMIT = int(os.getenv('FREE_USER_LIMIT', 1))
SUBSCRIBED_USER_LIMIT = int(os.getenv('SUBSCRIBED_USER_LIMIT', 5))
ADMIN_LIMIT = int(os.getenv('ADMIN_LIMIT', 20))
OWNER_LIMIT = float('inf')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

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

# NEW: paid system data
plans_cache = {}
zapupi_settings = {}
binance_settings = {}
pending_payments = {}

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

# --- Command Button Layouts (with new menu items) ---
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["📞 Contact Owner"],
    ["📦 Manual Install", "🆘 Help"],
    ["📋 View Plans", "🛒 Purchase Plan"],
    ["📅 My Subscription"]
]

ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💳 Subscriptions", "📢 Broadcast"],
    ["🔒 Lock Bot", "🟢 Running All Code"],
    ["👑 Admin Panel", "📞 Contact Owner"],
    ["📢 Channel Add", "🛠️ Manual Install"],
    ["👥 User Management", "⚙️ Settings"],
    ["💲 Payment Settings", "📋 Plan Management"],
    ["📋 View Plans", "🛒 Purchase Plan"]
]

# --- Database Setup ---
def init_db():
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        # Existing tables
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT, PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY, join_date TEXT, last_seen TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_by INTEGER, added_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, ban_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_limits (user_id INTEGER PRIMARY KEY, file_limit INTEGER, set_by INTEGER, set_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS mandatory_channels (channel_id TEXT PRIMARY KEY, channel_username TEXT, channel_name TEXT, added_by INTEGER, added_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS install_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, module_name TEXT, package_name TEXT, status TEXT, log TEXT, install_date TEXT)''')
        # New tables for paid system
        c.execute('''CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price REAL NOT NULL, duration_days INTEGER NOT NULL, bot_limit INTEGER NOT NULL, description TEXT, status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS zapupi_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, api_key TEXT, gateway_enabled INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS binance_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, api_key TEXT, secret_key TEXT, gateway_enabled INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_id INTEGER, gateway TEXT, transaction_id TEXT UNIQUE, amount REAL, currency TEXT, status TEXT DEFAULT 'pending', payment_details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_id INTEGER, start_date TEXT, expiry_date TEXT, bot_limit INTEGER, active INTEGER DEFAULT 1, transaction_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES active_users(user_id), FOREIGN KEY (plan_id) REFERENCES plans(id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS payment_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, gateway TEXT, request_data TEXT, response_data TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

        c.execute('SELECT COUNT(*) FROM plans')
        if c.fetchone()[0] == 0:
            default_plans = [
                ('Starter', 5.00, 30, 2, 'Basic plan: 2 bots, 30 days'),
                ('Pro', 15.00, 90, 5, 'Pro plan: 5 bots, 90 days'),
                ('Enterprise', 30.00, 365, 20, 'Enterprise: 20 bots, 365 days')
            ]
            for name, price, duration, limit, desc in default_plans:
                c.execute('''INSERT INTO plans (name, price, duration_days, bot_limit, description, status) VALUES (?, ?, ?, ?, ?, 'active')''', (name, price, duration, limit, desc))
            logger.info("Default plans inserted.")

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
        # Load existing
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
        # Load new
        c.execute('SELECT id, name, price, duration_days, bot_limit, description, status FROM plans')
        for row in c.fetchall():
            plans_cache[row[0]] = {'id': row[0], 'name': row[1], 'price': row[2], 'duration_days': row[3], 'bot_limit': row[4], 'description': row[5], 'status': row[6]}
        c.execute('SELECT api_key, gateway_enabled FROM zapupi_settings ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        if row:
            zapupi_settings['api_key'] = row[0]
            zapupi_settings['enabled'] = bool(row[1])
        else:
            zapupi_settings['api_key'] = None
            zapupi_settings['enabled'] = False
        c.execute('SELECT api_key, secret_key, gateway_enabled FROM binance_settings ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        if row:
            binance_settings['api_key'] = row[0]
            binance_settings['secret_key'] = row[1]
            binance_settings['enabled'] = bool(row[2])
        else:
            binance_settings['api_key'] = None
            binance_settings['secret_key'] = None
            binance_settings['enabled'] = False
        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(plans_cache)} plans, Zapupi enabled: {zapupi_settings.get('enabled', False)}, Binance enabled: {binance_settings.get('enabled', False)}")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

init_db()
load_data()

# --- Helper functions for paid system ---
def get_user_active_plan(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''SELECT plan_id, bot_limit, expiry_date FROM user_plans WHERE user_id = ? AND active = 1 AND expiry_date > datetime('now') ORDER BY expiry_date DESC LIMIT 1''', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        plan_id, bot_limit, expiry_date = row
        return {'plan_id': plan_id, 'bot_limit': bot_limit, 'expiry_date': datetime.fromisoformat(expiry_date)}
    return None

def get_user_plan_limit(user_id):
    plan = get_user_active_plan(user_id)
    if plan:
        return plan['bot_limit']
    return None

def get_user_file_limit(user_id):
    plan_limit = get_user_plan_limit(user_id)
    if plan_limit is not None:
        return plan_limit
    if user_id == OWNER_ID:
        return OWNER_LIMIT
    if user_id in admin_ids:
        return ADMIN_LIMIT
    if user_id in user_limits:
        return user_limits[user_id]
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

# --- Existing helper functions (unchanged, but we keep them) ---
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

# --- Security functions (unchanged) ---
def check_code_security(file_path, file_type):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        dangerous_patterns = [
            r'\bos\b', r'\bos\.system\b', r'\bos\.(remove|unlink|walk|listdir|scandir|stat|popen|fork|exec|kill|spawn)\b',
            r'\bshutdown\b', r'\breboot\b', r'rm\s+-rf', r'format\s+c:', r'dd\s+if=', r'\bmkfs\b', r'\bfdisk\b',
            r'chmod\s+777', r'chmod\s+\+x', r'\bsys\.exit\b', r'\bsys\.argv\b', r'\bls\b', r'\bcd\b', r'\bvps\b',
            r'\bkill\b', r'\bkillall\b', r'\bpkill\b', r'\bkill\s+-\d+', r'\bhalt\b', r'\bpoweroff\b',
            r'\binit\s+0', r'\binit\s+6', r'\btelinit\s+0', r'\btelinit\s+6', r'\bmv\b.*/dev/null',
            r'\bcat\s+>/dev/null', r'>\s*/dev/null', r'2>\s*&1', r'\b&\s*$', r'\bnohup\b', r'\bdisown\b',
            r'rm\s+-rf\s+/', r'rm\s+-rf\s+~', r'rm\s+-rf\s+\.', r'rm\s+-rf\s+\*', r'rm\s+-rf\s+.*',
            r'\bdd\s+if=/dev/zero', r'\bdd\s+of=/dev/sda', r'\bmv\s+/dev/null', r'>\s+\.bash_history',
            r'>\s+\.zsh_history', r'echo\s+""\s+>', r'truncate\s+-s\s+0', r':>\s*',
            r'\bre\b', r'\bre\.(compile|search|match|findall|finditer|sub|split|escape|fullmatch)\b',
            r'\bimport\s+re\b', r'\bfrom\s+re\s+import\b', r'\bregex\b', r'\bpattern\s*=\s*re\.compile',
            r're\.(I|IGNORECASE|M|MULTILINE|S|DOTALL|U|UNICODE|X|VERBOSE)', r'\.*\{.*,\}', r'\^.*\$', r'\[.*\]',
            r'\(.*\)', r'\?.*', r'\*.*', r'\+.*', r'image\.jpeg', r'image\.jpg', r'image\.png', r'image\.gif',
            r'image\.bmp', r'\.jpeg\b', r'\.jpg\b', r'\.png\b', r'\.gif\b', r'\.bmp\b', r'\.ico\b', r'\.svg\b',
            r'\.webp\b', r'\.tiff\b', r'\.tif\b', r'\.pdf\b', r'\.docx\b', r'\.doc\b', r'\.xlsx\b', r'\.xls\b',
            r'\.pptx\b', r'\.ppt\b', r'\.zip\b', r'\.tar\b', r'\.gz\b', r'\.7z\b', r'\.rar\b', r'\bPIL\b',
            r'\bImage\b', r'\bImage\.(open|save|new|fromarray|frombytes)\b', r'\bcv2\b', r'\bopencv\b',
            r'\bskimage\b', r'\bscikit-image\b', r'\bmatplotlib\.image\b', r'\bimread\b', r'\bimwrite\b',
            r'\bimshow\b', r'\bimsave\b', r'\bctypes\b', r'\bctypes\.(CDLL|WinDLL|PyDLL|cdll|windll|oledll|py_object|Structure|Union)\b',
            r'\bCDLL\b', r'\bWinDLL\b', r'\blibc\b', r'\bFILE_p\b', r'\blibc\.(system|exec|fork|kill|popen)\b',
            r'\bmemset\b', r'\bmemcpy\b', r'\bmprotect\b', r'\bmmap\b', r'\bVirtualAlloc\b', r'\bCreateProcess\b',
            r'\bLoadLibrary\b', r'\bGetProcAddress\b', r'\bsubprocess\b', r'\bsubprocess\.(Popen|call|run|check_output|getoutput|getstatusoutput)\b',
            r'\beval\b', r'\bexec\b', r'\bcompile\b', r'\b__import__\b', r'\bopen\s*\(', r'\bread\s*\(',
            r'\bpathlib\b', r'\bglob\b', r'\bshutil\b', r'\bshutil\.(rmtree|copytree|move|disk_usage)\b',
            r'\bzipfile\b', r'\btempfile\b', r'\bcPickle\b', r'\bshelve\b', r'\bsqlite3\b',
            r'\bpandas\.(read_csv|read_excel|read_json)\b', r'\bos\.environ\b', r'\bdotenv\b', r'\bload_dotenv\b',
            r'\bprintenv\b', r'\benv\b', r'\bgetpass\b', r'\bkeyring\b', r'\bconfigparser\b', r'\byaml\b',
            r'\bjson\.load\b', r'\bsocket\b', r'\bsocket\.(socket|create_connection|gethostname|gethostbyname)\b',
            r'\brequests\b', r'\brequests\.(get|post|put|delete|head|request)\b', r'\burllib\b', r'\burllib2\b',
            r'\burllib3\b', r'\bhttp\.client\b', r'\bwebsocket\b', r'\basyncio\.open_connection\b', r'\bwget\b',
            r'\bcurl\b', r'\bdownload\b', r'\bftplib\b', r'\bsmtplib\b', r'\bpoplib\b', r'\bimaplib\b',
            r'\btelnetlib\b', r'\bparamiko\b', r'\bscp\b', r'\bssh\b', r'\bsshlib\b', r'\bpexpect\b',
            r'\bfabric\b', r'\bpsutil\b', r'\bplatform\b', r'\bplatform\.(node|processor|machine|architecture|system|version)\b',
            r'\bcmdline\b', r'\bpid\b', r'/proc/', r'\bmem\b', r'\bcpu\b', r'\bhostname\b', r'\buname\b',
            r'\bwhoami\b', r'\bglobals\b', r'\blocals\b', r'\bvars\b', r'\binspect\b', r'\bmarshal\b',
            r'\bpickle\b', r'\bimportlib\b', r'\b__builtins__\b', r'\b__import__\b', r'\b__loader__\b',
            r'\b__file__\b', r'\b__package__\b', r'\b__spec__\b', r'\b__code__\b', r'\b__dict__\b',
            r'\bgetattr\b', r'\bsetattr\b', r'\bdelattr\b', r'\bhasattr\b', r'\bcallable\b', r'\btelebot\b',
            r'\btelebot\.types\b', r'\baiogram\b', r'\bpyrogram\b', r'\btelegram\.ext\b', r'\btelegram\.bot\b',
            r'/bin/sh', r'/bin/bash', r'/bin/zsh', r'/bin/dash', r'nc\s+-e', r'netcat', r'\bbase64\b',
            r'\becho\b.*\|', r'\bawk\b', r'\bsed\b', r'\bfind\b', r'\bxargs\b', r'\bcrontab\b', r'\bservice\b',
            r'\bsystemctl\b', r'\btop\b', r'\bps\b', r'\bhtop\b', r'\bifconfig\b', r'\bip\s+a', r'\bss\b',
            r'\blsof\b', r'\bnetstat\b', r'/etc/passwd', r'/etc/shadow', r'/etc/hosts', r'/etc/resolv.conf',
            r'\.ssh/', r'id_rsa', r'id_dsa', r'authorized_keys', r'known_hosts', r'\.bashrc', r'\.bash_profile',
            r'\.zshrc', r'\.profile', r'\bsqlite3\b', r'\bmysql\b', r'\bmysql\.connector\b', r'\bpsycopg2\b',
            r'\bpymongo\b', r'\bredis\b', r'\bcrypt\b', r'\bhashlib\b', r'\bhmac\b', r'\bssl\b', r'\btls\b',
            r'\bCrypto\b', r'\bcryptography\b', r'\bsignal\b', r'\bmultiprocessing\b', r'\bthreading\b',
            r'\bdaemon\b', r'\batexit\b', r'\bexit\b', r'\bquit\b', r'\bpyautogui\b', r'\bselenium\b',
            r'\bpyscreenshot\b', r'\bImageGrab\b', r'\bpynput\b', r'\bkeyboard\b', r'\bmouse\b', r'\bgetch\b',
            r'\.name\b', r'\.__name__\b', r'\.__class__\b', r'\.__bases__\b', r'\.__subclasses__\b',
            r'\.__mro__\b', r'\.__dictitems__\b', r'\.__reduce__\b', r'\.__reduce_ex__\b', r'\.__getstate__\b',
            r'\.__setstate__\b', r'\bwin32api\b', r'\bwin32com\b', r'\bwin32con\b', r'\bwin32event\b',
            r'\bwin32file\b', r'\bwin32process\b', r'\bwin32security\b', r'\bwmi\b', r'\bregedit\b',
            r'\bregistry\b', r'\bGetAsyncKeyState\b', r'\bSetWindowsHookEx\b', r'\btaskkill\b', r'\btasklist\b',
            r'\bschtasks\b', r'\bptrace\b', r'\bdebugger\b', r'\bisatty\b', r'\bwindbg\b', r'\bollydbg\b',
            r'\bmmap\b', r'\bmprotect\b', r'\bbrk\b', r'\bsbrk\b', r'\bmalloc\b', r'\bfree\b', r'\brealloc\b',
            r'\bVirtualAlloc\b', r'\bVirtualProtect\b', r'\bVirtualFree\b', r'\bHeapAlloc\b', r'\bHeapFree\b',
            r'\binject\b', r'\bpayload\b', r'\bshellcode\b', r'\bmetasploit\b', r'\bbackdoor\b', r'\brootkit\b',
            r'\btrojan\b', r'\bmalware\b', r'\bexploit\b', r'\bvirus\b', r'\bworm\b', r'\bnmap\b', r'\bnping\b',
            r'\bscapy\b', r'\barp\b', r'\bping\b', r'\btraceroute\b', r'\broute\b', r'\bifconfig\b',
            r'\bipconfig\b', r'\bnetstat\b', r'\bss\b', r'\bsudo\b', r'\bsu\b', r'\brunas\b', r'\bprivilege\b',
            r'\bescalation\b', r'\buac\b', r'\bbypassuac\b', r'\bregistry\b', r'\bstartup\b', r'\bautostart\b',
            r'\bscheduled\s*task\b', r'\bcron\b', r'\bat\b', r'\binit\.d\b', r'\bsystemd\b', r'\blaunchd\b',
            r'\bplist\b', r'\bmv\s+.*\s+/dev/null', r'\b>+\s*.*\.log', r'\btar\s+.*--exclude', r'\bfuser\b',
            r'\bstrace\b', r'\bltrace\b', r'\bgdb\b', r'\bobjdump\b', r'\bstrings\b', r'\bhexdump\b', r'\bxxd\b',
            r'\bod\b', r'\bsize\b', r'\bnm\b', r'\breadelf\b', r'\bldd\b', r'\bfile\b', r'\bwhich\b',
            r'\bwhereis\b', r'\blocate\b', r'\bupdatedb\b', r'\bmake\b', r'\bgcc\b', r'\bg\+\+\b', r'\bclang\b',
            r'\bclang\+\+\b', r'\bpython\d*\s+-c', r'\bperl\s+-e', r'\bruby\s+-e', r'\bphp\s+-r', r'\blua\s+-e',
            r'\bnode\s+-e', r'\bwget\s+.*\|\s*sh', r'\bcurl\s+.*\|\s*sh', r'\bwget\s+.*\|\s*bash',
            r'\bcurl\s+.*\|\s*bash', r'\bchattr\s+\+i', r'\bchattr\s+-i', r'\bsetfacl\b', r'\bgetfacl\b',
            r'\bchown\s+.*:.*', r'\bchgrp\b', r'\busermod\b', r'\bgroupmod\b', r'\badduser\b', r'\baddgroup\b',
            r'\bdeluser\b', r'\bdelgroup\b', r'\bpasswd\b', r'\bvisudo\b', r'\bed\b', r'\bex\b', r'\bvi\b',
            r'\bvim\b', r'\bnano\b', r'\bemacs\b', r'\bpico\b', r'\bmicro\b', r'\bne\b',
            r'\b__import__\s*\(', r'\bgetattr\s*\(', r'\bsetattr\s*\(', r'\bdelattr\s*\(', r'\bhasattr\s*\(',
            r'\b__getattr__\b', r'\b__setattr__\b', r'\b__delattr__\b', r'\b__getattribute__\b',
            r'\b__call__\b', r'\b__enter__\b', r'\b__exit__\b', r'\b__new__\b', r'\b__init__\b',
            r'\b__del__\b', r'\b__repr__\b', r'\b__str__\b', r'\b__bytes__\b', r'\b__format__\b',
            r'\b__lt__\b', r'\b__le__\b', r'\b__eq__\b', r'\b__ne__\b', r'\b__gt__\b', r'\b__ge__\b',
            r'\b__hash__\b', r'\b__bool__\b', r'\b__getitem__\b', r'\b__setitem__\b', r'\b__delitem__\b',
            r'\b__iter__\b', r'\b__next__\b', r'\b__reversed__\b', r'\b__contains__\b', r'\b__len__\b',
            r'\b__length_hint__\b', r'\b__missing__\b', r'\b__copy__\b', r'\b__deepcopy__\b'
        ]
        found_patterns = []
        for pattern in dangerous_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                found_patterns.append(pattern)
        if found_patterns:
            logger.warning(f"🚨 Dangerous patterns detected in {file_path}: {found_patterns}")
            return False, f"Code contains dangerous commands: {', '.join(found_patterns[:5])}"
        return True, "Code is safe"
    except Exception as e:
        logger.error(f"Error in security check: {e}")
        return False, f"Security check error: {str(e)}"

def scan_zip_security(zip_path):
    try:
        dangerous_patterns = [
            r'\bos\b', r'\bos\.system\b', r'\bos\.(remove|unlink|walk|listdir|scandir|stat|popen|fork|exec|kill|spawn)\b',
            r'\bshutdown\b', r'\breboot\b', r'rm\s+-rf', r'format\s+c:', r'dd\s+if=', r'\bmkfs\b', r'\bfdisk\b',
            r'chmod\s+777', r'chmod\s+\+x', r'\bsys\.exit\b', r'\bsys\.argv\b', r'\bls\b', r'\bcd\b', r'\bvps\b',
            r'\bkill\b', r'\bkillall\b', r'\bpkill\b', r'\bkill\s+-\d+', r'\bhalt\b', r'\bpoweroff\b',
            r'\binit\s+0', r'\binit\s+6', r'\btelinit\s+0', r'\btelinit\s+6', r'\bmv\b.*/dev/null',
            r'\bcat\s+>/dev/null', r'>\s*/dev/null', r'2>\s*&1', r'\b&\s*$', r'\bnohup\b', r'\bdisown\b',
            r'rm\s+-rf\s+/', r'rm\s+-rf\s+~', r'rm\s+-rf\s+\.', r'rm\s+-rf\s+\*', r'rm\s+-rf\s+.*',
            r'\bdd\s+if=/dev/zero', r'\bdd\s+of=/dev/sda', r'\bmv\s+/dev/null', r'>\s+\.bash_history',
            r'>\s+\.zsh_history', r'echo\s+""\s+>', r'truncate\s+-s\s+0', r':>\s*',
            r'\bre\b', r'\bre\.(compile|search|match|findall|finditer|sub|split|escape|fullmatch)\b',
            r'\bimport\s+re\b', r'\bfrom\s+re\s+import\b', r'\bregex\b', r'\bpattern\s*=\s*re\.compile',
            r're\.(I|IGNORECASE|M|MULTILINE|S|DOTALL|U|UNICODE|X|VERBOSE)', r'\.*\{.*,\}', r'\^.*\$', r'\[.*\]',
            r'\(.*\)', r'\?.*', r'\*.*', r'\+.*', r'image\.jpeg', r'image\.jpg', r'image\.png', r'image\.gif',
            r'image\.bmp', r'\.jpeg\b', r'\.jpg\b', r'\.png\b', r'\.gif\b', r'\.bmp\b', r'\.ico\b', r'\.svg\b',
            r'\.webp\b', r'\.tiff\b', r'\.tif\b', r'\.pdf\b', r'\.docx\b', r'\.doc\b', r'\.xlsx\b', r'\.xls\b',
            r'\.pptx\b', r'\.ppt\b', r'\.zip\b', r'\.tar\b', r'\.gz\b', r'\.7z\b', r'\.rar\b', r'\bPIL\b',
            r'\bImage\b', r'\bImage\.(open|save|new|fromarray|frombytes)\b', r'\bcv2\b', r'\bopencv\b',
            r'\bskimage\b', r'\bscikit-image\b', r'\bmatplotlib\.image\b', r'\bimread\b', r'\bimwrite\b',
            r'\bimshow\b', r'\bimsave\b', r'\bctypes\b', r'\bctypes\.(CDLL|WinDLL|PyDLL|cdll|windll|oledll|py_object|Structure|Union)\b',
            r'\bCDLL\b', r'\bWinDLL\b', r'\blibc\b', r'\bFILE_p\b', r'\blibc\.(system|exec|fork|kill|popen)\b',
            r'\bmemset\b', r'\bmemcpy\b', r'\bmprotect\b', r'\bmmap\b', r'\bVirtualAlloc\b', r'\bCreateProcess\b',
            r'\bLoadLibrary\b', r'\bGetProcAddress\b', r'\bsubprocess\b', r'\bsubprocess\.(Popen|call|run|check_output|getoutput|getstatusoutput)\b',
            r'\beval\b', r'\bexec\b', r'\bcompile\b', r'\b__import__\b', r'\bopen\s*\(', r'\bread\s*\(',
            r'\bpathlib\b', r'\bglob\b', r'\bshutil\b', r'\bshutil\.(rmtree|copytree|move|disk_usage)\b',
            r'\bzipfile\b', r'\btempfile\b', r'\bcPickle\b', r'\bshelve\b', r'\bsqlite3\b',
            r'\bpandas\.(read_csv|read_excel|read_json)\b', r'\bos\.environ\b', r'\bdotenv\b', r'\bload_dotenv\b',
            r'\bprintenv\b', r'\benv\b', r'\bgetpass\b', r'\bkeyring\b', r'\bconfigparser\b', r'\byaml\b',
            r'\bjson\.load\b', r'\bsocket\b', r'\bsocket\.(socket|create_connection|gethostname|gethostbyname)\b',
            r'\brequests\b', r'\brequests\.(get|post|put|delete|head|request)\b', r'\burllib\b', r'\burllib2\b',
            r'\burllib3\b', r'\bhttp\.client\b', r'\bwebsocket\b', r'\basyncio\.open_connection\b', r'\bwget\b',
            r'\bcurl\b', r'\bdownload\b', r'\bftplib\b', r'\bsmtplib\b', r'\bpoplib\b', r'\bimaplib\b',
            r'\btelnetlib\b', r'\bparamiko\b', r'\bscp\b', r'\bssh\b', r'\bsshlib\b', r'\bpexpect\b',
            r'\bfabric\b', r'\bpsutil\b', r'\bplatform\b', r'\bplatform\.(node|processor|machine|architecture|system|version)\b',
            r'\bcmdline\b', r'\bpid\b', r'/proc/', r'\bmem\b', r'\bcpu\b', r'\bhostname\b', r'\buname\b',
            r'\bwhoami\b', r'\bglobals\b', r'\blocals\b', r'\bvars\b', r'\binspect\b', r'\bmarshal\b',
            r'\bpickle\b', r'\bimportlib\b', r'\b__builtins__\b', r'\b__import__\b', r'\b__loader__\b',
            r'\b__file__\b', r'\b__package__\b', r'\b__spec__\b', r'\b__code__\b', r'\b__dict__\b',
            r'\bgetattr\b', r'\bsetattr\b', r'\bdelattr\b', r'\bhasattr\b', r'\bcallable\b', r'\btelebot\b',
            r'\btelebot\.types\b', r'\baiogram\b', r'\bpyrogram\b', r'\btelegram\.ext\b', r'\btelegram\.bot\b',
            r'/bin/sh', r'/bin/bash', r'/bin/zsh', r'/bin/dash', r'nc\s+-e', r'netcat', r'\bbase64\b',
            r'\becho\b.*\|', r'\bawk\b', r'\bsed\b', r'\bfind\b', r'\bxargs\b', r'\bcrontab\b', r'\bservice\b',
            r'\bsystemctl\b', r'\btop\b', r'\bps\b', r'\bhtop\b', r'\bifconfig\b', r'\bip\s+a', r'\bss\b',
            r'\blsof\b', r'\bnetstat\b', r'/etc/passwd', r'/etc/shadow', r'/etc/hosts', r'/etc/resolv.conf',
            r'\.ssh/', r'id_rsa', r'id_dsa', r'authorized_keys', r'known_hosts', r'\.bashrc', r'\.bash_profile',
            r'\.zshrc', r'\.profile', r'\bsqlite3\b', r'\bmysql\b', r'\bmysql\.connector\b', r'\bpsycopg2\b',
            r'\bpymongo\b', r'\bredis\b', r'\bcrypt\b', r'\bhashlib\b', r'\bhmac\b', r'\bssl\b', r'\btls\b',
            r'\bCrypto\b', r'\bcryptography\b', r'\bsignal\b', r'\bmultiprocessing\b', r'\bthreading\b',
            r'\bdaemon\b', r'\batexit\b', r'\bexit\b', r'\bquit\b', r'\bpyautogui\b', r'\bselenium\b',
            r'\bpyscreenshot\b', r'\bImageGrab\b', r'\bpynput\b', r'\bkeyboard\b', r'\bmouse\b', r'\bgetch\b',
            r'\.name\b', r'\.__name__\b', r'\.__class__\b', r'\.__bases__\b', r'\.__subclasses__\b',
            r'\.__mro__\b', r'\.__dictitems__\b', r'\.__reduce__\b', r'\.__reduce_ex__\b', r'\.__getstate__\b',
            r'\.__setstate__\b', r'\bwin32api\b', r'\bwin32com\b', r'\bwin32con\b', r'\bwin32event\b',
            r'\bwin32file\b', r'\bwin32process\b', r'\bwin32security\b', r'\bwmi\b', r'\bregedit\b',
            r'\bregistry\b', r'\bGetAsyncKeyState\b', r'\bSetWindowsHookEx\b', r'\btaskkill\b', r'\btasklist\b',
            r'\bschtasks\b', r'\bptrace\b', r'\bdebugger\b', r'\bisatty\b', r'\bwindbg\b', r'\bollydbg\b',
            r'\bmmap\b', r'\bmprotect\b', r'\bbrk\b', r'\bsbrk\b', r'\bmalloc\b', r'\bfree\b', r'\brealloc\b',
            r'\bVirtualAlloc\b', r'\bVirtualProtect\b', r'\bVirtualFree\b', r'\bHeapAlloc\b', r'\bHeapFree\b',
            r'\binject\b', r'\bpayload\b', r'\bshellcode\b', r'\bmetasploit\b', r'\bbackdoor\b', r'\brootkit\b',
            r'\btrojan\b', r'\bmalware\b', r'\bexploit\b', r'\bvirus\b', r'\bworm\b', r'\bnmap\b', r'\bnping\b',
            r'\bscapy\b', r'\barp\b', r'\bping\b', r'\btraceroute\b', r'\broute\b', r'\bifconfig\b',
            r'\bipconfig\b', r'\bnetstat\b', r'\bss\b', r'\bsudo\b', r'\bsu\b', r'\brunas\b', r'\bprivilege\b',
            r'\bescalation\b', r'\buac\b', r'\bbypassuac\b', r'\bregistry\b', r'\bstartup\b', r'\bautostart\b',
            r'\bscheduled\s*task\b', r'\bcron\b', r'\bat\b', r'\binit\.d\b', r'\bsystemd\b', r'\blaunchd\b',
            r'\bplist\b', r'\bmv\s+.*\s+/dev/null', r'\b>+\s*.*\.log', r'\btar\s+.*--exclude', r'\bfuser\b',
            r'\bstrace\b', r'\bltrace\b', r'\bgdb\b', r'\bobjdump\b', r'\bstrings\b', r'\bhexdump\b', r'\bxxd\b',
            r'\bod\b', r'\bsize\b', r'\bnm\b', r'\breadelf\b', r'\bldd\b', r'\bfile\b', r'\bwhich\b',
            r'\bwhereis\b', r'\blocate\b', r'\bupdatedb\b', r'\bmake\b', r'\bgcc\b', r'\bg\+\+\b', r'\bclang\b',
            r'\bclang\+\+\b', r'\bpython\d*\s+-c', r'\bperl\s+-e', r'\bruby\s+-e', r'\bphp\s+-r', r'\blua\s+-e',
            r'\bnode\s+-e', r'\bwget\s+.*\|\s*sh', r'\bcurl\s+.*\|\s*sh', r'\bwget\s+.*\|\s*bash',
            r'\bcurl\s+.*\|\s*bash', r'\bchattr\s+\+i', r'\bchattr\s+-i', r'\bsetfacl\b', r'\bgetfacl\b',
            r'\bchown\s+.*:.*', r'\bchgrp\b', r'\busermod\b', r'\bgroupmod\b', r'\badduser\b', r'\baddgroup\b',
            r'\bdeluser\b', r'\bdelgroup\b', r'\bpasswd\b', r'\bvisudo\b', r'\bed\b', r'\bex\b', r'\bvi\b',
            r'\bvim\b', r'\bnano\b', r'\bemacs\b', r'\bpico\b', r'\bmicro\b', r'\bne\b',
            r'\b__import__\s*\(', r'\bgetattr\s*\(', r'\bsetattr\s*\(', r'\bdelattr\s*\(', r'\bhasattr\s*\(',
            r'\b__getattr__\b', r'\b__setattr__\b', r'\b__delattr__\b', r'\b__getattribute__\b',
            r'\b__call__\b', r'\b__enter__\b', r'\b__exit__\b', r'\b__new__\b', r'\b__init__\b',
            r'\b__del__\b', r'\b__repr__\b', r'\b__str__\b', r'\b__bytes__\b', r'\b__format__\b',
            r'\b__lt__\b', r'\b__le__\b', r'\b__eq__\b', r'\b__ne__\b', r'\b__gt__\b', r'\b__ge__\b',
            r'\b__hash__\b', r'\b__bool__\b', r'\b__getitem__\b', r'\b__setitem__\b', r'\b__delitem__\b',
            r'\b__iter__\b', r'\b__next__\b', r'\b__reversed__\b', r'\b__contains__\b', r'\b__len__\b',
            r'\b__length_hint__\b', r'\b__missing__\b', r'\b__copy__\b', r'\b__deepcopy__\b'
        ]
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
                                return False, f"File {file_info.filename} contains dangerous command: {pattern}"
        return True, "Archive is safe"
    except Exception as e:
        return False, f"Error scanning archive: {str(e)}"

# --- Mandatory Channels Functions (unchanged) ---
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

# --- User Management Functions (unchanged) ---
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

# --- Other helper functions (save_user_file, add_active_user, etc.) ---
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
            c.execute('INSERT OR REPLACE INTO active_users (user_id, join_date, last_seen) VALUES (?, ?, ?)',
                      (user_id, join_date, join_date))
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

# --- TELEGRAM_MODULES mapping (unchanged) ---
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

# --- Manual install functions (unchanged) ---
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

# --- Menu creation functions (unchanged) ---
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates Channel', url=f'https://t.me/{UPDATE_CHANNEL.replace("@", "")}'),
        types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
        types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'),
        types.InlineKeyboardButton('📦 Manual Install', callback_data='manual_install'),
        types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}')
    ]
    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot', callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('📢 Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('🟢 Run All Scripts', callback_data='run_all_scripts'),
            types.InlineKeyboardButton('📢 Channel Add', callback_data='manage_mandatory_channels'),
            types.InlineKeyboardButton('👥 User Management', callback_data='user_management'),
            types.InlineKeyboardButton('🛠️ Admin Install', callback_data='admin_install'),
            types.InlineKeyboardButton('⚙️ Settings', callback_data='admin_settings')
        ]
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], admin_buttons[0])
        markup.add(admin_buttons[1], admin_buttons[3])
        markup.add(admin_buttons[2], admin_buttons[5])
        markup.add(admin_buttons[6], admin_buttons[8])
        markup.add(admin_buttons[7], admin_buttons[9])
        markup.add(admin_buttons[4])
        markup.add(buttons[5])
    else:
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], buttons[4])
        markup.add(types.InlineKeyboardButton('📊 Statistics', callback_data='stats'))
        markup.add(buttons[5])
    return markup

def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout_to_use = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row_buttons_text in layout_to_use:
        markup.add(*[types.KeyboardButton(text) for text in row_buttons_text])
    return markup

def create_control_buttons(script_owner_id, file_name, is_running=True):
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

# --- New plan and payment menu functions ---
def create_plan_management_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('➕ Create Plan', callback_data='admin_create_plan'),
               types.InlineKeyboardButton('📋 View Plans', callback_data='admin_view_plans'))
    markup.row(types.InlineKeyboardButton('✏️ Edit Plan', callback_data='admin_edit_plan'),
               types.InlineKeyboardButton('🗑 Delete Plan', callback_data='admin_delete_plan'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_payment_settings_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(types.InlineKeyboardButton('💲 Zapupi Settings', callback_data='admin_zapupi_settings'),
               types.InlineKeyboardButton('🟣 Binance Settings', callback_data='admin_binance_settings'))
    markup.row(types.InlineKeyboardButton('📊 Transactions', callback_data='admin_transactions'),
               types.InlineKeyboardButton('📈 Revenue', callback_data='admin_revenue'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

# --- File handling (unchanged) ---
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
            security_warning_msg = f"🚨 File needs approval:\n👤 User: {user_id}\n📁 File: {file_name_zip}\n⚠️ Reason: {security_msg}"
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_zip_{user_id}_{file_name_zip}"),
                       types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_zip_{user_id}_{file_name_zip}"))
            for admin_id in admin_ids:
                try:
                    bot.send_message(admin_id, security_warning_msg, reply_markup=markup)
                except Exception as e:
                    logger.error(f"Failed to send security warning to admin {admin_id}: {e}")
            if user_id not in pending_zip_files:
                pending_zip_files[user_id] = {}
            pending_zip_files[user_id][file_name_zip] = downloaded_file_content
            bot.reply_to(message, f"⏳ File under security review. You will be notified upon approval.")
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

def process_zip_file(zip_path, user_id, user_folder, file_name_zip, message, temp_dir=None):
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
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
    except Exception as e:
        logger.error(f"Error processing zip file: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing zip: {str(e)}")
    finally:
        if cleanup_temp and temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.error(f"Failed to clean temp dir {temp_dir}: {e}", exc_info=True)

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"❌ Error processing JS file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing JS file: {str(e)}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"❌ Error processing Python file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing Python file: {str(e)}")

# --- run_script and run_js_script (unchanged) ---
def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        return
    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run Python script: {script_path} (Key: {script_key}) for user {script_owner_id}")
    try:
        if not os.path.exists(script_path):
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
                        success, _ = attempt_install_pip(module_name, message_obj_for_reply)
                        if success:
                            logger.info(f"Install OK for {module_name}. Retrying run_script...")
                            bot.reply_to(message_obj_for_reply, f"🔄 Install successful. Retrying '{file_name}'...")
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"❌ Install failed. Cannot run '{file_name}'.")
                            return
                    else:
                        error_summary = stderr[:500]
                        bot.reply_to(message_obj_for_reply, f"❌ Error in script pre-check for '{file_name}':\n```\n{error_summary}\n```\nFix the script.", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                logger.info("Python Pre-check timed out (>5s), imports likely OK. Killing check process.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                logger.error(f"Python interpreter not found: {sys.executable}")
                bot.reply_to(message_obj_for_reply, f"❌ Error: Python interpreter '{sys.executable}' not found.")
                return
            except Exception as e:
                logger.error(f"Error in Python pre-check for {script_key}: {e}", exc_info=True)
                bot.reply_to(message_obj_for_reply, f"❌ Unexpected error in script pre-check for '{file_name}': {e}")
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
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file '{log_file_path}': {e}")
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
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'py', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ Python script '{file_name}' started! (PID: {process.pid}) (For User: {script_owner_id})")
        except FileNotFoundError:
            logger.error(f"Python interpreter {sys.executable} not found for long run {script_key}")
            bot.reply_to(message_obj_for_reply, f"❌ Error: Python interpreter '{sys.executable}' not found.")
            if log_file and not log_file.closed:
                log_file.close()
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            error_msg = f"❌ Error starting Python script '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            bot.reply_to(message_obj_for_reply, error_msg)
            if process and process.poll() is None:
                logger.warning(f"Killing potentially started Python process {process.pid} for {script_key}")
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ Unexpected error running Python script '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message_obj_for_reply, error_msg)
        if script_key in bot_scripts:
            logger.warning(f"Cleaning up {script_key} due to error in run_script.")
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        return
    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run JS script: {script_path} (Key: {script_key}) for user {script_owner_id}")
    try:
        if not os.path.exists(script_path):
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
                            success, _ = attempt_install_npm(module_name, user_folder, message_obj_for_reply)
                            if success:
                                logger.info(f"NPM Install OK for {module_name}. Retrying run_js_script...")
                                bot.reply_to(message_obj_for_reply, f"🔄 NPM Install successful. Retrying '{file_name}'...")
                                time.sleep(2)
                                threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                return
                            else:
                                bot.reply_to(message_obj_for_reply, f"❌ NPM Install failed. Cannot run '{file_name}'.")
                                return
                    error_summary = stderr[:500]
                    bot.reply_to(message_obj_for_reply, f"❌ Error in JS script pre-check for '{file_name}':\n```\n{error_summary}\n```\nFix script or install manually.", parse_mode='Markdown')
                    return
            except subprocess.TimeoutExpired:
                logger.info("JS Pre-check timed out (>5s), imports likely OK. Killing check process.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                error_msg = "❌ Error: 'node' not found. Ensure Node.js is installed for JS files."
                logger.error(error_msg)
                bot.reply_to(message_obj_for_reply, error_msg)
                return
            except Exception as e:
                logger.error(f"Error in JS pre-check for {script_key}: {e}", exc_info=True)
                bot.reply_to(message_obj_for_reply, f"❌ Unexpected error in JS pre-check for '{file_name}': {e}")
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
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file '{log_file_path}': {e}")
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
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'js', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ JS script '{file_name}' started! (PID: {process.pid}) (For User: {script_owner_id})")
        except FileNotFoundError:
            error_msg = "❌ Error: 'node' not found for long run. Ensure Node.js is installed."
            logger.error(error_msg)
            if log_file and not log_file.closed:
                log_file.close()
            bot.reply_to(message_obj_for_reply, error_msg)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            error_msg = f"❌ Error starting JS script '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            bot.reply_to(message_obj_for_reply, error_msg)
            if process and process.poll() is None:
                logger.warning(f"Killing potentially started JS process {process.pid} for {script_key}")
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ Unexpected error running JS script '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message_obj_for_reply, error_msg)
        if script_key in bot_scripts:
            logger.warning(f"Cleaning up {script_key} due to error in run_js_script.")
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

# --- Core logic functions (modified to fix expiry_info bug) ---
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    logger.info(f"Welcome request from user_id: {user_id}")

    if is_user_banned(user_id):
        bot.send_message(chat_id, "❌ You are banned from using this bot.")
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
            owner_notification = (f"🎉 New user!\n👤 Name: {user_name}\n🆔 ID: `{user_id}`")
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"⚠️ Failed to notify owner about new user {user_id}: {e}")

    # ---- FIX: initialize expiry_info and limit_str ----
    expiry_info = ""
    limit_str = "Unlimited"

    active_plan = get_user_active_plan(user_id)
    if active_plan:
        expiry_date = active_plan['expiry_date']
        days_left = (expiry_date - datetime.now()).days
        user_status = f"⭐ Premium (Plan {active_plan['plan_id']})"
        expiry_info = f"\n⏳ Expires in: {days_left} days"
        limit_str = str(active_plan['bot_limit'])
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

    current_files = get_user_file_count(user_id)
    welcome_msg_text = (f"〽️ Welcome, {user_name}!\n\n🆔 Your User ID: `{user_id}`\n"
                        f"🔰 Your Status: {user_status}{expiry_info}\n"
                        f"📁 Files Uploaded: {current_files} / {limit_str}\n\n"
                        f"🤖 Host & run Python (`.py`) or JS (`.js`) scripts.\n"
                        f"   Upload single scripts or `.zip` archives.\n"
                        f"📦 Manual module installation available\n"
                        f"💳 To buy a plan, use /plans or the button below.\n\n"
                        f"👇 Use buttons or type commands.")

    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error sending welcome to {user_id}: {e}", exc_info=True)

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
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
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
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            user_level = "⭐ Premium (Legacy)"
        else:
            user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     f"👤 Your Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Error during speed test (cmd): {e}", exc_info=True)
        bot.edit_message_text("❌ Error during speed test.", chat_id, wait_msg.message_id)

def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    bot.reply_to(message, "Click to contact Owner:", reply_markup=markup)

def _logic_manual_install(message):
    manual_install_module_init(message)

def _logic_help(message):
    help_text = """
🤖 **PETRO Hosting Bot Help Guide**

**📌 Basic Commands:**
• /start - Start the bot
• /help - Show this help message
• /status - Show bot statistics
• /plans - View available subscription plans
• /buy - Purchase a plan
• /myplan - Check your current subscription

**📁 File Management:**
• Upload `.py` or `.js` files directly
• Upload `.zip` archives with multiple files
• Auto-installs dependencies from `requirements.txt` or `package.json`

**📦 Module Installation:**
• Auto-install missing Python/Node modules
• Manual install via "📦 Manual Install" button
• Admin can install modules for users

**💳 Subscription & Payments:**
• View available plans with /plans
• Purchase a plan with /buy
• Pay via Zapupi or Binance
• Automatic activation after payment
• Check your subscription with /myplan

**👑 Admin Features:**
• User management (ban/unban)
• Set custom file limits
• Manage mandatory channels
• Broadcast messages
• Run all user scripts
• Create, edit, delete subscription plans
• Configure payment gateways (Zapupi, Binance)
• View transactions and revenue

**⚙️ Tips:**
1. Make sure your scripts don't contain dangerous commands
2. Join all required channels
3. Contact owner for support

**Support:** @Z4X_Silent_Boy1
**Updates:** @DigitalWorld1318
"""
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
    total_users = len(active_users)
    total_files_records = sum(len(files) for files in user_files.values())
    running_bots_count = 0
    user_running_bots = 0
    for script_key_iter, script_info_iter in list(bot_scripts.items()):
        s_owner_id, _ = script_key_iter.split('_', 1)
        if is_bot_running(int(s_owner_id), script_info_iter['file_name']):
            running_bots_count += 1
            if int(s_owner_id) == user_id:
                user_running_bots += 1
    stats_msg_base = (f"📊 Bot Statistics:\n\n"
                      f"👥 Total Users: {total_users}\n"
                      f"🚫 Banned Users: {len(banned_users)}\n"
                      f"📂 Total File Records: {total_files_records}\n"
                      f"🟢 Total Active Bots: {running_bots_count}\n")
    if user_id in admin_ids:
        stats_msg_admin = (f"🔒 Bot Status: {'🔴 Locked' if bot_locked else '🟢 Unlocked'}\n"
                           f"📢 Mandatory Channels: {len(mandatory_channels)}\n"
                           f"⚙️ Custom Limits: {len(user_limits)}\n"
                           f"📋 Plans: {len(plans_cache)}\n"
                           f"🤖 Your Running Bots: {user_running_bots}")
        stats_msg = stats_msg_base + stats_msg_admin
    else:
        stats_msg = stats_msg_base + f"🤖 Your Running Bots: {user_running_bots}"
    bot.reply_to(message, stats_msg)

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
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
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

# --- NEW: Admin plan & payment management functions ---
def _logic_manage_plans(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "📋 Plan Management\nCreate, edit, delete plans.", reply_markup=create_plan_management_menu())

def _logic_payment_settings(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "💲 Payment Settings\nConfigure payment gateways.", reply_markup=create_payment_settings_menu())

# --- NEW: User commands for plans and purchase ---
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
    if not plan:
        bot.reply_to(message, "❌ You don't have an active subscription plan.\nUse /plans to view and purchase.")
        return
    expiry = plan['expiry_date']
    days_left = (expiry - datetime.now()).days
    text = f"📅 **Your Subscription:**\n\nPlan ID: {plan['plan_id']}\nBot Limit: {plan['bot_limit']}\nExpires: {expiry.strftime('%Y-%m-%d %H:%M:%S')}\nDays left: {days_left}\n\nUse /plans to renew or upgrade."
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['manageplans'])
def command_manageplans(message):
    _logic_manage_plans(message)

@bot.message_handler(commands=['paymentsettings'])
def command_paymentsettings(message):
    _logic_payment_settings(message)

# --- Existing command handlers (unchanged) ---
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
    "📞 Contact Owner": _logic_contact_owner,
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
    "📋 Plan Management": _logic_manage_plans
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func:
        logic_func(message)
    else:
        logger.warning(f"Button text '{message.text}' matched but no logic func.")

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
    _logic_contact_owner(message)
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

# --- Document handler (unchanged) ---
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
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)", parse_mode='Markdown')
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
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file_content)
            logger.info(f"Saved single file to {file_path}")
            is_safe, security_msg = check_code_security(file_path, file_ext[1:])
            if not is_safe:
                security_warning_msg = f"🚨 File needs approval:\n👤 User: {user_id}\n📁 File: {file_name}\n⚠️ Reason: {security_msg}"
                markup = types.InlineKeyboardMarkup()
                markup.row(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_file_{user_id}_{file_name}"),
                           types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_file_{user_id}_{file_name}"))
                for admin_id in admin_ids:
                    try:
                        bot.send_message(admin_id, security_warning_msg, reply_markup=markup)
                    except Exception as e:
                        logger.error(f"Failed to send security warning to admin {admin_id}: {e}")
                bot.reply_to(message, f"⏳ File under security review. You will be notified upon approval.")
                return
            if file_ext == '.js':
                handle_js_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py':
                handle_py_file(file_path, user_id, user_folder, file_name, message)
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"Telegram API Error handling file for {user_id}: {e}", exc_info=True)
        if "file is too big" in str(e).lower():
            bot.reply_to(message, f"❌ Telegram API Error: File too large to download (~20MB limit).")
        else:
            bot.reply_to(message, f"❌ Telegram API Error: {str(e)}. Try later.")
    except Exception as e:
        logger.error(f"❌ General error handling file for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Unexpected error: {str(e)}")

# --- Callback query handler (full) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    logger.info(f"Callback: User={user_id}, Data='{data}'")
    if is_user_banned(user_id) and data not in ['back_to_main']:
        bot.answer_callback_query(call.id, "❌ You are banned from using this bot.", show_alert=True)
        return
    if data not in ['check_subscription_status', 'back_to_main', 'manual_install']:
        is_subscribed, not_joined = check_mandatory_subscription(user_id)
        if not is_subscribed and user_id not in admin_ids:
            subscription_message, markup = create_subscription_check_message(not_joined)
            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_text(subscription_message, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
            except:
                bot.send_message(call.message.chat.id, subscription_message, reply_markup=markup, parse_mode='Markdown')
            return
    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats', 'check_subscription_status', 'manual_install']:
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
        elif data.startswith('approve_file_'):
            admin_required_callback(call, process_approve_file)
        elif data.startswith('reject_file_'):
            admin_required_callback(call, process_reject_file)
        elif data.startswith('approve_zip_'):
            admin_required_callback(call, process_approve_zip)
        elif data.startswith('reject_zip_'):
            admin_required_callback(call, process_reject_zip)
        # NEW plan and payment callbacks
        elif data.startswith('buy_plan_'):
            callback_buy_plan(call)
        elif data.startswith('pay_zapupi_'):
            callback_pay_zapupi(call)
        elif data.startswith('pay_binance_'):
            callback_pay_binance(call)
        elif data.startswith('verify_zapupi_'):
            callback_verify_zapupi(call)
        elif data.startswith('verify_binance_'):
            callback_verify_binance(call)
        elif data == 'cancel_purchase':
            callback_cancel_purchase(call)
        elif data == 'admin_create_plan':
            admin_required_callback(call, callback_admin_create_plan)
        elif data == 'admin_view_plans':
            admin_required_callback(call, callback_admin_view_plans)
        elif data == 'admin_edit_plan':
            admin_required_callback(call, callback_admin_edit_plan)
        elif data == 'admin_delete_plan':
            admin_required_callback(call, callback_admin_delete_plan)
        elif data == 'admin_zapupi_settings':
            admin_required_callback(call, callback_admin_zapupi_settings)
        elif data == 'admin_binance_settings':
            admin_required_callback(call, callback_admin_binance_settings)
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
        elif data == 'binance_set_keys':
            admin_required_callback(call, callback_binance_set_keys)
        elif data == 'binance_toggle':
            admin_required_callback(call, callback_binance_toggle)
        elif data == 'binance_delete':
            admin_required_callback(call, callback_binance_delete)
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

# --- User callbacks (unchanged) ---
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
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
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
                reply_markup=create_control_buttons(script_owner_id, file_name, is_running),
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
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
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
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
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
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            user_level = "⭐ Premium (Legacy)"
        else:
            user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     f"👤 Your Level: {user_level}")
        bot.answer_callback_query(call.id)
        bot.edit_message_text(speed_msg, chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
    except Exception as e:
        logger.error(f"Error during speed test (cb): {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error in speed test.", show_alert=True)
        try:
            bot.edit_message_text("〽️ Main Menu", chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
        except Exception:
            pass

# ---- FIX: back_to_main_callback with expiry_info fixed ----
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

    # ---- FIX: initialize expiry_info and limit_str ----
    expiry_info = ""
    limit_str = "Unlimited"

    active_plan = get_user_active_plan(user_id)
    if active_plan:
        user_status = f"⭐ Premium (Plan {active_plan['plan_id']})"
        days_left = (active_plan['expiry_date'] - datetime.now()).days
        expiry_info = f"\n⏳ Expires in: {days_left} days"
        limit_str = str(active_plan['bot_limit'])
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

    current_files = get_user_file_count(user_id)
    main_menu_text = (f"〽️ Welcome back, {call.from_user.first_name}!\n\n🆔 ID: `{user_id}`\n"
                      f"🔰 Status: {user_status}{expiry_info}\n📁 Files: {current_files} / {limit_str}\n\n"
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

# --- Admin callbacks (existing, unchanged) ---
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

# --- User Management Callbacks (unchanged) ---
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
            info_parts.append(f"⭐ **Plan:** {active_plan['plan_id']} (Bot limit: {active_plan['bot_limit']})")
            info_parts.append(f"📅 **Expiry:** {active_plan['expiry_date'].strftime('%Y-%m-%d %H:%M:%S')}")
            days_left = (active_plan['expiry_date'] - datetime.now()).days
            info_parts.append(f"⏳ **Days left:** {days_left}")
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
        if user_id in active_users:
            info_parts.append("🟢 **Status:** Active")
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

# --- Admin Settings Callbacks (unchanged) ---
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
        info_parts.append(f"• Plans: {len(plans_cache)}")
        info_text = "\n".join(info_parts)
        bot.edit_message_text(info_text, call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_settings_menu(), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error showing system info: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error showing system info.", show_alert=True)

def bot_performance_callback(call):
    bot.answer_callback_query(call.id)
    try:
        performance_parts = []
        running_scripts = len(bot_scripts)
        total_files = sum(len(files) for files in user_files.values())
        performance_parts.append("📈 **Bot Performance Metrics:**")
        performance_parts.append(f"• Running Scripts: {running_scripts}")
        performance_parts.append(f"• Total Scripts: {total_files}")
        performance_parts.append(f"• Uptime Ratio: {running_scripts}/{total_files} ({running_scripts/total_files*100:.1f}% if total > 0)")
        try:
            bot_process = psutil.Process()
            memory_usage = bot_process.memory_info().rss / 1024 / 1024
            cpu_usage = bot_process.cpu_percent(interval=0.5)
            performance_parts.append(f"\n💾 **Resource Usage:**")
            performance_parts.append(f"• Memory: {memory_usage:.1f} MB")
            performance_parts.append(f"• CPU: {cpu_usage:.1f}%")
        except Exception as e:
            performance_parts.append(f"\n⚠️ Resource stats error: {str(e)}")
        performance_parts.append(f"\n🗄️ **Database:**")
        performance_parts.append(f"• Active Users: {len(active_users)}")
        performance_parts.append(f"• Subscriptions: {len(user_subscriptions)}")
        performance_parts.append(f"• Banned Users: {len(banned_users)}")
        performance_parts.append(f"• Custom Limits: {len(user_limits)}")
        performance_parts.append(f"• Plans: {len(plans_cache)}")
        performance_text = "\n".join(performance_parts)
        bot.edit_message_text(performance_text, call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_settings_menu(), parse_mode='Markdown')
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

# --- Mandatory Channels Callbacks (unchanged) ---
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

# --- Security Approval Callbacks (unchanged) ---
def process_approve_file(call):
    data_parts = call.data.split('_')
    if len(data_parts) < 4:
        bot.answer_callback_query(call.id, "❌ Invalid data.", show_alert=True)
        return
    user_id = int(data_parts[2])
    file_name = '_'.join(data_parts[3:])
    user_folder = get_user_folder(user_id)
    file_path = os.path.join(user_folder, file_name)
    if not os.path.exists(file_path):
        bot.answer_callback_query(call.id, "❌ File not found.", show_alert=True)
        return
    file_ext = os.path.splitext(file_name)[1].lower()
    try:
        if file_ext == '.js':
            handle_js_file(file_path, user_id, user_folder, file_name, call.message)
        elif file_ext == '.py':
            handle_py_file(file_path, user_id, user_folder, file_name, call.message)
        bot.answer_callback_query(call.id, "✅ File approved!")
        bot.edit_message_text(f"✅ File `{file_name}` approved for user `{user_id}`",
                              call.message.chat.id, call.message.message_id)
        try:
            bot.send_message(user_id, f"✅ Your file `{file_name}` has been approved and started.")
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error processing approved file: {e}")
        bot.answer_callback_query(call.id, "❌ Error processing file.", show_alert=True)

def process_reject_file(call):
    data_parts = call.data.split('_')
    if len(data_parts) < 4:
        bot.answer_callback_query(call.id, "❌ Invalid data.", show_alert=True)
        return
    user_id = int(data_parts[2])
    file_name = '_'.join(data_parts[3:])
    user_folder = get_user_folder(user_id)
    file_path = os.path.join(user_folder, file_name)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Error deleting rejected file: {e}")
    bot.answer_callback_query(call.id, "❌ File rejected!")
    bot.edit_message_text(f"❌ File `{file_name}` rejected for user `{user_id}`",
                          call.message.chat.id, call.message.message_id)
    try:
        bot.send_message(user_id, f"❌ Your file `{file_name}` has been rejected for security reasons.")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

def process_approve_zip(call):
    data_parts = call.data.split('_')
    if len(data_parts) < 4:
        bot.answer_callback_query(call.id, "❌ Invalid data.", show_alert=True)
        return
    user_id = int(data_parts[2])
    file_name = '_'.join(data_parts[3:])
    if user_id in pending_zip_files and file_name in pending_zip_files[user_id]:
        file_content = pending_zip_files[user_id][file_name]
        user_folder = get_user_folder(user_id)
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_approve_")
            zip_path = os.path.join(temp_dir, file_name)
            with open(zip_path, 'wb') as f:
                f.write(file_content)
            process_zip_file(zip_path, user_id, user_folder, file_name, call.message, temp_dir)
            if user_id in pending_zip_files and file_name in pending_zip_files[user_id]:
                del pending_zip_files[user_id][file_name]
                if not pending_zip_files[user_id]:
                    del pending_zip_files[user_id]
            bot.answer_callback_query(call.id, "✅ Archive approved!")
            bot.edit_message_text(f"✅ Archive `{file_name}` approved for user `{user_id}`",
                                  call.message.chat.id, call.message.message_id)
            try:
                bot.send_message(user_id, f"✅ Your archive `{file_name}` has been approved and processed.")
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error processing approved zip: {e}", exc_info=True)
            bot.answer_callback_query(call.id, "❌ Error processing archive.", show_alert=True)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.error(f"Error cleaning temp dir: {e}")
    else:
        bot.answer_callback_query(call.id, "❌ File content not found. Ask user to re-upload.", show_alert=True)

def process_reject_zip(call):
    data_parts = call.data.split('_')
    if len(data_parts) < 4:
        bot.answer_callback_query(call.id, "❌ Invalid data.", show_alert=True)
        return
    user_id = int(data_parts[2])
    file_name = '_'.join(data_parts[3:])
    if user_id in pending_zip_files and file_name in pending_zip_files[user_id]:
        del pending_zip_files[user_id][file_name]
        if not pending_zip_files[user_id]:
            del pending_zip_files[user_id]
    bot.answer_callback_query(call.id, "❌ Archive rejected!")
    bot.edit_message_text(f"❌ Archive `{file_name}` rejected for user `{user_id}`",
                          call.message.chat.id, call.message.message_id)
    try:
        bot.send_message(user_id, f"❌ Your archive `{file_name}` has been rejected for security reasons.")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

# --- NEW: Plan and Payment Callback Implementations ---
def show_plans_to_user(chat_id, user_id):
    plans = list_plans(active_only=True)
    if not plans:
        bot.send_message(chat_id, "❌ No plans available at the moment.")
        return
    text = "📋 **Available Plans:**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for plan in plans:
        text += f"*{plan['name']}*\n"
        text += f"💰 Price: ${plan['price']:.2f}\n"
        text += f"📆 Duration: {plan['duration_days']} days\n"
        text += f"🤖 Bot Limit: {plan['bot_limit']}\n"
        text += f"📝 {plan['description']}\n\n"
        markup.add(types.InlineKeyboardButton(f"Purchase {plan['name']}", callback_data=f"buy_plan_{plan['id']}"))
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

def initiate_purchase(user_id, plan_id, chat_id):
    plan = plans_cache.get(int(plan_id))
    if not plan or plan['status'] != 'active':
        bot.send_message(chat_id, "❌ Plan not available.")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    if zapupi_settings.get('enabled'):
        markup.add(types.InlineKeyboardButton("Pay with Zapupi", callback_data=f"pay_zapupi_{plan_id}"))
    if binance_settings.get('enabled'):
        markup.add(types.InlineKeyboardButton("Pay with Binance", callback_data=f"pay_binance_{plan_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Cancel", callback_data="cancel_purchase"))
    text = f"💳 **Purchase {plan['name']}**\nPrice: ${plan['price']:.2f}\nChoose payment method:"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

def handle_payment_gateway(user_id, plan_id, gateway, chat_id):
    plan = plans_cache.get(int(plan_id))
    if not plan:
        bot.send_message(chat_id, "❌ Plan not found.")
        return
    amount = plan['price']
    if gateway == 'zapupi':
        invoice_id, payment_url = create_zapupi_invoice(user_id, plan_id, amount)
        if not invoice_id:
            bot.send_message(chat_id, f"❌ Failed to create Zapupi invoice: {payment_url}")
            return
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''INSERT INTO transactions (user_id, plan_id, gateway, transaction_id, amount, currency, status)
                     VALUES (?, ?, ?, ?, ?, 'USD', 'pending')''',
                  (user_id, plan_id, 'zapupi', invoice_id, amount))
        trans_id = c.lastrowid
        conn.commit()
        conn.close()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Pay Now", url=payment_url))
        markup.add(types.InlineKeyboardButton("✅ I've Paid (Verify)", callback_data=f"verify_zapupi_{invoice_id}"))
        bot.send_message(chat_id, f"🔗 Click the button below to complete payment.\nOnce paid, click 'I've Paid' to verify.", reply_markup=markup)
    elif gateway == 'binance':
        order_id, payment_url = create_binance_payment(user_id, plan_id, amount)
        if not order_id:
            bot.send_message(chat_id, f"❌ Failed to create Binance order: {payment_url}")
            return
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''INSERT INTO transactions (user_id, plan_id, gateway, transaction_id, amount, currency, status)
                     VALUES (?, ?, ?, ?, ?, 'USDT', 'pending')''',
                  (user_id, plan_id, 'binance', order_id, amount))
        trans_id = c.lastrowid
        conn.commit()
        conn.close()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Pay Now", url=payment_url))
        markup.add(types.InlineKeyboardButton("✅ I've Paid (Verify)", callback_data=f"verify_binance_{order_id}"))
        bot.send_message(chat_id, f"🔗 Click the button below to complete payment.\nOnce paid, click 'I've Paid' to verify.", reply_markup=markup)

def verify_payment_manually(user_id, transaction_id, gateway, chat_id):
    if gateway == 'zapupi':
        success, msg = verify_zapupi_payment(transaction_id)
    else:
        success, msg = verify_binance_payment(transaction_id)
    if success:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT id, user_id, plan_id FROM transactions WHERE transaction_id = ? AND gateway = ? AND status = "pending"',
                  (transaction_id, gateway))
        row = c.fetchone()
        conn.close()
        if not row:
            bot.send_message(chat_id, "❌ Transaction not found or already processed.")
            return
        trans_id, user_id_db, plan_id = row
        update_transaction_status(trans_id, 'completed')
        success2, result = activate_user_plan(user_id_db, plan_id, trans_id)
        if success2:
            expiry_date = result
            bot.send_message(chat_id, f"✅ Payment verified! Your plan is active until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}.")
            bot.send_message(user_id_db, f"🎉 Your subscription has been activated!")
        else:
            bot.send_message(chat_id, f"❌ Failed to activate plan: {result}")
    else:
        bot.send_message(chat_id, f"❌ Payment not confirmed yet. Status: {msg}\nPlease wait or contact support.")

def callback_buy_plan(call):
    user_id = call.from_user.id
    plan_id = int(call.data.split('_')[2])
    initiate_purchase(user_id, plan_id, call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_pay_zapupi(call):
    user_id = call.from_user.id
    plan_id = int(call.data.split('_')[2])
    handle_payment_gateway(user_id, plan_id, 'zapupi', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_pay_binance(call):
    user_id = call.from_user.id
    plan_id = int(call.data.split('_')[2])
    handle_payment_gateway(user_id, plan_id, 'binance', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_verify_zapupi(call):
    user_id = call.from_user.id
    invoice_id = call.data.split('_')[2]
    verify_payment_manually(user_id, invoice_id, 'zapupi', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_verify_binance(call):
    user_id = call.from_user.id
    order_id = call.data.split('_')[2]
    verify_payment_manually(user_id, order_id, 'binance', call.message.chat.id)
    bot.answer_callback_query(call.id)

def callback_cancel_purchase(call):
    bot.answer_callback_query(call.id, "Purchase cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)

def callback_admin_create_plan(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "📝 **Create New Plan**\n\nSend plan details in format:\n`name | price | duration_days | bot_limit | description`\nExample: `Premium | 10 | 30 | 5 | Premium plan with 5 bots`\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_create_plan)
    bot.answer_callback_query(call.id)

def process_create_plan(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Plan creation cancelled.")
        return
    parts = message.text.split('|')
    if len(parts) != 5:
        bot.reply_to(message, "❌ Invalid format. Please use: `name | price | duration_days | bot_limit | description`")
        return
    name = parts[0].strip()
    try:
        price = float(parts[1].strip())
        duration = int(parts[2].strip())
        bot_limit = int(parts[3].strip())
    except ValueError:
        bot.reply_to(message, "❌ Price, duration, and bot limit must be numeric.")
        return
    description = parts[4].strip()
    plan_id = create_plan(name, price, duration, bot_limit, description)
    bot.reply_to(message, f"✅ Plan created with ID {plan_id}.")

def callback_admin_view_plans(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    plans = list_plans(active_only=False)
    if not plans:
        bot.edit_message_text("No plans found.", call.message.chat.id, call.message.message_id)
        return
    text = "📋 **All Plans**\n\n"
    for p in plans:
        text += f"ID: {p['id']}\nName: {p['name']}\nPrice: ${p['price']:.2f}\nDuration: {p['duration_days']} days\nBot Limit: {p['bot_limit']}\nStatus: {p['status']}\nDesc: {p['description']}\n\n"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_admin_edit_plan(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "✏️ **Edit Plan**\n\nSend plan ID and fields to update in format:\n`plan_id | field=value | field2=value2`\n\nAvailable fields: name, price, duration_days, bot_limit, description, status (active/inactive)\nExample: `3 | price=12.50 | status=inactive`\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_edit_plan)
    bot.answer_callback_query(call.id)

def process_edit_plan(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Edit cancelled.")
        return
    parts = message.text.split('|')
    if len(parts) < 2:
        bot.reply_to(message, "❌ Invalid format. Use: `plan_id | field=value`")
        return
    try:
        plan_id = int(parts[0].strip())
    except ValueError:
        bot.reply_to(message, "❌ Plan ID must be integer.")
        return
    updates = {}
    for part in parts[1:]:
        kv = part.strip().split('=')
        if len(kv) != 2:
            bot.reply_to(message, f"❌ Invalid key=value: {part}")
            return
        key, value = kv[0].strip(), kv[1].strip()
        if key in ['name', 'description', 'status']:
            updates[key] = value
        elif key in ['price', 'duration_days', 'bot_limit']:
            try:
                updates[key] = float(value) if key == 'price' else int(value)
            except ValueError:
                bot.reply_to(message, f"❌ {key} must be numeric.")
                return
        else:
            bot.reply_to(message, f"❌ Unknown field: {key}")
            return
    try:
        update_plan(plan_id, **updates)
        bot.reply_to(message, f"✅ Plan {plan_id} updated.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error updating plan: {e}")

def callback_admin_delete_plan(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "🗑 **Delete Plan**\n\nSend plan ID to delete.\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_delete_plan)
    bot.answer_callback_query(call.id)

def process_delete_plan(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Delete cancelled.")
        return
    try:
        plan_id = int(message.text.strip())
        delete_plan(plan_id)
        bot.reply_to(message, f"✅ Plan {plan_id} deleted.")
    except ValueError:
        bot.reply_to(message, "❌ Invalid plan ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def callback_admin_zapupi_settings(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    current = zapupi_settings
    status = "✅ Enabled" if current.get('enabled') else "❌ Disabled"
    api_key = current.get('api_key', 'Not set')
    text = f"💲 **Zapupi Settings**\n\nAPI Key: {api_key[:4]}...{api_key[-4:] if api_key else 'N/A'}\nStatus: {status}\n\nChoose action:"
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
    msg = bot.send_message(call.message.chat.id, "🔑 Send Zapupi API Key:\n/cancel to cancel.")
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

def callback_admin_binance_settings(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    current = binance_settings
    status = "✅ Enabled" if current.get('enabled') else "❌ Disabled"
    api_key = current.get('api_key', 'Not set')
    secret_key = current.get('secret_key', 'Not set')
    text = f"🟣 **Binance Settings**\n\nAPI Key: {api_key[:4]}...{api_key[-4:] if api_key else 'N/A'}\nSecret Key: {secret_key[:4]}...{secret_key[-4:] if secret_key else 'N/A'}\nStatus: {status}\n\nChoose action:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ Set Keys", callback_data="binance_set_keys"),
               types.InlineKeyboardButton("🔄 Toggle Enable", callback_data="binance_toggle"),
               types.InlineKeyboardButton("🗑 Delete Keys", callback_data="binance_delete"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

def callback_binance_set_keys(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    msg = bot.send_message(call.message.chat.id, "🔑 Send Binance API Key and Secret Key in format:\n`api_key | secret_key`\n/cancel to cancel.")
    bot.register_next_step_handler(msg, process_binance_set_keys)
    bot.answer_callback_query(call.id)

def process_binance_set_keys(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    parts = message.text.split('|')
    if len(parts) != 2:
        bot.reply_to(message, "❌ Invalid format. Use: `api_key | secret_key`")
        return
    api_key = parts[0].strip()
    secret_key = parts[1].strip()
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM binance_settings')
    c.execute('INSERT INTO binance_settings (api_key, secret_key, gateway_enabled) VALUES (?, ?, 1)', (api_key, secret_key))
    conn.commit()
    conn.close()
    load_data()
    bot.reply_to(message, "✅ Binance keys saved and gateway enabled.")

def callback_binance_toggle(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    new_status = not binance_settings.get('enabled', False)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE binance_settings SET gateway_enabled = ?', (1 if new_status else 0,))
    conn.commit()
    conn.close()
    load_data()
    bot.answer_callback_query(call.id, f"Binance {'enabled' if new_status else 'disabled'}.")
    callback_admin_binance_settings(call)

def callback_binance_delete(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.")
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM binance_settings')
    conn.commit()
    conn.close()
    load_data()
    bot.answer_callback_query(call.id, "Binance keys deleted.")
    callback_admin_binance_settings(call)

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
    c.execute('SELECT SUM(amount) FROM transactions WHERE status = "completed" AND gateway = "binance"')
    binance_total = c.fetchone()[0] or 0
    conn.close()
    text = f"📈 **Revenue Report**\n\nTotal Revenue: ${total:.2f}\nTotal Transactions: {count}\n\nZapupi: ${zapupi_total:.2f}\nBinance: ${binance_total:.2f}"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

# --- Payment gateway core functions ---
def create_zapupi_invoice(user_id, plan_id, amount, currency='USD'):
    api_key = zapupi_settings.get('api_key')
    if not api_key:
        return None, "Zapupi API key not configured."
    url = "https://api.zapupi.com/v1/invoice"  # placeholder
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "amount": amount,
        "currency": currency,
        "description": f"Plan purchase for user {user_id}",
        "callback_url": "https://your-domain.com/webhook/zapupi",
        "metadata": {"user_id": user_id, "plan_id": plan_id}
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        invoice_id = data.get('invoice_id')
        payment_url = data.get('payment_url')
        return invoice_id, payment_url
    except Exception as e:
        logger.error(f"Zapupi invoice creation error: {e}")
        return None, str(e)

def verify_zapupi_payment(invoice_id):
    api_key = zapupi_settings.get('api_key')
    if not api_key:
        return False, "API key missing"
    url = f"https://api.zapupi.com/v1/invoice/{invoice_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        status = data.get('status')
        if status == 'paid':
            return True, "Paid"
        else:
            return False, f"Status: {status}"
    except Exception as e:
        logger.error(f"Zapupi verify error: {e}")
        return False, str(e)

def create_binance_payment(user_id, plan_id, amount, currency='USDT'):
    api_key = binance_settings.get('api_key')
    secret_key = binance_settings.get('secret_key')
    if not api_key or not secret_key:
        return None, "Binance keys not configured."
    url = "https://api.binance.com/sapi/v1/pay/order"  # placeholder
    timestamp = int(time.time() * 1000)
    params = {
        "timestamp": timestamp,
        "merchantTradeNo": f"PAY_{uuid.uuid4().hex[:10]}",
        "amount": amount,
        "currency": currency,
        "goodsName": f"Plan_{plan_id}",
        "goodsDetail": f"Plan purchase for user {user_id}",
        "callbackUrl": "https://your-domain.com/webhook/binance",
        "returnUrl": "https://t.me/your_bot"
    }
    query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    headers = {"X-Binance-APIKEY": api_key, "Content-Type": "application/json"}
    payload = params.copy()
    payload["signature"] = signature
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        order_id = data.get('orderId')
        payment_url = data.get('payment_url')
        return order_id, payment_url
    except Exception as e:
        logger.error(f"Binance payment creation error: {e}")
        return None, str(e)

def verify_binance_payment(order_id):
    api_key = binance_settings.get('api_key')
    secret_key = binance_settings.get('secret_key')
    if not api_key or not secret_key:
        return False, "Keys missing"
    timestamp = int(time.time() * 1000)
    url = f"https://api.binance.com/sapi/v1/pay/order/query?timestamp={timestamp}&orderId={order_id}"
    query_string = f"orderId={order_id}&timestamp={timestamp}"
    signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    url += f"&signature={signature}"
    headers = {"X-Binance-APIKEY": api_key}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        status = data.get('status')
        if status == 'PAID':
            return True, "Paid"
        else:
            return False, f"Status: {status}"
    except Exception as e:
        logger.error(f"Binance verify error: {e}")
        return False, str(e)

def process_zapupi_webhook(data):
    invoice_id = data.get('invoice_id')
    status = data.get('status')
    if status != 'paid':
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, user_id, plan_id FROM transactions WHERE transaction_id = ? AND gateway = "zapupi"', (invoice_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        logger.warning(f"Transaction not found for invoice_id {invoice_id}")
        return
    trans_id, user_id, plan_id = row
    update_transaction_status(trans_id, 'completed')
    success, result = activate_user_plan(user_id, plan_id, trans_id)
    if success:
        expiry_date = result
        bot.send_message(user_id, f"✅ Payment confirmed! Your plan has been activated until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}.")
        logger.info(f"Plan activated for user {user_id}, plan {plan_id}")
    else:
        logger.error(f"Failed to activate plan for user {user_id}: {result}")

def process_binance_webhook(data):
    order_id = data.get('orderId')
    status = data.get('status')
    if status != 'PAID':
        return
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, user_id, plan_id FROM transactions WHERE transaction_id = ? AND gateway = "binance"', (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        logger.warning(f"Transaction not found for order_id {order_id}")
        return
    trans_id, user_id, plan_id = row
    update_transaction_status(trans_id, 'completed')
    success, result = activate_user_plan(user_id, plan_id, trans_id)
    if success:
        expiry_date = result
        bot.send_message(user_id, f"✅ Payment confirmed! Your plan has been activated until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}.")
        logger.info(f"Plan activated for user {user_id}, plan {plan_id}")
    else:
        logger.error(f"Failed to activate plan for user {user_id}: {result}")

def update_transaction_status(trans_id, status):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE transactions SET status = ?, updated_at = datetime("now") WHERE id = ?', (status, trans_id))
    conn.commit()
    conn.close()

def activate_user_plan(user_id, plan_id, transaction_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT duration_days, bot_limit FROM plans WHERE id = ?', (plan_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Plan not found"
    duration_days, bot_limit = row
    start_date = datetime.now()
    expiry_date = start_date + timedelta(days=duration_days)
    c.execute('UPDATE user_plans SET active = 0 WHERE user_id = ? AND active = 1', (user_id,))
    c.execute('''INSERT INTO user_plans (user_id, plan_id, start_date, expiry_date, bot_limit, active, transaction_id)
                 VALUES (?, ?, ?, ?, ?, 1, ?)''',
              (user_id, plan_id, start_date.isoformat(), expiry_date.isoformat(), bot_limit, transaction_id))
    conn.commit()
    conn.close()
    save_subscription(user_id, expiry_date)
    return True, expiry_date

def create_plan(name, price, duration_days, bot_limit, description):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''INSERT INTO plans (name, price, duration_days, bot_limit, description, status)
                 VALUES (?, ?, ?, ?, ?, 'active')''',
              (name, price, duration_days, bot_limit, description))
    plan_id = c.lastrowid
    conn.commit()
    conn.close()
    load_data()
    return plan_id

def update_plan(plan_id, name=None, price=None, duration_days=None, bot_limit=None, description=None, status=None):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    updates = []
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if price is not None:
        updates.append("price = ?")
        params.append(price)
    if duration_days is not None:
        updates.append("duration_days = ?")
        params.append(duration_days)
    if bot_limit is not None:
        updates.append("bot_limit = ?")
        params.append(bot_limit)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    updates.append("updated_at = datetime('now')")
    params.append(plan_id)
    sql = f"UPDATE plans SET {', '.join(updates)} WHERE id = ?"
    c.execute(sql, params)
    conn.commit()
    conn.close()
    load_data()

def delete_plan(plan_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM plans WHERE id = ?', (plan_id,))
    conn.commit()
    conn.close()
    load_data()

def list_plans(active_only=True):
    if active_only:
        return [p for p in plans_cache.values() if p['status'] == 'active']
    return list(plans_cache.values())

def ensure_node_installed():
    logger.info("Checking Node.js environment...")
    node_path = shutil.which('node')
    npm_path = shutil.which('npm')
    if not node_path or not npm_path:
        common_dirs = [
            "/usr/bin", "/usr/local/bin", "/usr/sbin", "/usr/local/sbin", "/bin", "/sbin",
            os.path.expanduser("~/.nvm/versions/node/*/bin"),
            os.path.expanduser("~/.local/bin"),
            "/opt/nodejs/bin"
        ]
        import glob
        expanded_dirs = []
        for d in common_dirs:
            if '*' in d:
                expanded_dirs.extend(glob.glob(d))
            else:
                expanded_dirs.append(d)
        for d in expanded_dirs:
            n_p = os.path.join(d, 'node')
            nm_p = os.path.join(d, 'npm')
            if not node_path and os.path.exists(n_p):
                node_path = n_p
            if not npm_path and os.path.exists(nm_p):
                npm_path = nm_p
            if node_path and npm_path:
                if d not in os.environ["PATH"]:
                    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
                    logger.info(f"Added {d} to PATH.")
                break
    if not node_path or not npm_path:
        logger.warning("Node.js or npm not found. Attempting auto-installation...")
        try:
            if shutil.which('apt-get'):
                logger.info("Installing via apt-get...")
                subprocess.run(['sudo', 'apt-get', 'update', '-y'], check=False, capture_output=True)
                subprocess.run(['sudo', 'apt-get', 'install', '-y', 'nodejs', 'npm'], check=False, capture_output=True)
            elif shutil.which('yum'):
                logger.info("Installing via yum...")
                subprocess.run(['sudo', 'yum', 'install', '-y', 'nodejs', 'npm'], check=False, capture_output=True)
            node_path = shutil.which('node')
            npm_path = shutil.which('npm')
        except Exception as e:
            logger.error(f"Auto-installation failed: {e}")
    if node_path and npm_path:
        try:
            node_v = subprocess.run([node_path, '-v'], capture_output=True, text=True).stdout.strip()
            npm_v = subprocess.run([npm_path, '-v'], capture_output=True, text=True).stdout.strip()
            logger.info(f"Node.js ({node_v}) and npm ({npm_v}) ready at {node_path} and {npm_path}")
            return True
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False
    else:
        logger.error("❌ Node.js/npm still not found after setup attempts.")
        return False

def cleanup():
    logger.warning("Shutdown. Cleaning up processes...")
    script_keys_to_stop = list(bot_scripts.keys())
    if not script_keys_to_stop:
        logger.info("No scripts running. Exiting.")
        return
    logger.info(f"Stopping {len(script_keys_to_stop)} scripts...")
    for key in script_keys_to_stop:
        if key in bot_scripts:
            logger.info(f"Stopping: {key}")
            kill_process_tree(bot_scripts[key])
        else:
            logger.info(f"Script {key} already removed.")
    logger.warning("Cleanup finished.")
atexit.register(cleanup)

if __name__ == '__main__':
    ensure_node_installed()
    logger.info("="*50 + "\n🤖 DIV Hosting Bot Starting Up... (Paid Version)\n" + "="*50)
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