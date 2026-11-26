"""Portal-owned database: who may sign in, who may see what, server-side sessions, audit trail, refresh jobs. (SQLite in the mini version; PostgreSQL in the full build.)"""
import sqlite3, datetime as dt, json, secrets, threading
from config import DB_PATH
_lock = threading.Lock()
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA foreign_keys=ON"); return c
def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE, oid TEXT UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN('admin','viewer')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT, dashboard_uuid TEXT NOT NULL, dataset_id INTEGER NOT NULL, live INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS assignments(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE, branch_scope TEXT, created_at TEXT NOT NULL, PRIMARY KEY(user_id, report_id));
CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL, id_token TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, outcome TEXT NOT NULL, ip TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS refresh_jobs(id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, source_name TEXT, source_type TEXT, status TEXT NOT NULL, rows_read INTEGER, rows_published INTEGER, message TEXT, rejected_json TEXT, triggered_by TEXT);
"""
def init():
    with _lock, conn() as c: c.executescript(SCHEMA)
def audit(actor, action, target="", outcome="ok", ip="", detail=""):
    """Append-only audit event. NEVER pass secrets/tokens in detail."""
    with _lock, conn() as c: c.execute("INSERT INTO events(ts,actor,action,target,outcome,ip,detail) VALUES(?,?,?,?,?,?,?)", (now(), actor, action, target, outcome, ip, str(detail)[:500]))
def q(sql, *a):
    with conn() as c: return [dict(r) for r in c.execute(sql, a).fetchall()]
def one(sql, *a):
    r = q(sql, *a); return r[0] if r else None
def run(sql, *a):
    with _lock, conn() as c: cur = c.execute(sql, a); return cur.lastrowid
def new_sid(): return secrets.token_urlsafe(32)
