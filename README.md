# 台股監控 Discord Bot

即時監控台灣股市（上市/上櫃），透過 Discord 發送漲跌停警報、目標價／停損通知，並提供技術面分析建議與**籌碼面（三大法人買賣超＋融資融券）查詢與買盤時機判讀**。

## 功能

| 指令 | 說明 |
|---|---|
| `/watch 2330 2454 0050` | 新增監控股票（支援多檔同時新增） |
| `/unwatch 2330` | 移除監控股票 |
| `/list` | 顯示監控清單與即時價位 |
| `/status 2330` | 查詢單檔詳細資訊（開高低收、RSI、5MA、漲跌停價） |
| `/price 2330` | 快速查詢現價 |
| `/target 2330 1000` | 設定目標價，達到時 @everyone 通知 |
| `/stoploss 2330 800` | 設定停損價，跌破時 @everyone 通知 |
| `/recommend 2330` | 技術分析與建議目標價／停損價（RSI、MA5/20、20日高低） |
| `/chips 2330` | 籌碼面查詢：三大法人買賣超、融資增減、近期動向、買盤時機判讀 |
| `/ping` | 確認 Bot 是否正常運作 |

**自動警報（每 30 秒輪詢）：**
- 漲停 / 跌停觸發
- 達到目標價
- 跌破停損價
- RSI(14) < 30（超賣）
- 跌破 5 日均線
- 成交量超過均量 3 倍
- 從 20 日高點回撤 ≥ 15%（跌深警示，提醒勿急著接刀）
- 回撤 ≥ 10% 且量縮至均量 70% 以下（量縮止跌初步訊號，12:30 後評估）

**籌碼面（每日 15:30 收盤速報 + 每小時刷新）：**
- 外資 / 投信 / 自營商當日買賣超（張）
- 融資（散戶）與融券增減
- 外資連續賣超 ≥ 3 日 → @everyone 警告
- 外資大額買賣超（預設 ±1000 張，可用環境變數 `CHIP_FOREIGN_BIG_SELL_LOTS` 調整）
- 外資由賣超轉買超 / 由買超轉賣超（首日轉折提示）
- 投信連續買超 ≥ 3 日
- 一併寫入每日快照（SQLite `chip_daily`），供計算連續天數

**定時報告（交易日）：**
- 09:05 開盤報告
- 12:00 盤中報告
- 13:35 收盤報告
- 15:30 收盤籌碼速報（法人資料發布後自動重試至成功）

## 架構

```
taiwan-stock-bot/
├── main.py               # Bot 主體、Slash Commands、監控迴圈
├── src/
│   ├── market_time.py    # 台北時區交易時段判斷（解決雲端 UTC 時區問題）
│   ├── twse_api.py       # TWSE MIS 即時 API（上市）+ yfinance fallback
│   ├── institutional.py  # 籌碼面：三大法人買賣超（上市+上櫃）＋融資融券餘額
│   ├── alert_engine.py   # 警報邏輯（漲跌停、目標價、停損、技術指標、跌深/量縮）
│   ├── indicators.py     # RSI、MA5、MA20、量比、近期高低（K 線 5 分鐘 TTL 快取）
│   ├── database.py       # SQLite（監控清單、目標價、停損、警報記錄、籌碼快照）
│   └── formatters.py     # Discord Embed 格式化
├── tests/
│   └── test_bot.py       # 單元測試（不連網、不碰正式 DB）
├── data/
│   └── stocks.db         # SQLite 資料庫（自動建立＋自動遷移）
├── .github/
│   └── workflows/
│       └── run-bot.yml   # GitHub Actions 雲端自動運行
├── .env.example          # 環境變數範本
└── requirements.txt
```

## 快速開始

### 1. 建立 Discord Bot

1. 前往 [Discord Developer Portal](https://discord.com/developers/applications)
2. 建立新 Application → 進入 **Bot** 頁面
3. 啟用 **Message Content Intent**（非必要但建議開啟）
4. 複製 **Token**
5. 用以下連結邀請 Bot 進入你的伺服器（替換 `CLIENT_ID`）：
   ```
   https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=2048&scope=bot%20applications.commands
   ```

### 2. 設定環境變數

```bash
cp .env.example .env
```

編輯 `.env`：

```env
DISCORD_TOKEN=你的_Bot_Token
DISCORD_CHANNEL_ID=要發送通知的頻道ID
# 選填：Discord 伺服器 ID（加速 Slash 指令同步）
GUILD_ID=你的伺服器ID
```

> 頻道 ID 取得方式：Discord 開啟開發者模式（設定 → 進階），右鍵頻道 → 複製 ID

### 3. 安裝套件

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. 啟動 Bot

```bash
python main.py
```

## 雲端部署（GitHub Actions）

Bot 可免費部署在 GitHub Actions 上，每 6 小時自動重啟（Actions 單次最長 6 小時）。

1. Fork 此專案到你的 GitHub
2. 前往 **Settings → Secrets and variables → Actions**，新增兩個 Secret：
   - `DISCORD_TOKEN`
   - `DISCORD_CHANNEL_ID`
3. 前往 **Actions** 頁籤，手動觸發 `Run Taiwan Stock Bot` workflow

> 之後每 6 小時會自動重啟一次，確保 Bot 持續運行。

## 資料來源

| 資料 | 來源 |
|---|---|
| 即時股價、漲跌停價 | [TWSE MIS API](https://mis.twse.com.tw)（上市） |
| 歷史 K 線（RSI/MA）| [yfinance](https://github.com/ranaroussi/yfinance)（Yahoo Finance） |
| 三大法人買賣超（上市） | [TWSE RWD fund/T86](https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALL)（需 `selectType=ALL`） |
| 三大法人買賣超（上櫃） | [TPEx OpenAPI tpex_3insti_daily_trading](https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading) |
| 融資融券餘額（上市） | [TWSE OpenAPI exchangeReport/MI_MARGN](https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN) |
| 融資融券餘額（上櫃） | [TPEx OpenAPI tpex_mainboard_margin_balance](https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance) |

> 上櫃股票（OTC）同樣支援，Bot 新增時會自動識別交易所；籌碼面資料由證交所與櫃買中心**免金鑰公開 API** 取得。

## 測試

```bash
python -m unittest discover -s tests -v
```

測試不發出真實網路請求，也不會觸碰正式資料庫（`data/stocks.db`）。

## 注意事項

- 本 Bot 僅供個人學習與資訊參考，**非投資建議**
- `/recommend` 建議價位基於技術指標，不保證準確性
- `/chips` 買盤時機判讀為籌碼面＋技術面規則組合，僅供參考
- 籌碼面資料為日資料，盤後才會更新，`/chips` 顯示最近一個交易日
- 外資大額買賣超門檻可用環境變數 `CHIP_FOREIGN_BIG_SELL_LOTS` 調整（預設 1000 張）
- 警報每日同類型只發送一次，避免重複打擾
- 非交易時段（09:00–13:30、假日）不輪詢，不發出警報

## 授權

MIT License
