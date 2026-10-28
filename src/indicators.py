import time

import yfinance as yf
import pandas as pd

# code -> (DataFrame, 下載時間戳)
_history_cache: dict[str, tuple[pd.DataFrame, float]] = {}

# K 線資料快取存活時間（秒）。
# 盤中 30 秒輪詢會不斷呼叫 get_rsi / get_ma5 / get_volume_ratio，
# 若不設 TTL，每檔股票每 30 秒就會對 yfinance 發一次 HTTP 請求，
# 極易被限流（HTTP 429）。K 線資料以日為單位，5 分鐘的延遲完全足夠。
HISTORY_TTL = 300


def fetch_history(code: str, period: str = "3mo", ttl: float = HISTORY_TTL) -> pd.DataFrame:
    """取得日 K 線資料，ttl 秒內重複呼叫直接回傳快取，不發出網路請求。"""
    now = time.time()
    cached = _history_cache.get(code)
    if cached is not None and now - cached[1] < ttl:
        return cached[0]

    try:
        df = yf.Ticker(f"{code}.TW").history(period=period)
    except Exception:
        # 下載失敗時退回過期快取（總比空資料好）
        return cached[0] if cached is not None else pd.DataFrame()

    if df.empty:
        return cached[0] if cached is not None else df

    _history_cache[code] = (df, now)
    return df


def clear_cache():
    """清空 K 線快取（供測試使用）。"""
    _history_cache.clear()


def get_rsi(code: str, period: int = 14) -> float | None:
    df = fetch_history(code)
    if df.empty or len(df) < period + 1:
        return None
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rsi = 100 - (100 / (1 + gain / loss))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


def get_ma5(code: str) -> float | None:
    df = fetch_history(code)
    if df.empty or len(df) < 5:
        return None
    val = df["Close"].rolling(5).mean().iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


def get_ma20(code: str) -> float | None:
    df = fetch_history(code)
    if df.empty or len(df) < 20:
        return None
    val = df["Close"].rolling(20).mean().iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


def get_volume_ratio(code: str) -> float | None:
    """Today's volume / 20-day average volume."""
    df = fetch_history(code)
    if df.empty or len(df) < 21:
        return None
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    today_vol = df["Volume"].iloc[-1]
    if avg_vol == 0:
        return None
    return round(float(today_vol / avg_vol), 2)


def get_recent_high_low(code: str, days: int = 20) -> tuple[float, float] | tuple[None, None]:
    df = fetch_history(code)
    if df.empty or len(df) < days:
        return None, None
    recent = df["Close"].iloc[-days:]
    return round(float(recent.max()), 2), round(float(recent.min()), 2)


def preload(codes: list[str]):
    for code in codes:
        fetch_history(code)
