"""籌碼面資料：三大法人買賣超＋融資融券餘額。

回答「今天跌成這樣，到底是誰在賣、賣了多少」的問題。

資料源（免費、免金鑰）：
- 上市三大法人：TWSE RWD fund/T86（可指定交易日期）
- 上櫃三大法人：TPEx OpenAPI tpex_3insti_daily_trading
- 上市融資融券：TWSE OpenAPI exchangeReport/MI_MARGN
- 上櫃融資融券：TPEx OpenAPI tpex_mainboard_margin_balance

所有股數單位一律正規化為「張」（1 張 = 1,000 股）。
法人／融資資料為日資料，盤後才會更新，因此整份快取 1 小時即可。
"""
import os
import time
import logging

import requests

log = logging.getLogger("stock-bot")

T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_3INSTI_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
TSE_MARGIN_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
OTC_MARGIN_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# 日資料 TTL（秒）：收盤後資料每天只更新一次，1 小時刷新足夠
CHIP_TTL = 3600

# 外資「大額賣超」門檻（張），超過時發出 @everyone 警告
FOREIGN_BIG_SELL_LOTS = int(os.getenv("CHIP_FOREIGN_BIG_SELL_LOTS", "1000"))

_insti_cache: dict[str, tuple[float, dict[str, dict]]] = {}
_margin_cache: dict[str, tuple[float, dict[str, dict]]] = {}


# ── 小工具 ────────────────────────────────────────────────────

