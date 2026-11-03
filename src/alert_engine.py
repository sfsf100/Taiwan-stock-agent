from . import database as db
from .market_time import is_silent_period, is_trading_time, now_taipei
from .indicators import get_rsi, get_ma5, get_volume_ratio, get_recent_high_low


def check_alerts(code: str, name: str, info: dict) -> list[dict]:
    """
    info must contain: close, prev_close, limit_up, limit_down.
    These now come directly from the MIS API.
    """
    if is_silent_period():
        return []

    alerts = []
    current_price = info["close"]
    limit_up = info.get("limit_up", 0)
    limit_down = info.get("limit_down", 0)

    # 漲停警告
    if limit_up > 0 and current_price >= limit_up:
        if not db.has_alerted_today(code, "limit_up"):
            db.record_alert(code, "limit_up")
            alerts.append({
                "type": "limit_up",
                "message": f"@everyone ⚠️ **【漲停警告】{name} ({code})**\n現價 **{current_price:.2f}** 已達漲停 {limit_up:.2f}，請勿追價！",
            })

    # 跌停警告
    if limit_down > 0 and current_price <= limit_down:
        if not db.has_alerted_today(code, "limit_down"):
            db.record_alert(code, "limit_down")
            alerts.append({
                "type": "limit_down",
                "message": f"@everyone 🔴 **【跌停警告】{name} ({code})**\n現價 **{current_price:.2f}** 已達跌停 {limit_down:.2f}，注意停損！",
            })

    # 目標價（向上）
    for target in db.get_targets():
        if target["stock_code"] == code and current_price >= target["target_price"]:
            alert_key = f"target_{target['target_price']}"
            if not db.has_alerted_today(code, alert_key):
                db.record_alert(code, alert_key)
                db.remove_target(code, target["target_price"])
                alerts.append({
                    "type": "target",
                    "message": (
                        f"@everyone 🎯 **{name} ({code})** 已達目標價 **{target['target_price']:.2f}**\n"
                        f"現價：{current_price:.2f}"
                    ),
                })

    # 停損價（向下）
    for stop in db.get_stop_targets():
        if stop["stock_code"] == code and current_price <= stop["stop_price"]:
            alert_key = f"stoploss_{stop['stop_price']}"
            if not db.has_alerted_today(code, alert_key):
                db.record_alert(code, alert_key)
                db.remove_stop_target(code, stop["stop_price"])
                alerts.append({
                    "type": "stoploss",
                    "message": (
                        f"@everyone 🛑 **【停損警告】{name} ({code})**\n"
                        f"現價 {current_price:.2f} 已跌破停損價 **{stop['stop_price']:.2f}**，建議執行停損！"
                    ),
                })

    return alerts


def check_technical_alerts(code: str, name: str, price: float | None = None) -> list[dict]:
    """
    檢查技術面警報（RSI 超賣 / 跌破 5MA / 爆量）。
    price: 由呼叫端傳入的即時價（MIS 批次查詢結果），
    避免此函式再自行發一次網路請求造成限流。
    """
    if is_silent_period():
        return []

    alerts = []

    rsi = get_rsi(code)
    if rsi is not None and rsi < 30:
        if not db.has_alerted_today(code, "rsi_oversold"):
            db.record_alert(code, "rsi_oversold")
            alerts.append({
                "type": "rsi_oversold",
                "message": f"@everyone 📉 **{name} ({code})** RSI 超賣\nRSI(14) = **{rsi}**，可參考分批買進",
            })

    ma5 = get_ma5(code)
    if ma5 and price and price < ma5:
        if not db.has_alerted_today(code, "below_ma5"):
            db.record_alert(code, "below_ma5")
            alerts.append({
                "type": "below_ma5",
                "message": f"@everyone 📊 **{name} ({code})** 跌破 5MA\n現價 {price:.2f} < 5MA {ma5:.2f}，短線偏弱",
            })

    vol_ratio = get_volume_ratio(code)
    if vol_ratio and vol_ratio > 3:
        if not db.has_alerted_today(code, "high_volume"):
            db.record_alert(code, "high_volume")
            alerts.append({
                "type": "high_volume",
                "message": f"@everyone 📢 **{name} ({code})** 異常量能\n今日成交量為均量的 **{vol_ratio:.1f}** 倍，注意主力動向",
            })

    return alerts


# 跌深門檻：自 20 日高點回撤超過此百分比發「跌深警示」
DEEP_DRAWDOWN_PCT = -15.0
# 量縮止跌門檻：回撤超過 -10% 且成交量縮至均量 70% 以下
VOLUME_SHRINK_RATIO = 0.7
# 量比必須在收盤前（12:30 後）才可信，早盤成交量必然偏低
VOLUME_CHECK_TIME = (12, 30)


def check_buy_timing_alerts(code: str, name: str, price: float) -> list[dict]:
    """買盤時機警報：跌深警示＋量縮止跌初步訊號。

    跌深 ≠ 止跌：訊息中明確提醒待法人止賣／量價確認再考慮承接。
    """
    if is_silent_period():
        return []

    alerts = []
    high20, _low20 = get_recent_high_low(code)
    if not high20 or high20 <= 0 or price <= 0:
        return alerts
    drawdown = (price - high20) / high20 * 100

    if drawdown <= DEEP_DRAWDOWN_PCT and not db.has_alerted_today(code, "deep_drawdown"):
        db.record_alert(code, "deep_drawdown")
        alerts.append({
            "type": "deep_drawdown",
            "message": (
                f"@everyone 💥 **【跌深警示】{name} ({code})**\n"
                f"現價 {price:.2f}，自 20 日高點 {high20:.2f} 已回撤 **{abs(drawdown):.1f}%**。\n"
                f"跌深 ≠ 止跌，急跌行情中建議先觀察法人止賣與量價止穩訊號，勿急著接刀。"
            ),
        })

    # 收盤前量比不可靠，12:30 之後才評估「量縮止跌」
    now = now_taipei()
    if drawdown <= -10 and now.hour * 60 + now.minute >= VOLUME_CHECK_TIME[0] * 60 + VOLUME_CHECK_TIME[1]:
        vol_ratio = get_volume_ratio(code)
        if vol_ratio is not None and 0 < vol_ratio < VOLUME_SHRINK_RATIO:
            if not db.has_alerted_today(code, "volume_shrink"):
                db.record_alert(code, "volume_shrink")
                alerts.append({
                    "type": "volume_shrink",
                    "message": (
                        f"💧 **{name} ({code})** 量縮止跌初步訊號\n"
                        f"股價已回撤 {abs(drawdown):.1f}%，今日成交量僅為 20 日均量的 {vol_ratio:.0%}，\n"
                        f"若後續不再破底，可留意分批布局時機（需再確認法人端止賣）。"
                    ),
                })

    return alerts
