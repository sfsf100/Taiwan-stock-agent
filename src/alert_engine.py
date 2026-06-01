from datetime import datetime, time as dtime
from . import database as db
from .twse_api import calc_limit_prices, get_realtime_price
from .indicators import get_rsi, get_ma5, get_volume_ratio


def is_silent_period() -> bool:
    t = datetime.now().time()
    return t >= dtime(13, 30) or t < dtime(9, 0)


def check_alerts(code: str, name: str, current_price: float, prev_close: float) -> list[dict]:
    if is_silent_period():
        return []

    alerts = []
    limit_up, limit_down = calc_limit_prices(prev_close)

    # 漲停警告
    if limit_up > 0 and current_price >= limit_up:
        if not db.has_alerted_today(code, "limit_up"):
            db.record_alert(code, "limit_up")
            alerts.append({
                "type": "limit_up",
                "message": f"@everyone ⚠️ **【漲停警告】{name} ({code})**\n現價 **{current_price:.2f}** 已達漲停，請勿追價！",
            })

    # 跌停警告
    if limit_down > 0 and current_price <= limit_down:
        if not db.has_alerted_today(code, "limit_down"):
            db.record_alert(code, "limit_down")
            alerts.append({
                "type": "limit_down",
                "message": f"@everyone 🔴 **【跌停警告】{name} ({code})**\n現價 **{current_price:.2f}** 已達跌停，注意停損！",
            })

    # 目標價
    for target in db.get_targets():
        if target["stock_code"] == code and current_price >= target["target_price"]:
            alert_key = f"target_{target['target_price']}"
            if not db.has_alerted_today(code, alert_key):
                db.record_alert(code, alert_key)
                db.remove_target(code, target["target_price"])
                alerts.append({
                    "type": "target",
                    "message": f"@everyone 🎯 **{name} ({code})** 已達目標價 **{target['target_price']:.2f}**\n現價：{current_price:.2f}",
                })

    return alerts


def check_technical_alerts(code: str, name: str) -> list[dict]:
    if is_silent_period():
        return []

    alerts = []

    # RSI 超賣
    rsi = get_rsi(code)
    if rsi is not None and rsi < 30:
        if not db.has_alerted_today(code, "rsi_oversold"):
            db.record_alert(code, "rsi_oversold")
            alerts.append({
                "type": "rsi_oversold",
                "message": f"@everyone 📉 **{name} ({code})** RSI 超賣\nRSI(14) = **{rsi}**，可參考分批買進",
            })

    # 跌破 5MA
    ma5 = get_ma5(code)
    price = get_realtime_price(code)
    if ma5 and price and price < ma5:
        if not db.has_alerted_today(code, "below_ma5"):
            db.record_alert(code, "below_ma5")
            alerts.append({
                "type": "below_ma5",
                "message": f"@everyone 📊 **{name} ({code})** 跌破 5MA\n現價 {price:.2f} < 5MA {ma5:.2f}，短線偏弱",
            })

    # 異常量能
    vol_ratio = get_volume_ratio(code)
    if vol_ratio and vol_ratio > 3:
        if not db.has_alerted_today(code, "high_volume"):
            db.record_alert(code, "high_volume")
            alerts.append({
                "type": "high_volume",
                "message": f"@everyone 📢 **{name} ({code})** 異常量能\n今日成交量為均量的 **{vol_ratio:.1f}** 倍，注意主力動向",
            })

    return alerts