def _to_int(v) -> int | None:
    """把 '23,482,462' / '-' / '' / 空白 轉成 int；無效值回 None。"""
    if v is None:
        return None
    s = str(v).replace(",", "").replace("\u3000", "").strip()
    if not s or s in ("-", "--"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _shares_to_lots(v) -> int:
    """股數 → 張（1 張 = 1000 股）。"""
    n = _to_int(v)
    if n is None:
        return 0
    return round(n / 1000)


def _norm_key(k: str) -> str:
    """欄位名正規化：去掉所有空白、轉小寫（TPEx 欄位名含雜亂空格）。"""
    return "".join(str(k).split()).lower()


def _roc_to_ad(s: str) -> str:
    """日期正規化為 'YYYY-MM-DD'：
    民國日期 '1151103' → '2026-11-03'； 西元 'YYYYMMDD' → 'YYYY-MM-DD'。
    """
    s = str(s).strip()
    if len(s) not in (7, 8) or not s.isdigit():
        return s
    if len(s) == 7:  # 民國：1151103
        year, md = str(int(s[:3]) + 1911), s[3:]
    else:            # 西元 YYYYMMDD
        year, md = s[:4], s[4:]
    return f"{year}-{md[:2]}-{md[2:]}"


def _taipei_today() -> str:
    from .market_time import now_taipei
    return now_taipei().strftime("%Y%m%d")


# ── 三大法人買賣超 ───────────────────────────────────────────

def _parse_t86(payload: dict) -> dict[str, dict]:
    """解析 TWSE T86（三大法人買賣超日報，YYYYMMDDdate 欄位值為股數）。

    欄位名以網頁欄位對照表動態比對，避免官方調整欄位順序時程式壞掉。
    """
    result: dict[str, dict] = {}
    fields = payload.get("fields") or []
    rows = payload.get("data") or []

    def idx_of(*names: str) -> int | None:
        for name in names:
            for i, f in enumerate(fields):
                if str(f).strip() == name:
                    return i
        return None

    i_code = idx_of("證券代號")
    i_name = idx_of("證券名稱")
    i_foreign = idx_of("外陸資買賣超股數(不含外資自營商)")
    i_trust = idx_of("投信買賣超股數")
    i_dealer = idx_of("自營商買賣超股數", "自營商買賣超股數(合計)")
    i_total = idx_of("三大法人買賣超股數")
    if i_code is None:
        return result

    data_date = _roc_to_ad(payload.get("date", ""))
    for row in rows:
        if not row or i_code >= len(row):
            continue
        code = str(row[i_code]).strip()
        if not code or "=" in code:
            continue
        result[code] = {
            "name": str(row[i_name]).strip() if i_name is not None and i_name < len(row) else code,
            "date": data_date,
            "foreign_net": _shares_to_lots(row[i_foreign]) if i_foreign is not None else None,
            "trust_net": _shares_to_lots(row[i_trust]) if i_trust is not None else None,
            "dealer_net": _shares_to_lots(row[i_dealer]) if i_dealer is not None else None,
            "total_net": _shares_to_lots(row[i_total]) if i_total is not None else None,
        }
    return result


def _fetch_t86_institutional() -> dict[str, dict]:
    """上市三大法人。selectType=ALL 才會回傳全市場個股（預設只有 7 筆彙總列）。"""
    try:
        r = requests.get(
            T86_URL,
            params={"response": "json", "date": _taipei_today(), "selectType": "ALL"},
            headers=_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload.get("data"):
            parsed = _parse_t86(payload)
            if parsed:
                return parsed
    except Exception as e:
        log.warning("T86 抓取失敗：%s", e)

    # 今天沒資料（假日／尚未發布）：改抓最近一個交易日
    try:
        r = requests.get(
            T86_URL,
            params={"response": "json", "selectType": "ALL"},
            headers=_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload.get("data"):
            return _parse_t86(payload)
    except Exception as e:
        log.warning("T86 fallback 抓取失敗：%s", e)
    return {}


def _parse_tpex_insti(items: list[dict]) -> dict[str, dict]:
    """解析 TPEx 三大法人買賣明細（欄位名有雜訊空格，用正規化比對）。"""
    if not items:
        return {}

    # 只保留最新日期（response 可能混含多日）
    dates = {_norm_key(it.get("Date", "")) for it in items}
    latest = sorted(dates)[-1]
    data_date = _roc_to_ad(latest)

    result: dict[str, dict] = {}
    for it in items:
        if _norm_key(it.get("Date", "")) != latest:
            continue
        code = str(it.get("SecuritiesCompanyCode", "")).strip()
        if not code:
            continue
        # TPEx 欄位名亂含空格，正規化後比對才穩
        n = {_norm_key(k): v for k, v in it.items()}

        def getn(*names: str):
            for name in names:
                key = _norm_key(name)
                if key in n:
                    return n[key]
            return None

        foreign = _shares_to_lots(getn("ForeignInvestorsIncludeMainlandAreaInvestors-Difference"))
        trust = _shares_to_lots(getn("SecuritiesInvestmentTrustCompanies-Difference"))
        dealer = _shares_to_lots(getn("Dealers-Difference"))
        total_raw = _shares_to_lots(getn("TotalDifference"))
        result[code] = {
            "name": str(it.get("CompanyName", "")).strip() or code,
            "date": data_date,
            "foreign_net": foreign,
            "trust_net": trust,
            "dealer_net": dealer,
            "total_net": total_raw if total_raw else ((foreign or 0) + (trust or 0) + (dealer or 0)),
        }
    return result


def _fetch_tpex_institutional() -> dict[str, dict]:
    """上櫃三大法人。連線偶發 IncompleteRead（大表傳輸中斷），重試一次。"""
    for attempt in range(2):
        try:
            r = requests.get(TPEX_3INSTI_URL, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            return _parse_tpex_insti(r.json())
        except Exception as e:
            if attempt == 0:
                log.warning("TPEx 三大法人抓取失敗（將重試）：%s", e)
                continue
            log.warning("TPEx 三大法人抓取失敗：%s", e)
    return {}


def fetch_institutional() -> dict[str, dict]:
    """三大法人買賣超（上市＋上櫃合併），單位一律為張。

    回傳 {code: {"name", "date", "foreign_net", "trust_net", "dealer_net", "total_net"}}。
    市場整份快取 CHIP_TTL 秒，所有股票共用一次抓取。
    """
    now = time.time()
    if "all" in _insti_cache and now - _insti_cache["all"][0] < CHIP_TTL:
        return _insti_cache["all"][1]

    merged: dict[str, dict] = {}
    tse = _fetch_t86_institutional()
    otc = _fetch_tpex_institutional()
    merged.update(tse)
    for code, info in otc.items():
        merged.setdefault(code, info)

    if merged:
        _insti_cache["all"] = (now, merged)
        log.info("法人資料載入 %d 檔（上市 %d、上櫃 %d）", len(merged), len(tse), len(otc))
    return merged


# ── 融資融券 ─────────────────────────────────────────────────

def _fetch_margin() -> dict[str, dict]:
    """融資融券餘額增減（上市 MI_MARGN + 上櫃），單位：張。

    回傳 {code: {"date", "margin_balance", "margin_change",
                  "short_balance", "short_change"}}，缺值的欄位為 None。
    """
    now = time.time()
    if "all" in _margin_cache and now - _margin_cache["all"][0] < CHIP_TTL:
        return _margin_cache["all"][1]

    merged: dict[str, dict] = {}

    # 上市：TWSE OpenAPI MI_MARGN（單位：交易單位＝張）
    try:
        r = requests.get(TSE_MARGIN_URL, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        for it in r.json():
            code = str(it.get("股票代號", "")).strip()
            if not code:
                continue
            bal = _to_int(it.get("融資今日餘額"))
            prev = _to_int(it.get("融資前日餘額"))
            s_bal = _to_int(it.get("融券今日餘額"))
            s_prev = _to_int(it.get("融券前日餘額"))
            merged[code] = {
                "date": None,
                "margin_balance": bal,
                "margin_change": (bal - prev) if (bal is not None and prev is not None) else None,
                "short_balance": s_bal,
                "short_change": (s_bal - s_prev) if (s_bal is not None and s_prev is not None) else None,
            }
    except Exception as e:
        log.warning("MI_MARGN 融資券抓取失敗：%s", e)

    # 上櫃：TPEx（單位：千股，1 千股 = 1 張，數值可直接當張用）
    try:
        r = requests.get(OTC_MARGIN_URL, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        items = r.json()
        dates = {str(it.get("Date", "")).strip() for it in items}
        latest = sorted(filter(None, dates))[-1] if dates else ""
        data_date = _roc_to_ad(latest)
        for it in items:
            if str(it.get("Date", "")).strip() != latest:
                continue
            code = str(it.get("SecuritiesCompanyCode", "")).strip()
            if not code:
                continue
            bal = _to_int(it.get("MarginPurchaseBalance"))
            prev = _to_int(it.get("MarginPurchaseBalancePreviousDay"))
            s_bal = _to_int(it.get("ShortSaleBalance"))
            s_prev = _to_int(it.get("ShortSaleBalancePreviousDay"))
            merged[code] = {
                "date": data_date,
                "margin_balance": bal,
                "margin_change": (bal - prev) if (bal is not None and prev is not None) else None,
                "short_balance": s_bal,
                "short_change": (s_bal - s_prev) if (s_bal is not None and s_prev is not None) else None,
            }
    except Exception as e:
        log.warning("TPEx 融資券抓取失敗：%s", e)

    if merged:
        _margin_cache["all"] = (now, merged)
    return merged


def get_chips(codes: list[str]) -> dict[str, dict]:
    """取得指定股票的籌碼總覽（法人＋融資），單位：張。

    回傳 {code: chip}，chip 內容如下（缺資料的項目為 None）：
    {name, date, foreign_net, trust_net, dealer_net, total_net,
     margin_balance, margin_change, short_balance, short_change}
    """
    insti = fetch_institutional()
    margin = _fetch_margin()
    result: dict[str, dict] = {}
    for code in codes:
        base = insti.get(code)
        if not base:
            continue
        chip = dict(base)
        # 只用非 None 的融資券欄位覆蓋（TSE margin 端點無日期，不可覆蓋法人端日期）
        chip.update({k: v for k, v in margin.get(code, {}).items() if v is not None})
        result[code] = chip
    return result


# ── 連續日數與警報判斷 ────────────────────────────────────────

def compute_streaks(history: list[dict]) -> dict:
    """由 chip_daily 歷史紀錄（新→舊排序）計算連續賣超／買超狀態。

    history 每列需含 foreign_net、trust_net。
    連續日數從今天往回數，碰到方向改變即停止累計。
    """
    streaks = {
        "foreign_sell_streak": 0,
        "foreign_buy_streak": 0,
        "trust_buy_streak": 0,
        "foreign_turned_buy": False,
        "foreign_turned_sell": False,
    }

    # 外資連續賣超／買超
    for row in history:
        net = row.get("foreign_net")
        if net is None:
            break
        if net < 0 and streaks["foreign_buy_streak"] == 0:
            streaks["foreign_sell_streak"] += 1
        elif net > 0 and streaks["foreign_sell_streak"] == 0:
            streaks["foreign_buy_streak"] += 1
        else:
            break

    # 投信連續買超
    for row in history:
        net = row.get("trust_net")
        if net is None:
            break
        if net > 0:
            streaks["trust_buy_streak"] += 1
        else:
            break

    # 轉折判斷：今天與昨天方向相反
    if len(history) >= 2:
        today, yesterday = history[0], history[1]
        t_net, y_net = today.get("foreign_net"), yesterday.get("foreign_net")
        if t_net is not None and y_net is not None:
            if t_net > 0 and y_net < 0:
                streaks["foreign_turned_buy"] = True
            elif t_net < 0 and y_net > 0:
                streaks["foreign_turned_sell"] = True
    return streaks


def chip_alerts(chip: dict, streaks: dict) -> list[str]:
    """依籌碼面狀態產生警報訊息（由呼叫端負責去重與發送）。"""
    msgs: list[str] = []
    foreign = chip.get("foreign_net")
    name = f"{chip.get('name', '')} ({chip.get('code', '')})"

    if foreign is not None:
        # 大額賣超（當日）
        if foreign <= -FOREIGN_BIG_SELL_LOTS:
            msgs.append(
                f"⚠️ **【大額賣超】{name}**\n"
                f"外資今日賣超 **{abs(foreign):,}** 張，三大法人合計 {chip.get('total_net') or 0:+,} 張，"
                f"籌碼面急遽轉空，留意停損。"
            )
        elif foreign >= FOREIGN_BIG_SELL_LOTS:
            msgs.append(
                f"💰 **【大額買超】{name}**\n"
                f"外資今日買超 **{foreign:,}** 張，法人回補力道強，可留意是否有波段行情。"
            )

    n_sell = streaks.get("foreign_sell_streak", 0)
    if n_sell >= 3:
        msgs.append(
            f"🔴 **【外資連續賣超】{name}**\n"
            f"外資已連續 **{n_sell}** 個交易日賣超，籌碼面持續偏空，建議觀察止賣訊號再考慮承接。"
        )
    if streaks.get("foreign_turned_buy"):
        msgs.append(
            f"🟢 **【外資轉買超】{name}**\n"
            f"外資由賣超轉為買超（首日轉正），賣壓有緩解跡象，可留意量價確認。"
        )
    if streaks.get("foreign_turned_sell"):
        msgs.append(
            f"🟡 **【外資轉賣超】{name}**\n"
            f"外資由買超轉為賣超（首日轉負），留意短線反轉風險。"
        )

    n_buy = streaks.get("trust_buy_streak", 0)
    if n_buy >= 3:
        msgs.append(
            f"🟢 **【投信連續買超】{name}**\n"
            f"投信連續 **{n_buy}** 個交易日買超，多空資訊請自行判斷。"
        )
    return msgs
