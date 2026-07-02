import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "omnigram.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS owner_account (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT, name TEXT,
            session_string TEXT NOT NULL,
            api_id INTEGER, api_hash TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sender_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL, name TEXT,
            session_string TEXT NOT NULL,
            api_id INTEGER, api_hash TEXT,
            status TEXT DEFAULT 'active',
            custom_message TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS owner_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id TEXT UNIQUE, username TEXT,
            title TEXT, subscribers INTEGER DEFAULT 0,
            last_synced TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS edit_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER, source_post_url TEXT,
            target_post_id TEXT, extra_text TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL, action TEXT NOT NULL,
            status TEXT DEFAULT 'running', detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE TABLE IF NOT EXISTS report_account (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT, name TEXT,
            session_string TEXT NOT NULL,
            api_id INTEGER, api_hash TEXT, log_channel TEXT
        );
    """)
    conn.commit()
    conn.close()


def get_owner():
    conn = get_conn()
    row = conn.execute("SELECT * FROM owner_account LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def set_owner(phone, name, session_string, api_id, api_hash):
    conn = get_conn()
    conn.execute("DELETE FROM owner_account")
    conn.execute("INSERT INTO owner_account (phone,name,session_string,api_id,api_hash) VALUES (?,?,?,?,?)",
                 (phone, name, session_string, api_id, api_hash))
    conn.commit()
    conn.close()


def get_owner_channels():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM owner_channels ORDER BY title").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_channel(tg_id, username, title, subscribers=0):
    conn = get_conn()
    conn.execute("""INSERT INTO owner_channels (tg_id,username,title,subscribers,last_synced)
        VALUES (?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(tg_id) DO UPDATE SET
        username=excluded.username, title=excluded.title,
        subscribers=excluded.subscribers, last_synced=CURRENT_TIMESTAMP""",
                 (str(tg_id), username, title, subscribers))
    conn.commit()
    conn.close()


def clear_channels():
    conn = get_conn()
    conn.execute("DELETE FROM owner_channels")
    conn.commit()
    conn.close()


def update_task_status_by_url(url, status):
    conn = get_conn()
    conn.execute("UPDATE edit_tasks SET status=? WHERE source_post_url=?", (status, url))
    conn.commit()
    conn.close()


def log_action(module, action, status="running", detail=""):
    conn = get_conn()
    conn.execute("INSERT INTO action_log (module,action,status,detail) VALUES (?,?,?,?)",
                 (module, action, status, detail))
    conn.commit()
    conn.close()


def get_recent_actions(limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sender_accounts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sender_accounts ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_sender_account(phone, name, session_string, api_id, api_hash):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO sender_accounts (phone,name,session_string,api_id,api_hash) VALUES (?,?,?,?,?)",
                 (phone, name, session_string, api_id, api_hash))
    conn.commit()
    conn.close()


def update_sender_status(acc_id, status):
    conn = get_conn()
    conn.execute("UPDATE sender_accounts SET status=? WHERE id=?", (status, acc_id))
    conn.commit()
    conn.close()


def update_sender_message(acc_id, message):
    conn = get_conn()
    conn.execute("UPDATE sender_accounts SET custom_message=? WHERE id=?", (message, acc_id))
    conn.commit()
    conn.close()


def delete_sender_account(acc_id):
    conn = get_conn()
    conn.execute("DELETE FROM sender_accounts WHERE id=?", (acc_id,))
    conn.commit()
    conn.close()


def clear_sender_messages():
    conn = get_conn()
    conn.execute("UPDATE sender_accounts SET custom_message=NULL")
    conn.commit()
    conn.close()


def get_chats():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM chat_pool ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_chats(usernames):
    conn = get_conn()
    for u in usernames:
        try:
            conn.execute("INSERT OR IGNORE INTO chat_pool (username) VALUES (?)", (u,))
        except Exception:
            pass
    conn.commit()
    conn.close()


def clear_chats():
    conn = get_conn()
    conn.execute("DELETE FROM chat_pool")
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


def get_report_account():
    conn = get_conn()
    row = conn.execute("SELECT * FROM report_account LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def set_report_account(phone, name, session_string, api_id, api_hash):
    conn = get_conn()
    conn.execute("DELETE FROM report_account")
    conn.execute("INSERT INTO report_account (phone,name,session_string,api_id,api_hash) VALUES (?,?,?,?,?)",
                 (phone, name, session_string, api_id, api_hash))
    conn.commit()
    conn.close()
