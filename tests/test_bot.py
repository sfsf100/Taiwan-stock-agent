"""taiwan-stock-bot 單元測試。

執行方式（專案根目錄）：
    .\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v

所有測試皆不發出真實網路請求、不觸碰正式資料庫。
"""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TZ = ZoneInfo("Asia/Taipei")


# ─────────────────────────────────────────────────────────────
# market_time
# ─────────────────────────────────────────────────────────────
class TestMarketTime(unittest.TestCase):
    def test_trading_time_open(self):
        from src.market_time import is_trading_time
        now = datetime(2026, 10, 28, 10, 0, tzinfo=TZ)  # 週三 10:00
        self.assertTrue(is_trading_time(now))

    def test_trading_time_boundaries(self):
        from src.market_time import is_trading_time
        self.assertTrue(is_trading_time(datetime(2026, 10, 28, 9, 0, tzinfo=TZ)))
        self.assertTrue(is_trading_time(datetime(2026, 10, 28, 13, 30, tzinfo=TZ)))
        self.assertFalse(is_trading_time(datetime(2026, 10, 28, 8, 59, tzinfo=TZ)))
        self.assertFalse(is_trading_time(datetime(2026, 10, 28, 13, 31, tzinfo=TZ)))

    def test_weekend_not_trading(self):
        from src.market_time import is_trading_time
        self.assertFalse(is_trading_time(datetime(2026, 10, 31, 10, 0, tzinfo=TZ)))  # 週六
        self.assertFalse(is_trading_time(datetime(2026, 11, 1, 10, 0, tzinfo=TZ)))   # 週日

    def test_uses_taipei_tz(self):
        """同一 UTC 時刻，台北時間應正確換算（UTC 01:00 = 台北 09:00）。"""
        from src.market_time import is_trading_time
        utc = ZoneInfo("UTC")
        now = datetime(2026, 10, 28, 1, 0, tzinfo=utc)
        self.assertTrue(is_trading_time(now))  # 台北 09:00 開盤


# ─────────────────────────────────────────────────────────────
# twse_api（純邏輯，不連網）
# ─────────────────────────────────────────────────────────────
class TestTwseApi(unittest.TestCase):
    def test_safe_float(self):
        from src.twse_api import _safe_float
        self.assertEqual(_safe_float("123.45"), 123.45)
        self.assertIsNone(_safe_float("-"))
        self.assertIsNone(_safe_float("abc"))
        self.assertIsNone(_safe_float("-5"))  # 負數視為無效

    def test_parse_mis_item(self):
        from src.twse_api import _parse_mis_item
        item = {
            "c": "2330", "n": "台積電", "z": "1000.0", "y": "990.0",
            "o": "995.0", "h": "1005.0", "l": "990.0", "v": "30",
            "u": "1089.0", "w": "891.0",
        }
        info = _parse_mis_item(item)
        self.assertEqual(info["code"], "2330")
        self.assertEqual(info["close"], 1000.0)
        self.assertEqual(info["prev_close"], 990.0)
        self.assertEqual(info["limit_up"], 1089.0)
        self.assertEqual(info["limit_down"], 891.0)
        self.assertEqual(info["volume"], 30000)  # 張 → 股

    def test_parse_mis_item_no_trade(self):
        """盤後 z 為 '-' 時應回 None（自然擋掉非交易時段資料）。"""
        from src.twse_api import _parse_mis_item
        self.assertIsNone(_parse_mis_item({"c": "2330", "n": "台積電", "z": "-"}))

    def test_calc_limit_prices(self):
        from src.twse_api import calc_limit_prices
        up, down = calc_limit_prices(100.0)
        self.assertEqual(up, 110.0)
        self.assertEqual(down, 90.0)

    def test_batch_chunking(self):
        """批次查詢應分塊發請求，且結果合併。"""
        from src import twse_api
        codes = [(f"{i:04d}", "tse") for i in range(75)]  # 75 檔 → 3 批
        with patch.object(twse_api, "_query_mis", side_effect=[
            {c: {"code": c} for c, _ in codes[0:30]},
            {c: {"code": c} for c, _ in codes[30:60]},
            {c: {"code": c} for c, _ in codes[60:75]},
        ]) as mock_q, patch.object(twse_api.time, "time", return_value=1e12):
            result = twse_api.fetch_watchlist_prices(codes)
        self.assertEqual(len(result), 75)
        self.assertEqual(mock_q.call_count, 3)

    def test_batch_cache_respected(self):
        from src import twse_api
        twse_api._mis_cache = {"2330": {"code": "2330"}}
        twse_api._mis_cache_ts = time.time()
        try:
            with patch.object(twse_api, "_query_mis") as mock_q:
                result = twse_api.fetch_watchlist_prices([("2330", "tse")])
            mock_q.assert_not_called()
            self.assertIn("2330", result)
        finally:
            twse_api._mis_cache, twse_api._mis_cache_ts = {}, 0.0


