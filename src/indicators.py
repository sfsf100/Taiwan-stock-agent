import yfinance as yf
import pandas as pd

_history_cache: dict[str, pd.DataFrame] = {}


def fetch_history(code: str, period: str = "3mo") -> pd.DataFrame:
    try:
        ticker = yf.Ticker(f"{code}.TW")
        df = ticker.history(period=period)
        if not df.empty:
            _history_cache[code] = df
        return df
    except Exception:
        return _history_cache.get(code, pd.DataFrame())


def get_rsi(code: str, period: int = 14) -> float | None:
    df = fetch_history(code)
    if df.empty or len(df) < period + 1:
        return None
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


def get_ma5(code: str) -> float | None:
    df = fetch_history(code)
    if df.empty or len(df) < 5:
        return None
    val = df["Close"].rolling(5).mean().iloc[-1]
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


def preload(codes: list[str]):
    for code in codes:
        fetch_history(code)
