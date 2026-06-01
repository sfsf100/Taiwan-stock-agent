import requests
import math
from datetime import datetime, time
import yfinance as yf

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_cache: dict = {}


def is_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return time(9, 0) <= t <= time(13, 30)


def fetch_all_twse() -> dict:
    try:
        r = requests.get(TWSE_URL, timeout=10)
        r.raise_for_status()
        data = r.json()
        result = {}
        for item in data:
            code = item.get("Code", "")
            result[code] = {
                "code": code,
                "name": item.get("Name", ""),
                "close": float(item.get("ClosingPrice", 0) or 0),
                "open": float(item.get("OpeningPrice", 0) or 0),
                "high": float(item.get("HighestPrice", 0) or 0),
                "low": float(item.get("LowestPrice", 0) or 0),
                "volume": int(item.get("TradeVolume", 0) or 0),
                "prev_close": float(item.get("LastBestBidPrice", 0) or 0),
            }
        _cache.update(result)
        return result
    except Exception:
        return _cache


def get_stock_info(code: str) -> dict | None:
    data = fetch_all_twse()
    if code in data:
        return data[code]
    try:
        ticker = yf.Ticker(f"{code}.TW")
        info = ticker.fast_info
        price = info.last_price
        if price:
            return {
                "code": code,
                "name": code,
                "close": price,
                "open": getattr(info, "open", price),
                "high": getattr(info, "day_high", price),
                "low": getattr(info, "day_low", price),
                "volume": int(getattr(info, "three_month_average_volume", 0) or 0),
                "prev_close": getattr(info, "previous_close", price),
            }
    except Exception:
        pass
    return None


def validate_stock(code: str) -> str | None:
    """Returns stock name if valid, None if not found."""
    data = fetch_all_twse()
    if code in data:
        return data[code]["name"]
    try:
        ticker = yf.Ticker(f"{code}.TW")
        name = ticker.info.get("shortName") or ticker.info.get("longName")
        return name if name else None
    except Exception:
        return None


def calc_limit_prices(prev_close: float) -> tuple[float, float]:
    """Returns (limit_up, limit_down) per TWSE rules."""
    if prev_close <= 0:
        return 0, 0
    limit_up = math.floor(prev_close * 1.1 * 100) / 100
    limit_down = math.ceil(prev_close * 0.9 * 100) / 100
    return limit_up, limit_down


def get_realtime_price(code: str) -> float | None:
    try:
        ticker = yf.Ticker(f"{code}.TW")
        return ticker.fast_info.last_price
    except Exception:
        return None