# ─────────────────────────────────────────────────────────────
# indicators（TTL 快取）
# ─────────────────────────────────────────────────────────────
class TestIndicators(unittest.TestCase):
    def setUp(self):
        from src import indicators
        indicators.clear_cache()

    def _fake_df(self, closes, volumes=None):
        import pandas as pd
        idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
        data = {"Close": closes}
        if volumes:
            data["Volume"] = volumes
        return pd.DataFrame(data, index=idx)

    def test_fetch_history_ttl(self):
        """TTL 內第二次呼叫不應重新發出下載請求。"""
        from src import indicators
        df = self._fake_df([100.0] * 30)
        with patch("src.indicators.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = df
            first = indicators.fetch_history("2330")
            second = indicators.fetch_history("2330")
        # history() 只被呼叫一次（第二次走快取）
        self.assertEqual(mock_ticker.return_value.history.call_count, 1)
        self.assertIs(first, second)

    def test_fetch_history_expired_ttl(self):
        from src import indicators
        df = self._fake_df([100.0] * 30)
        with patch("src.indicators.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = df
            indicators.fetch_history("2330", ttl=0.05)
            time.sleep(0.06)
            indicators.fetch_history("2330", ttl=0.05)
        self.assertEqual(mock_ticker.return_value.history.call_count, 2)

    def test_fetch_history_failure_falls_back_to_cache(self):
        from src import indicators
        df = self._fake_df([100.0] * 30)
        with patch("src.indicators.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = df
            indicators.fetch_history("2330")
            mock_ticker.return_value.history.side_effect = Exception("boom")
            result = indicators.fetch_history("2330")
        self.assertEqual(len(result), 30)  # 退回舊快取而非空資料

    def test_rsi_calculation(self):
        from src import indicators
        with patch("src.indicators.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = self._fake_df(
                [100 + i for i in range(20)]  # 單邊上漲 → RSI 應很高
            )
            rsi = indicators.get_rsi("2330")
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, 70)

    def test_volume_ratio(self):
        from src import indicators
        vols = [1000] * 20 + [5000]  # 今日量為均量 5 倍
        with patch("src.indicators.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = self._fake_df(
                [100.0] * 21, vols
            )
            ratio = indicators.get_volume_ratio("2330")
        self.assertEqual(ratio, 5.0)


# ─────────────────────────────────────────────────────────────
# alert_engine（以 mock DB 驗證警報邏輯）
# ─────────────────────────────────────────────────────────────
class TestAlertEngine(unittest.TestCase):
    def setUp(self):
        from src import alert_engine, indicators
        indicators.clear_cache()

        # 測試一律在「交易時段」執行；silent 測試另外覆蓋
        self._silent_patch = patch.object(alert_engine, "is_silent_period", return_value=False)
        self._silent_patch.start()
        self.addCleanup(self._silent_patch.stop)

        # 模擬 DB：每檔股票每天每類型只警報一次
        self.alerted = set()
        self.targets = []
        self.stops = []
        alert_engine.db = MagicMock()
        alert_engine.db.has_alerted_today.side_effect = (
            lambda code, k: (code, k) in self.alerted
        )
        alert_engine.db.record_alert.side_effect = lambda code, k: self.alerted.add((code, k))
        alert_engine.db.get_targets.side_effect = lambda: self.targets
        alert_engine.db.get_stop_targets.side_effect = lambda: self.stops
        alert_engine.db.remove_target.side_effect = (
            lambda code, price: self.targets.remove(
                {"stock_code": code, "target_price": price})
        )
        alert_engine.db.remove_stop_target.side_effect = (
            lambda code, price: self.stops.remove(
                {"stock_code": code, "stop_price": price})
        )

    def test_limit_up_alert_once_per_day(self):
        from src.alert_engine import check_alerts
        info = {"close": 110.0, "prev_close": 100.0, "limit_up": 110.0, "limit_down": 90.0}
        first = check_alerts("2330", "台積電", info)
        second = check_alerts("2330", "台積電", info)
        self.assertEqual(len(first), 1)
        self.assertIn("漲停", first[0]["message"])
        self.assertEqual(second, [])  # 第二次不再發

    def test_limit_down_alert(self):
        from src.alert_engine import check_alerts
        info = {"close": 90.0, "prev_close": 100.0, "limit_up": 110.0, "limit_down": 90.0}
        alerts = check_alerts("2330", "台積電", info)
        self.assertEqual(len(alerts), 1)
        self.assertIn("跌停", alerts[0]["message"])

    def test_target_triggered_then_removed(self):
        from src.alert_engine import check_alerts
        self.targets.append({"stock_code": "2330", "target_price": 950.0})
        info = {"close": 960.0, "prev_close": 900.0, "limit_up": 990.0, "limit_down": 810.0}
        alerts = check_alerts("2330", "台積電", info)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(self.targets, [])  # 觸發後自動移除
        # 不會重複觸發
        self.assertEqual(check_alerts("2330", "台積電", info), [])

    def test_stoploss_triggered_then_removed(self):
        from src.alert_engine import check_alerts
        self.stops.append({"stock_code": "2330", "stop_price": 850.0})
        info = {"close": 840.0, "prev_close": 900.0, "limit_up": 990.0, "limit_down": 810.0}
        alerts = check_alerts("2330", "台積電", info)
        self.assertEqual(len(alerts), 1)
        self.assertIn("停損", alerts[0]["message"])
        self.assertEqual(self.stops, [])

    def test_silent_period_no_alerts(self):
        """非交易時段一律靜音（解決『沒開盤也一直通知』）。"""
        from src.alert_engine import check_alerts
        from src import alert_engine as ae
        info = {"close": 110.0, "prev_close": 100.0, "limit_up": 110.0, "limit_down": 90.0}
        with patch.object(ae, "is_silent_period", return_value=True):
            self.assertEqual(check_alerts("2330", "台積電", info), [])
            self.assertEqual(check_technical_alerts := ae.check_technical_alerts("2330", "台積電", price=100.0), [])

    def test_technical_alerts_rsi_oversold(self):
        from src.alert_engine import check_technical_alerts
        from src import alert_engine as ae
        with patch.object(ae, "get_rsi", return_value=25.0), \
             patch.object(ae, "get_ma5", return_value=None), \
             patch.object(ae, "get_volume_ratio", return_value=None):
            alerts = check_technical_alerts("2330", "台積電", price=500.0)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "rsi_oversold")

    def test_technical_alerts_below_ma5(self):
        from src.alert_engine import check_technical_alerts
        from src import alert_engine as ae
        with patch.object(ae, "get_rsi", return_value=55.0), \
             patch.object(ae, "get_ma5", return_value=520.0), \
             patch.object(ae, "get_volume_ratio", return_value=None):
            alerts = check_technical_alerts("2330", "台積電", price=500.0)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "below_ma5")

    def test_technical_alerts_high_volume(self):
        from src.alert_engine import check_technical_alerts
        from src import alert_engine as ae
        with patch.object(ae, "get_rsi", return_value=55.0), \
             patch.object(ae, "get_ma5", return_value=None), \
             patch.object(ae, "get_volume_ratio", return_value=4.2):
            alerts = check_technical_alerts("2330", "台積電", price=500.0)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "high_volume")


