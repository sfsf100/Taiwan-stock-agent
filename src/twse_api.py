import requests
import time
import math
from datetime import datetime, time as dtime

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_DAY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

_MIS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://mis.twse.com.tw/",
}

_mis_cache: dict[str, dict] = {}
_mis_cache_ts: float = 0.0
MIS_TTL = 20  # seconds

_code_exchange: dict[str, str] = {}   # code -> "tse" | "otc"
_day_name_cache: dict[str, str] = {}  # code -> name (from STOCK_DAY_ALL)


def is_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 0) <= t <= dtime(13, 30)


def _safe_float(s) -> float | None:
    try:
        v = float(s)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_mis_item(item: dict) -> dict | None:
    price = _safe_float(item.get("z"))
    if price is None:
        return None
    prev = _safe_float(item.get("y")) or price
    return {
        "code": item.get("c", ""),
        "name": item.get("n", item.get("c", "")),
        "close": price,
        "prev_close": prev,
        "open": _safe_float(item.get("o")) or price,
        "high": _safe_float(item.get("h")) or price,
        "low": _safe_float(item.get("l")) or price,
        "volume": int(float(item.get("v", 0)) * 1000) if item.get("v", "-") != "-" else 0,
        "limit_up": _safe_float(item.get("u")) or 0.0,
        "limit_down": _safe_float(item.get("w")) or 0.0,
    }


def _query_mis(ex_ch_str: str) -> dict[str, dict]:
    """Single MIS API call; returns {code: info}."""
    r = requests.get(
        MIS_URL,
        params={"ex_ch": ex_ch_str, "json": "1", "delay": "0"},
        headers=_MIS_HEADERS,
        timeout=8,
    )
    r.raise_for_status()
    result = {}
    for item in r.json().get("msgArray", []):
        info = _parse_mis_item(item)
        if info:
            result[info["code"]] = info
            _code_exchange[info["code"]] = item.get("ex", "tse")
    return result


def fetch_watchlist_prices(codes_exchanges: list[tuple[str, str]]) -> dict[str, dict]:
    """
    Batch-fetch real-time prices for the watchlist.
    codes_exchanges: list of (code, exchange).
    Caches for MIS_TTL seconds.
    """
    global _mis_cache, _mis_cache_ts

    now = time.time()
    if now - _mis_cache_ts < MIS_TTL and _mis_cache:
        return _mis_cache

    if not codes_exchanges:
        return {}

    ex_ch = "|".join(f"{ex}_{code}.tw" for code, ex in codes_exchanges)
    try:
        result = _query_mis(ex_ch)
        _mis_cache = result
        _mis_cache_ts = now
        return result
    except Exception:
        return _mis_cache


def get_stock_info(code: str, exchange: str | None = None) -> dict | None:
    """Get real-time info for a single stock. Falls back to yfinance if MIS unavailable."""
    # Use cached batch result if fresh
    now = time.time()
    if code in _mis_cache and now - _mis_cache_ts < MIS_TTL:
        return _mis_cache[code]

    # Determine exchange
    ex = exchange or _code_exchange.get(code)
    exchanges_to_try = [ex] if ex else ["tse", "otc"]

    for ex_try in exchanges_to_try:
        try:
            result = _query_mis(f"{ex_try}_{code}.tw")
            if code in result:
                _mis_cache[code] = result[code]
                _mis_cache_ts = now
                return result[code]
        except Exception:
            pass

    # Fallback: yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{code}.TW")
        fi = ticker.fast_info
        price = fi.last_price
        if price:
            prev = getattr(fi, "previous_close", price)
            return {
                "code": code,
                "name": _day_name_cache.get(code, code),
                "close": price,
                "prev_close": prev or price,
                "open": getattr(fi, "open", price) or price,
                "high": getattr(fi, "day_high", price) or price,
                "low": getattr(fi, "day_low", price) or price,
                "volume": int(getattr(fi, "three_month_average_volume", 0) or 0),
                "limit_up": math.floor(prev * 1.1 * 100) / 100 if prev else 0,
                "limit_down": math.ceil(prev * 0.9 * 100) / 100 if prev else 0,
            }
    except Exception:
        pass
    return None


def validate_stock(code: str) -> tuple[str | None, str]:
    """
    Returns (name, exchange) if valid, (None, '') if not found.
    Also updates _code_exchange and _day_name_cache.
    """
    # Try MIS (TSE then OTC) — fastest
    for ex in ("tse", "otc"):
        try:
            result = _query_mis(f"{ex}_{code}.tw")
            if code in result:
                name = result[code]["name"]
                _day_name_cache[code] = name
                return name, ex
        except Exception:
            pass

    # Fallback: STOCK_DAY_ALL (covers cases where MIS is down)
    try:
        r = requests.get(TWSE_DAY_URL, timeout=10)
        r.raise_for_status()
        for item in r.json():
            if item.get("Code") == code:
                name = item.get("Name", code)
                _day_name_cache[code] = name
                _code_exchange[code] = "tse"
                return name, "tse"
    except Exception:
        pass

    return None, ""


def get_realtime_price(code: str) -> float | None:
    info = get_stock_info(code)
    return info["close"] if info else None


def calc_limit_prices(prev_close: float) -> tuple[float, float]:
    """Fallback calculation when MIS limit_up/limit_down not available."""
    if prev_close <= 0:
        return 0.0, 0.0
    return math.floor(prev_close * 1.1 * 100) / 100, math.ceil(prev_close * 0.9 * 100) / 100
