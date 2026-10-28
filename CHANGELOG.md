# 更新紀錄 (Changelog)

所有重要變更都會記錄在此檔案。

## [2026-10-28] — 大修版：時區／限流／穩定性

### 🔴 修復的嚴重問題

| # | 問題 | 根因 | 修復方式 |
|---|---|---|---|
| 1 | **沒開盤也一直發通知** | GitHub Actions Runner 是 UTC，交易時段判斷用本地時間 → bot 以為台北時間 17:00–21:30 是交易時段，晚上狂發警報 | 新增 `src/market_time.py`，所有時間判斷統一 `Asia/Taipei`；workflow 加 `TZ=Asia/Taipei` 雙保險 |
| 2 | **yfinance 被限流（429）** | `indicators.py` 每次呼叫都重新下載 K 線，4 檔 × 每 30 秒 ≈ 一天 2000+ 次請求 | K 線加入 **5 分鐘 TTL 快取**（`HISTORY_TTL=300`）；下載失敗退回過期快取；技術警報改用 MIS 批次查詢已有的即時價 |
| 3 | **監控迴圈會永久停擺** | `price_monitor` 無 try/except，`tasks.loop` 遇未捕捉例外整個停止 | 整體例外處理 + logging，迴圈繼續跑 |
| 4 | **`/hold` `/stoploss` 噴 DB 錯誤** | 舊版 `stocks.db` 缺 `holdings`、`stop_targets` 表與 `exchange` 欄位 | 執行遷移補齊；`init_db()` 每次啟動自動遷移 |
| 5 | **SQLite 連線洩漏** | `with sqlite3.connect()` 不會關閉連線（只 commit），造成 Windows 檔案鎖 | 改用 `closing()` 確保關閉；警報去重查詢加索引 |
| 6 | **定時報告 TypeError** | `datetime.time + timedelta` 不合法 | 檔位判斷改用「分鐘數」比較，抽成純函數 `due_report_slot()` |
| 7 | **@everyone 上線通知打擾** | Actions 每 6 小時重啟 = 每次都發 @everyone（台北 08:00/14:00/20:00/02:00 各一次） | 改為普通訊息（無標記）＋顯示當下時間 |

### 🟡 其他修正

- `on_ready` 重複觸發只發一次上線訊息
- 頻道取得改為「快取 → `fetch_channel`」退回機制（修復 Channel not found）
- 同步的 DB / 網路操作全部移入 `run_in_executor`，不再阻塞 event loop
- MIS 批次查詢分塊（每 30 檔），URL 過長防護
- 單檔查詢不再汙染批次快取時間戳
- 定時報告 90 秒容錯視窗 + 同檔位一天只發一次
- `GUILD_ID` 從硬編碼移到 `.env` / GitHub Secret
- `requirements.txt` 移除未使用的 `apscheduler`、`pandas-ta`，補 `tzdata`
- workflow 加 `concurrency`（防雙 bot 互踢）、pip cache
- 新增 `logging`（console + `bot.log`）
- git 設定修復：commit 作者 email 壞掉導致 contributions 不計入，已改寫全部歷史為 `sfsf100 <shuyoulin0@gmail.com>`

### ✅ 測試

新增 `tests/test_bot.py` — **36 個單元測試全數通過**，不連網、不碰正式 DB：

```
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

涵蓋：market_time（時區/邊界）、twse_api（解析/分塊/快取）、
indicators（TTL/RSI/量比）、alert_engine（去重/觸發/靜音）、
database（遷移/CRUD）、formatters（防呆）、due_report_slot（檔位）。

### 📦 Commit 紀錄

```
648ddac fix: 上線通知不再使用 @everyone
9efd52d fix: scheduled_reports 檔位判斷改用分鐘數比較
c5ca37d fix: 修復時區錯誤、yfinance 限流、迴圈崩潰
```

### ⚠️ 待確認事項

- GitHub repo Secrets 需有：`DISCORD_TOKEN`、`DISCORD_CHANNEL_ID`、`GUILD_ID`（=1511001003716116510）
- 8/7 的排程 run 全部被 cancel，10/28 起重新啟用；需觀察明天 08:00 排程是否正常觸發

---

## 待辦（Backlog）

| 優先 | 項目 | 說明 |
|---|---|---|
| ⭐ 高 | MIS API 被 GitHub IP 封鎖的備援 | Actions 的 IP 常被 TWSE 擋；可加重試邏輯或用證交所 OpenAPI 備援 |
| ⭐ 高 | 警報訊號補強 | RSI>70 超買、站回 5MA、日內漲跌超過 N% |
| 中 | 持倉交易明細 | 支援加碼/減碼紀錄與已實現損益（目前只有單筆平均成本） |
| 中 | `/history` 指令 | 查詢歷史警報紀錄（資料已存但未暴露） |
| 中 | `/debug` 健康診斷指令 | 回報 uptime、上次輪詢時間、快取狀態 |
| 中 | 雲端/本機 DB 不同步問題 | Actions 用 cache 存 DB，與本機各一份；長期考慮雲端 DB 方案 |
| 低 | ETF 漲跌停幅差異 | 債券型 ETF 是 ±5% 非 ±10%（現行以 MIS API 回傳值為準，大致正確） |
| 低 | README 截圖 | 加入 Embed 顯示範例 |
