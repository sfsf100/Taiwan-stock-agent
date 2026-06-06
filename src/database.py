import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "stocks.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watchlist (
                stock_code TEXT PRIMARY KEY,
                stock_name TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'tse',
                added_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                target_price REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stop_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                stop_price REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                triggered_date TEXT NOT NULL
            );
        """)
    # Migrate: add exchange column to existing DBs
    with get_conn() as conn:
        try:
            conn.execute("ALTER TABLE watchlist ADD COLUMN exchange TEXT NOT NULL DEFAULT 'tse'")
        except Exception:
            pass


# --- Watchlist ---

def add_stock(code: str, name: str, exchange: str = "tse"):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (stock_code, stock_name, exchange, added_at) VALUES (?, ?, ?, date('now'))",
            (code, name, exchange)
        )


def remove_stock(code: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE stock_code = ?", (code,))


def get_watchlist() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at").fetchall()
        return [dict(r) for r in rows]


def is_watching(code: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM watchlist WHERE stock_code = ?", (code,)).fetchone()
        return row is not None


# --- Target prices (upside) ---

def add_target(code: str, price: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO targets (stock_code, target_price, created_at) VALUES (?, ?, date('now'))",
            (code, price)
        )


def remove_target(code: str, price: float):
    with get_conn() as conn:
        conn.execute("DELETE FROM targets WHERE stock_code = ? AND target_price = ?", (code, price))


def get_targets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM targets").fetchall()
        return [dict(r) for r in rows]


# --- Stop-loss targets (downside) ---

def add_stop_target(code: str, price: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO stop_targets (stock_code, stop_price, created_at) VALUES (?, ?, date('now'))",
            (code, price)
        )


def remove_stop_target(code: str, price: float):
    with get_conn() as conn:
        conn.execute("DELETE FROM stop_targets WHERE stock_code = ? AND stop_price = ?", (code, price))


def get_stop_targets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM stop_targets").fetchall()
        return [dict(r) for r in rows]


# --- Alert History ---

def has_alerted_today(code: str, alert_type: str) -> bool:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM alert_history WHERE stock_code = ? AND alert_type = ? AND triggered_date = ?",
            (code, alert_type, today)
        ).fetchone()
        return row is not None


def record_alert(code: str, alert_type: str):
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alert_history (stock_code, alert_type, triggered_date) VALUES (?, ?, ?)",
            (code, alert_type, today)
        )


def clear_today_alerts():
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM alert_history WHERE triggered_date != ?", (today,))
