# 台股監控 Discord Bot

即時監控台灣股市（上市/上櫃），透過 Discord 發送漲跌停警報、目標價／停損通知，並提供技術面分析建議。

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
| `/ping` | 確認 Bot 是否正常運作 |

**自動警報（每 30 秒輪詢）：**
- 漲停 / 跌停觸發
- 達到目標價
- 跌破停損價
- RSI(14) < 30（超賣）
- 跌破 5 日均線
- 成交量超過均量 3 倍

**定時報告（交易日）：**
- 09:05 開盤報告
- 12:00 盤中報告
- 13:35 收盤報告

## 架構

```
taiwan-stock-bot/
├── main.py               # Bot 主體、Slash Commands、監控迴圈
├── src/
│   ├── twse_api.py       # TWSE MIS 即時 API（上市）+ yfinance fallback
│   ├── alert_engine.py   # 警報邏輯（漲跌停、目標價、停損、技術指標）
│   ├── indicators.py     # RSI、MA5、MA20、量比、近期高低
│   ├── database.py       # SQLite（監控清單、目標價、停損、警報記錄）
│   └── formatters.py     # Discord Embed 格式化
├── data/
│   └── stocks.db         # SQLite 資料庫（自動建立）
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

> 上櫃股票（OTC）同樣支援，Bot 新增時會自動識別交易所。

## 注意事項

- 本 Bot 僅供個人學習與資訊參考，**非投資建議**
- `/recommend` 建議價位基於技術指標，不保證準確性
- 警報每日同類型只發送一次，避免重複打擾
- 非交易時段（09:00–13:30、假日）不輪詢，不發出警報

## 授權

MIT License
