import sqlite3
import os
from contextlib import closing

from .market_time import now_taipei

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "stocks.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _run(sql: str, params: tuple = (), *, commit: bool = True):
    """執行單一 SQL 並確保連線關閉（with sqlite3 不會 close，會造成檔案鎖與連線洩漏）。"""
    with closing(get_conn()) as conn:
        cur = conn.execute(sql, params)
        if commit:
            conn.commit()
        return cur.fetchall()


def init_db():
    with closing(get_conn()) as conn:
        with conn:
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
                CREATE TABLE IF NOT EXISTS holdings (
                    stock_code TEXT PRIMARY KEY,
                    stock_name TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    cost_price REAL NOT NULL,
                    added_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alert_history
                    ON alert_history (stock_code, alert_type, triggered_date);
            """)
        # Migrate: add exchange column to existing DBs
        try:
            with conn:
                conn.execute(
                    "ALTER TABLE watchlist ADD COLUMN exchange TEXT NOT NULL DEFAULT 'tse'"
                )
        except sqlite3.OperationalError:
            pass


# --- Watchlist ---

def add_stock(code: str, name: str, exchange: str = "tse"):
    _run(
        "INSERT OR IGNORE INTO watchlist (stock_code, stock_name, exchange, added_at) VALUES (?, ?, ?, date('now'))",
        (code, name, exchange)
    )


def remove_stock(code: str):
    _run("DELETE FROM watchlist WHERE stock_code = ?", (code,))


def get_watchlist() -> list[dict]:
    rows = _run("SELECT * FROM watchlist ORDER BY added_at")
    return [dict(r) for r in rows]


def is_watching(code: str) -> bool:
    return len(_run("SELECT 1 FROM watchlist WHERE stock_code = ?", (code,))) > 0


# --- Target prices (upside) ---

def add_target(code: str, price: float):
    _run(
        "INSERT INTO targets (stock_code, target_price, created_at) VALUES (?, ?, date('now'))",
        (code, price)
    )


def remove_target(code: str, price: float):
    _run("DELETE FROM targets WHERE stock_code = ? AND target_price = ?", (code, price))


def get_targets() -> list[dict]:
    return [dict(r) for r in _run("SELECT * FROM targets")]


# --- Stop-loss targets (downside) ---

def add_stop_target(code: str, price: float):
    _run(
        "INSERT INTO stop_targets (stock_code, stop_price, created_at) VALUES (?, ?, date('now'))",
        (code, price)
    )


def remove_stop_target(code: str, price: float):
    _run("DELETE FROM stop_targets WHERE stock_code = ? AND stop_price = ?", (code, price))


def get_stop_targets() -> list[dict]:
    return [dict(r) for r in _run("SELECT * FROM stop_targets")]


# --- Holdings ---

def add_holding(code: str, name: str, shares: int, cost_price: float):
    _run(
        "INSERT OR REPLACE INTO holdings (stock_code, stock_name, shares, cost_price, added_at) VALUES (?, ?, ?, ?, date('now'))",
        (code, name, shares, cost_price)
    )


def remove_holding(code: str):
    _run("DELETE FROM holdings WHERE stock_code = ?", (code,))


def get_holding(code: str) -> dict | None:
    rows = _run("SELECT * FROM holdings WHERE stock_code = ?", (code,))
    return dict(rows[0]) if rows else None


def get_holdings() -> list[dict]:
    return [dict(r) for r in _run("SELECT * FROM holdings ORDER BY added_at")]


# --- Alert History ---

def _today() -> str:
    """以台北時區取得今天日期（警報去重基準日）。"""
    return now_taipei().date().isoformat()


def has_alerted_today(code: str, alert_type: str) -> bool:
    rows = _run(
        "SELECT 1 FROM alert_history WHERE stock_code = ? AND alert_type = ? AND triggered_date = ?",
        (code, alert_type, _today())
    )
    return len(rows) > 0


def record_alert(code: str, alert_type: str):
    _run(
        "INSERT INTO alert_history (stock_code, alert_type, triggered_date) VALUES (?, ?, ?)",
        (code, alert_type, _today())
    )


def clear_today_alerts():
    """刪除非今日的警報紀錄（保留今日，避免重啟後重複通知）。"""
    _run("DELETE FROM alert_history WHERE triggered_date != ?", (_today(),))
