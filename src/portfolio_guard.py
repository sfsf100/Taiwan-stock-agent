"""持倉防線：把警報跟使用者實際持倉（/hold 記錄的成本）綁定。

解決「買了卻一路跌」的情境：
1. 未實現虧損警報 —— 跌破成本的設定百分比（預設 -8%）就開口，不再依賴手動 /stoploss
2. 移動停損 —— 持倉紀錄以來的高點回撤 N%（預設 10%）就提醒鎖利／減碼，
   對付「不破固定停損價、但每天陰跌 2%」的走法
3. 籌碼組合訊號 ——（由 main.send_chip_report 組合）持倉虧損中且外資續賣超

門檻可在 /hold 時用 loss_pct / trail_pct 逐檔調整；未指定時用模組預設值。
"""
import logging

import pandas as pd

from .indicators import fetch_history
from . import database as db

log = logging.getLogger("stock-bot")

# 預設門檻（百分比）
DEFAULT_LOSS_PCT = -8.0        # 未實現虧損 ≥ 8% 警告
DEFAULT_TRAILING_PCT = 10.0    # 從持倉高點回撤 ≥ 10% 提醒鎖利
_PROFIT_TO_GUARD = 3.0         # 高點至少要高過成本 3%，才有「獲利保護」意義


def _threshold(holding: dict, key: str, default: float) -> float:
    v = holding.get(key)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _high_since_added(code: str, added_at: str) -> float | None:
    """持倉紀錄日期以來的最高價（用 yfinance 日 K；紀錄早於K線範圍則用整段）。"""
    df = fetch_history(code, period="6mo")
    if df.empty or "High" not in df.columns:
        return None
    try:
        start = pd.Timestamp(added_at, tz="Asia/Taipei")
        recent = df[df.index >= start.tz_convert(df.index.tz)] if df.index.tz is not None else df
        high = float(recent["High"].max())
        return high if high > 0 else None
    except Exception as e:
        log.debug("_high_since_added 失敗 %s：%s", code, e)
        return None


def check_position_guard(holding: dict, info: dict) -> list[dict]:
    """單一持倉的防線檢查（由 30 秒輪詢呼叫，去重靠 alert_history）。

    holding 需含 stock_code、stock_name（可為 None）、shares、cost_price、added_at，
    另可帶 loss_guard_pct（正數，代表虧損幅度）／trailing_guard_pct。
    """
    code = holding["stock_code"]
    price = info.get("close") or 0
    cost = holding.get("cost_price") or 0
    if price <= 0 or cost <= 0:
        return []

    name = holding.get("stock_name") or code
    alerts: list[dict] = []
    unrealized_pct = (price - cost) / cost * 100

    # ── 1. 未實現虧損警報 ──
    # /hold 的 loss_pct 以正數儲存（代表虧損幅度），此處轉為負門檻
    loss_raw = holding.get("loss_guard_pct")
    try:
        loss_thresh = -abs(float(loss_raw)) if loss_raw is not None else DEFAULT_LOSS_PCT
    except (TypeError, ValueError):
        loss_thresh = DEFAULT_LOSS_PCT
    if unrealized_pct <= loss_thresh and not db.has_alerted_today(code, "position_loss"):
        db.record_alert(code, "position_loss")
        loss_amount = abs(price - cost) * (holding.get("shares") or 0)
        alerts.append({
            "type": "position_loss",
            "message": (
                f"@everyone 🩸 **【持倉警告】{name} ({code})**\n"
                f"現價 **{price:.2f}** 已低於成本 {cost:.2f} 達 **{abs(unrealized_pct):.1f}%**"
                f"（帳面損失約 {loss_amount:,.0f} 元）。\n"
                f"跌破成本防線，請檢視停損紀律或確認加攤理由。"
            ),
        })

    # ── 2. 移動停損（鎖利）──
    trail_thresh = _threshold(holding, "trailing_guard_pct", DEFAULT_TRAILING_PCT)
    added_at = holding.get("added_at")
    if added_at:
        high = _high_since_added(code, added_at)
        if high and high >= cost * (1 + _PROFIT_TO_GUARD / 100):
            drop_pct = (price - high) / high * 100
            if drop_pct <= -trail_thresh and not db.has_alerted_today(code, "trailing_protect"):
                db.record_alert(code, "trailing_protect")
                alerts.append({
                    "type": "trailing_protect",
                    "message": (
                        f"@everyone 🔒 **【移動停損提醒】{name} ({code})**\n"
                        f"持倉期間高點 {high:.2f}，現價 **{price:.2f}** 已回撤 **{abs(drop_pct):.1f}%**。\n"
                        f"（未實現損益 {unrealized_pct:+.1f}%）獲利回吐中，考慮減碼鎖住部分獲利。"
                    ),
                })

    return alerts


def combo_chip_message(holding: dict, info: dict, foreign_net: int | None) -> str | None:
    """持倉 × 籌碼組合訊號：持倉虧損中且外資今日續賣超（收盤籌碼速報用）。"""
    price = info.get("close") or 0
    cost = holding.get("cost_price") or 0
    if price <= 0 or cost <= 0 or foreign_net is None:
        return None
    unrealized_pct = (price - cost) / cost * 100
    if unrealized_pct >= 0 or foreign_net >= 0:
        return None
    code = holding["stock_code"]
    name = holding.get("stock_name") or code
    return (
        f"@everyone 🩸📉 **【持倉 × 籌碼雙重警告】{name} ({code})**\n"
        f"持倉未實現虧損 **{abs(unrealized_pct):.1f}%**（成本 {cost:.2f}／現價 {price:.2f}），"
        f"且外資今日續賣超 **{abs(foreign_net):,}** 張，籌碼面未止賣。\n"
        f"慎重考慮降低風險敞口，或確認這是要分批承接的理由。"
    )
