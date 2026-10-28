"""台北時區的交易時間判斷。

所有交易時段相關判斷都必須使用 Asia/Taipei 時區，
避免 bot 部署在 GitHub Actions（UTC）或任何非台北時區的機器上時，
在非交易時段誤發警報／報告。
"""
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")

# 台股交易時段（一般交易，不含盤後）
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(13, 30)


def now_taipei() -> datetime:
    """取得台北時區的現在時間。"""
    return datetime.now(TZ)


def is_weekday(now: datetime | None = None) -> bool:
    n = now or now_taipei()
    return n.weekday() < 5


def is_trading_time(now: datetime | None = None) -> bool:
    """是否在台股交易時段（週一～五 09:00–13:30 台北時間）。

    傳入其他時區的 aware datetime 會先轉換成台北時間再判斷。
    """
    n = now or now_taipei()
    if n.tzinfo is not None:
        n = n.astimezone(TZ)
    if n.weekday() >= 5:
        return False
    t = n.time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_silent_period(now: datetime | None = None) -> bool:
    """靜音時段（非交易時段）：不發任何價格警報。"""
    return not is_trading_time(now)