# ─────────────────────────────────────────────────────────────
# database（使用暫存檔，不碰正式 DB）
# ─────────────────────────────────────────────────────────────
class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        import src.database as database
        self.database = database
        database.DB_PATH = self.db_path

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_db_creates_all_tables(self):
        self.database.init_db()
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        for t in ("watchlist", "targets", "stop_targets", "alert_history", "holdings", "chip_daily"):
            self.assertIn(t, tables)

    def test_migrate_adds_exchange_column(self):
        """模擬舊版 DB（無 exchange 欄位）能自動升級。"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE watchlist (stock_code TEXT PRIMARY KEY, stock_name TEXT NOT NULL, added_at TEXT NOT NULL)")
        conn.execute("INSERT INTO watchlist VALUES ('2330', '台積電', '2026-01-01')")
        conn.commit()
        conn.close()
        self.database.init_db()
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT exchange FROM watchlist WHERE stock_code='2330'").fetchone()
        conn.close()
        self.assertEqual(row[0], "tse")

    def test_watchlist_crud(self):
        self.database.init_db()
        self.database.add_stock("2330", "台積電", "tse")
        self.assertTrue(self.database.is_watching("2330"))
        wl = self.database.get_watchlist()
        self.assertEqual(wl[0]["stock_code"], "2330")
        self.database.remove_stock("2330")
        self.assertFalse(self.database.is_watching("2330"))

    def test_targets_add_and_remove(self):
        self.database.init_db()
        self.database.add_target("2330", 1000.0)
        self.assertEqual(len(self.database.get_targets()), 1)
        self.database.remove_target("2330", 1000.0)
        self.assertEqual(len(self.database.get_targets()), 0)

    def test_holdings_crud(self):
        self.database.init_db()
        self.database.add_holding("2330", "台積電", 1000, 950.0)
        h = self.database.get_holding("2330")
        self.assertEqual(h["shares"], 1000)
        self.assertEqual(h["cost_price"], 950.0)
        self.database.remove_holding("2330")
        self.assertIsNone(self.database.get_holding("2330"))

    def test_alert_dedup(self):
        self.database.init_db()
        self.assertFalse(self.database.has_alerted_today("2330", "limit_up"))
        self.database.record_alert("2330", "limit_up")
        self.assertTrue(self.database.has_alerted_today("2330", "limit_up"))
        self.database.clear_today_alerts()
        # 今日紀錄應被保留（clear 只刪非今日）
        self.assertTrue(self.database.has_alerted_today("2330", "limit_up"))


# ─────────────────────────────────────────────────────────────
# main.py 定時報告檔位判斷
# ─────────────────────────────────────────────────────────────
class TestDueReportSlot(unittest.TestCase):
    def test_open_slot(self):
        from main import due_report_slot
        self.assertEqual(due_report_slot(datetime(2026, 10, 28, 9, 5, 30, tzinfo=TZ)), 0)

    def test_midday_slot(self):
        from main import due_report_slot
        self.assertEqual(due_report_slot(datetime(2026, 10, 28, 12, 0, 59, tzinfo=TZ)), 1)

    def test_close_slot(self):
        from main import due_report_slot
        self.assertEqual(due_report_slot(datetime(2026, 10, 28, 13, 36, 10, tzinfo=TZ)), 2)

    def test_outside_window(self):
        from main import due_report_slot
        self.assertIsNone(due_report_slot(datetime(2026, 10, 28, 9, 7, 1, tzinfo=TZ)))
        self.assertIsNone(due_report_slot(datetime(2026, 10, 28, 15, 0, 0, tzinfo=TZ)))


# ─────────────────────────────────────────────────────────────
# formatters（防呆：資料缺漏時不應噴例外）
# ─────────────────────────────────────────────────────────────
class TestFormatters(unittest.TestCase):
    def test_stock_list_embed_empty(self):
        from src.formatters import stock_list_embed
        embed = stock_list_embed([], {})
        self.assertIn("空", embed.description)

    def test_stock_list_embed_zero_prev(self):
        """prev_close 缺漏（=0）時不應除以零。"""
        from src.formatters import stock_list_embed
        embed = stock_list_embed(
            [{"stock_code": "2330", "stock_name": "台積電"}],
            {"2330": {"close": 1000.0, "prev_close": 0}},
        )
        self.assertEqual(len(embed.fields), 1)

    def test_holdings_embed_profit(self):
        from src.formatters import holdings_embed
        embed = holdings_embed(
            [{"stock_code": "2330", "stock_name": "台積電", "shares": 1000, "cost_price": 900.0}],
            {"2330": {"close": 1000.0}},
        )
        self.assertIn("100000", embed.footer.text.replace(",", ""))


# ─────────────────────────────────────────────────────────────
# institutional（籌碼面解析與連續日數，純邏輯、不連網）
# ─────────────────────────────────────────────────────────────
class TestInstitutional(unittest.TestCase):
    def test_to_int(self):
        from src.institutional import _to_int
        self.assertEqual(_to_int("23,482,462"), 23482462)
        self.assertEqual(_to_int("-1,780,889"), -1780889)
        self.assertIsNone(_to_int(""))
        self.assertIsNone(_to_int("-"))
        self.assertIsNone(_to_int(None))
        self.assertIsNone(_to_int("abc"))
        self.assertEqual(_to_int(" 12 "), 12)

    def test_shares_to_lots(self):
        from src.institutional import _shares_to_lots
        self.assertEqual(_shares_to_lots("8,084,870"), 8085)  # 股 → 張，四捨五入
        self.assertEqual(_shares_to_lots("-1,780,889"), -1781)
        self.assertEqual(_shares_to_lots(""), 0)

    def test_roc_to_ad(self):
        from src.institutional import _roc_to_ad
        self.assertEqual(_roc_to_ad("1151103"), "2026-11-03")
        self.assertEqual(_roc_to_ad("1141231"), "2025-12-31")
        self.assertEqual(_roc_to_ad("bad"), "bad")

    def test_parse_t86(self):
        from src.institutional import _parse_t86
        payload = {
            "date": "20261103",
            "fields": [
                "證券代號", "證券名稱",
                "外陸資買進股數(不含外資自營商)", "外陸資賣出股數(不含外資自營商)",
                "外陸資買賣超股數(不含外資自營商)", "投信買賣超股數",
                "自營商買賣超股數", "三大法人買賣超股數",
            ],
            "data": [
                ["2330", "台積電           ", "2,348,246", "15,397,592", "-13,049,346",
                 "64,000", "-5,000", "-10,000"],
                ["=-weighted average==="],
            ],
        }
        result = _parse_t86(payload)
        self.assertIn("2330", result)
        row = result["2330"]
        self.assertEqual(row["name"], "台積電")
        self.assertEqual(row["date"], "2026-11-03")
        self.assertEqual(row["foreign_net"], -13049)  # 張，四捨五入
        self.assertEqual(row["trust_net"], 64)
        self.assertEqual(row["dealer_net"], -5)
        self.assertEqual(row["total_net"], -10)
        self.assertNotIn("=", result)  # 權重平均列應被跳過

    def test_parse_tpex_insti(self):
        """TPEx 欄位名含亂空格，正規化比對應該抓得到值。"""
        from src.institutional import _parse_tpex_insti
        items = [
            {
                "Date": "1151103",
                "SecuritiesCompanyCode": "7130",
                "CompanyName": "台科股",
                "ForeignInvestorsIncludeMainlandAreaInvestors-Difference": "500,000",   # 标準鍵
                " Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "-300",
                "SecuritiesInvestmentTrustCompanies-Difference": "-100,000",
                "Dealers-Difference": "200,000",
                "TotalDifference": "600,000",
            }
        ]
        result = _parse_tpex_insti(items)
        row = result["7130"]
        self.assertEqual(row["date"], "2026-11-03")
        self.assertEqual(row["foreign_net"], 500)
        self.assertEqual(row["trust_net"], -100)
        self.assertEqual(row["dealer_net"], 200)
        self.assertEqual(row["total_net"], 600)

    def test_parse_tpex_insti_only_latest_date(self):
        from src.institutional import _parse_tpex_insti
        items = [
            {"Date": "1151102", "SecuritiesCompanyCode": "AAA", "ForeignInvestorsIncludeMainlandAreaInvestors-Difference": "999999"},
            {"Date": "1151103", "SecuritiesCompanyCode": "AAA", "ForeignInvestorsIncludeMainlandAreaInvestors-Difference": "1000"},
        ]
        result = _parse_tpex_insti(items)
        self.assertEqual(result["AAA"]["foreign_net"], 1)
        self.assertEqual(result["AAA"]["date"], "2026-11-03")

    def test_compute_streaks(self):
        from src.institutional import compute_streaks
        history = [
            {"foreign_net": -500, "trust_net": 100},   # 今天
            {"foreign_net": -300, "trust_net": -100},
            {"foreign_net": -100, "trust_net": 50},
            {"foreign_net": 200, "trust_net": 0},     # 方向改變，停止累計
        ]
        s = compute_streaks(history)
        self.assertEqual(s["foreign_sell_streak"], 3)
        self.assertEqual(s["foreign_buy_streak"], 0)
        self.assertEqual(s["trust_buy_streak"], 1)  # 只有今天買超，昨天轉負即停止
        self.assertFalse(s["foreign_turned_buy"])

    def test_compute_streaks_turned_buy(self):
        from src.institutional import compute_streaks
        history = [
            {"foreign_net": 500, "trust_net": 0},   # 今天買超
            {"foreign_net": -800, "trust_net": 0},  # 昨天賣超
        ]
        s = compute_streaks(history)
        self.assertTrue(s["foreign_turned_buy"])
        self.assertEqual(s["foreign_buy_streak"], 1)

    def test_compute_streaks_trust_buy(self):
        from src.institutional import compute_streaks
        history = [
            {"foreign_net": 0, "trust_net": 100},
            {"foreign_net": 0, "trust_net": 50},
            {"foreign_net": 0, "trust_net": 10},
            {"foreign_net": 0, "trust_net": -5},
        ]
        s = compute_streaks(history)
        self.assertEqual(s["trust_buy_streak"], 3)

    def test_chip_alerts_big_sell(self):
        from src.institutional import chip_alerts
        chip = {"name": "台積電", "code": "2330", "foreign_net": -2500, "total_net": -2600}
        msgs = chip_alerts(chip, {"foreign_sell_streak": 0, "trust_buy_streak": 0})
        self.assertTrue(any("大額賣超" in m for m in msgs))

    def test_chip_alerts_sell_streak(self):
        from src.institutional import chip_alerts
        chip = {"name": "台積電", "code": "2330", "foreign_net": -100, "total_net": -150}
        msgs = chip_alerts(chip, {"foreign_sell_streak": 4, "trust_buy_streak": 0})
        self.assertTrue(any("連續" in m and "賣超" in m for m in msgs))


# ─────────────────────────────────────────────────────────────
# formatters 籌碼面（缺資料時不可爆例外）
# ─────────────────────────────────────────────────────────────
class TestChipFormatters(unittest.TestCase):
    CHIP = {
        "name": "台積電", "date": "2026-11-03",
        "foreign_net": -11703, "trust_net": 2346, "dealer_net": 2658,
        "total_net": -6699, "margin_balance": 35219, "margin_change": 258,
    }

    def test_chips_embed_fields(self):
        from src.formatters import chips_embed
        embed = chips_embed(
            "2330", self.CHIP,
            history=[{"data_date": "2026-11-03", "foreign_net": -11703, "trust_net": 2346}],
            streaks={"foreign_sell_streak": 1, "foreign_turned_buy": False},
            rsi=28.5,
        )
        self.assertEqual(len(embed.fields) > 0, True)
        self.assertIn("籌碼", embed.title)

    def test_chips_embed_missing_values(self):
        """缺融資／缺 RSI／空歷史都不可噴例外。"""
        from src.formatters import chips_embed
        embed = chips_embed("2330", {"name": "台積電", "foreign_net": None}, [], {})
        self.assertIsNotNone(embed)

    def test_daily_chip_embed_entry(self):
        from src.formatters import daily_chip_embed
        embed = daily_chip_embed("📊 收盤籌碼速報", [
            {"code": "2330", "chip": self.CHIP, "streaks": {"foreign_sell_streak": 4}},
        ])
        self.assertIn("外資連賣 4 日", embed.fields[0].name.replace("*", ""))


# ─────────────────────────────────────────────────────────────
# portfolio_guard（持倉防線，不連網）
# ─────────────────────────────────────────────────────────────
class TestPortfolioGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        import src.database as database
        self.database = database
        database.DB_PATH = self.db_path
        database.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_loss_alert_triggers(self):
        from src.portfolio_guard import check_position_guard
        holding = {"stock_code": "2330", "stock_name": "台積電", "shares": 1000,
                   "cost_price": 1000.0, "added_at": "2026-11-01"}
        info = {"close": 900.0}
        alerts = check_position_guard(holding, info)
        self.assertTrue(any(a["type"] == "position_loss" for a in alerts))
        self.assertIn("10.0%", alerts[0]["message"])  # 預設門檻 -8%，跌 10% 應觸發

    def test_no_alert_when_profit(self):
        from src.portfolio_guard import check_position_guard
        holding = {"stock_code": "2330", "stock_name": "台積電", "shares": 1000,
                   "cost_price": 900.0, "added_at": "2026-11-01"}
        alerts = check_position_guard(holding, {"close": 950.0})
        self.assertEqual(alerts, [])

    def test_loss_alert_dedup_same_day(self):
        from src.portfolio_guard import check_position_guard
        holding = {"stock_code": "2330", "stock_name": "台積電", "shares": 1000,
                   "cost_price": 1000.0, "added_at": "2026-11-01"}
        first = check_position_guard(holding, {"close": 900.0})
        self.assertEqual(len(first), 1)
        second = check_position_guard(holding, {"close": 880.0})  # 仍未止損24小時
        self.assertEqual(second, [])  # 同日去重

    def test_loss_threshold_custom(self):
        from src.portfolio_guard import check_position_guard
        holding = {"stock_code": "2330", "stock_name": "台積電", "shares": 1000,
                   "cost_price": 1000.0, "added_at": "2026-11-01", "loss_guard_pct": 15}
        # -8% 不觸發（門檻 -15%），-16% 才觸發
        self.assertEqual(check_position_guard(holding, {"close": 920.0}), [])
        alerts = check_position_guard(holding, {"close": 840.0})
        self.assertTrue(any(a["type"] == "position_loss" for a in alerts))

    def test_trailing_protect(self):
        from src import portfolio_guard
        holding = {"stock_code": "2330", "stock_name": "台積電", "shares": 1000,
                   "cost_price": 1000.0, "added_at": "2026-11-01"}
        with patch.object(portfolio_guard, "_high_since_added", return_value=1100.0):
            alerts = portfolio_guard.check_position_guard(holding, {"close": 950.0})
        # 1000→1100 獲利，1100→950 回撤 13.6% ≥ 預設 10% → 觸發
        self.assertTrue(any(a["type"] == "trailing_protect" for a in alerts))

    def test_combo_chip_message(self):
        from src.portfolio_guard import combo_chip_message
        holding = {"stock_code": "2330", "stock_name": "台積電", "shares": 1000,
                   "cost_price": 1000.0}
        # 虧損 + 外資賣超
        msg = combo_chip_message(holding, {"close": 900.0}, foreign_net=-11703)
        self.assertIsNotNone(msg)
        self.assertIn("雙重警告", msg)
        self.assertIn("11,703", msg)
        # 獲利中 → 不觸發
        self.assertIsNone(combo_chip_message(holding, {"close": 1000.0}, foreign_net=-500))
        # 外資買超 → 不觸發
        self.assertIsNone(combo_chip_message(holding, {"close": 900.0}, foreign_net=500))


if __name__ == "__main__":
    unittest.main()
