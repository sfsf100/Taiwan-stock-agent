import os
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
from datetime import datetime

from src import database as db
from src.market_time import now_taipei, is_trading_time
from src.twse_api import (
    get_stock_info, validate_stock, get_realtime_price,
    fetch_watchlist_prices,
)
from src.alert_engine import check_alerts, check_technical_alerts
from src.formatters import (
    stock_list_embed, stock_status_embed, daily_report_embed, recommend_embed,
    holdings_embed,
)
from src.indicators import preload, get_rsi, get_ma5, get_ma20, get_recent_high_low

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("stock-bot")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# 定時報告檔位：台北時間（時, 分）→ 標題
REPORT_SLOTS = [
    ((9, 5), "🌅 09:05 開盤報告"),
    ((12, 0), "☀️ 12:00 盤中報告"),
    ((13, 35), "🌆 13:35 收盤報告"),
]
# 記錄今天已發過的報告檔位，避免重複發送
_sent_reports: set[str] = set()
_sent_reports_date = None


def _report_slot_key(now: datetime) -> str:
    return f"{now.date().isoformat()}@{now.strftime('%H:%M')}"


async def _get_channel() -> discord.abc.Messageable | None:
    """優先使用快取；快取未就緒時退回 fetch_channel（會發 API 請求）。"""
    ch = client.get_channel(CHANNEL_ID)
    if ch:
        return ch
    try:
        ch = await client.fetch_channel(CHANNEL_ID)
    except (discord.NotFound, discord.HTTPException, ValueError) as e:
        log.error("找不到頻道 %s：%s", CHANNEL_ID, e)
        return None
    return ch


# ── 定時輪詢（30 秒）────────────────────────────────────────
@tasks.loop(seconds=30)
async def price_monitor():
    if not is_trading_time():
        return
    try:
        channel = await _get_channel()
        if not channel:
            return

        watchlist = db.get_watchlist()
        if not watchlist:
            return

        # Batch-fetch all prices in a single API call (executed off the event loop)
        codes_exchanges = [(s["stock_code"], s.get("exchange", "tse")) for s in watchlist]
        loop = asyncio.get_running_loop()
        prices = await loop.run_in_executor(None, fetch_watchlist_prices, codes_exchanges)

        for s in watchlist:
            code = s["stock_code"]
            name = s["stock_name"]
            info = prices.get(code)
            if not info:
                continue

            alerts = await loop.run_in_executor(
                None, check_alerts, code, name, info
            )
            tech = await loop.run_in_executor(
                None, check_technical_alerts, code, name, info["close"]
            )
            for alert in alerts + tech:
                try:
                    await channel.send(
                        alert["message"],
                        allowed_mentions=discord.AllowedMentions(everyone=True),
                    )
                except discord.HTTPException as e:
                    log.warning("發送警報失敗 %s：%s", code, e)
    except Exception:
        log.exception("price_monitor 發生未預期錯誤（迴圈將繼續執行）")


async def send_daily_report(title: str):
    channel = await _get_channel()
    if not channel:
        return
    watchlist = db.get_watchlist()
    if not watchlist:
        return
    codes_exchanges = [(s["stock_code"], s.get("exchange", "tse")) for s in watchlist]
    loop = asyncio.get_running_loop()
    prices = await loop.run_in_executor(None, fetch_watchlist_prices, codes_exchanges)
    embed = daily_report_embed(title, watchlist, prices)
    await channel.send(embed=embed)


def _report_slot_key(now: datetime) -> str:
    return f"{now.date().isoformat()}@{now.strftime('%H:%M')}"


def due_report_slot(now: datetime, slots: list | None = None, window_sec: float = 90) -> int | None:
    """判斷現在時間是否落在某個報告檔位的容錯視窗內。

    回傳檔位索引（REPORT_SLOTS 的 index），不在任何檔位則回傳 None。
    以「分鐘數」比較，避開 datetime.time 無法加 timedelta 的限制。
    """
    slots = slots if slots is not None else REPORT_SLOTS
    now_min = now.hour * 60 + now.minute + now.second / 60
    for i, ((hh, mm), _title) in enumerate(slots):
        slot_min = hh * 60 + mm
        if slot_min <= now_min <= slot_min + window_sec / 60:
            return i
    return None


# ── 定時報告 ─────────────────────────────────────────────
@tasks.loop(seconds=30)
async def scheduled_reports():
    """定時報告：以台北時間判斷檔位，且同一檔位一天只發一次。"""
    global _sent_reports_date
    now = now_taipei()
    if now.weekday() >= 5:
        return

    if _sent_reports_date != now.date().isoformat():
        _sent_reports.clear()
        _sent_reports_date = now.date().isoformat()

    idx = due_report_slot(now)
    if idx is None:
        return
    (hh, mm), title = REPORT_SLOTS[idx]
    key = _report_slot_key(now.replace(hour=hh, minute=mm))
    if key in _sent_reports:
        return
    _sent_reports.add(key)
    try:
        await send_daily_report(title)
    except Exception:
        log.exception("定時報告發送失敗：%s", title)


@client.event
async def on_ready():
    try:
        db.init_db()
        db.clear_today_alerts()
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)

        watchlist = db.get_watchlist()
        if watchlist:
            codes = [s["stock_code"] for s in watchlist]
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, preload, codes)

        if not price_monitor.is_running():
            price_monitor.start()
        if not scheduled_reports.is_running():
            scheduled_reports.start()

        log.info("Bot 已啟動：%s，監控 %d 檔股票", client.user, len(watchlist))
        # 上線通知只在初次啟動發送，重連（on_ready 可能觸發多次）不重複打擾
        if not getattr(client, "_online_announced", False):
            client._online_announced = True
            channel = await _get_channel()
            if channel:
                await channel.send(
                    f"@everyone ✅ 台股監控 Bot 已上線！監控中：{len(watchlist)} 檔股票",
                    allowed_mentions=discord.AllowedMentions(everyone=True),
                )
    except Exception:
        log.exception("on_ready 發生錯誤")


# ── Slash Commands ────────────────────────────────────────

@tree.command(name="ping", description="測試 Bot 是否正常運作")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong！Bot 運作正常。")


@tree.command(name="watch", description="新增監控股票")
@app_commands.describe(codes="股票代碼，空格分隔，例如：2330 2454 0050")
async def watch(interaction: discord.Interaction, codes: str):
    await interaction.response.defer()
    results = []
    loop = asyncio.get_running_loop()
    for code in codes.split():
        code = code.strip()
        if db.is_watching(code):
            results.append(f"ℹ️ {code} 已在監控清單")
            continue
        name, exchange = await loop.run_in_executor(None, validate_stock, code)
        if name:
            db.add_stock(code, name, exchange)
            holding = db.get_holding(code)
            holding_tag = f"　💼 持有中 {holding['shares']} 股，成本 {holding['cost_price']:.2f}" if holding else ""
            results.append(f"✅ 已新增：{name} ({code})  [{exchange.upper()}]{holding_tag}")
        else:
            results.append(f"❌ 找不到代碼：{code}")
    await interaction.followup.send("\n".join(results))


@tree.command(name="unwatch", description="移除監控股票")
@app_commands.describe(code="股票代碼，例如 2330")
async def unwatch(interaction: discord.Interaction, code: str):
    if db.is_watching(code):
        info = await asyncio.get_running_loop().run_in_executor(None, get_stock_info, code)
        name = info["name"] if info else code
        db.remove_stock(code)
        await interaction.response.send_message(f"✅ 已移除監控：{name} ({code})")
    else:
        await interaction.response.send_message(f"ℹ️ {code} 不在監控清單中")


@tree.command(name="list", description="顯示監控清單與即時價位")
async def list_stocks(interaction: discord.Interaction):
    await interaction.response.defer()
    watchlist = db.get_watchlist()
    codes_exchanges = [(s["stock_code"], s.get("exchange", "tse")) for s in watchlist]
    loop = asyncio.get_running_loop()
    prices = await loop.run_in_executor(None, fetch_watchlist_prices, codes_exchanges)
    embed = stock_list_embed(watchlist, prices)
    await interaction.followup.send(embed=embed)


@tree.command(name="status", description="查詢單檔股票詳細資訊")
@app_commands.describe(code="股票代碼，例如 2330")
async def status(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, get_stock_info, code)
    if not info:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")
        return
    embed = await loop.run_in_executor(None, stock_status_embed, code, info)
    await interaction.followup.send(embed=embed)


@tree.command(name="target", description="設定目標價警報（漲至此價位時通知）")
@app_commands.describe(code="股票代碼", price="目標價格")
async def target(interaction: discord.Interaction, code: str, price: float):
    await interaction.response.defer()
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, get_stock_info, code)
    if not info:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")
        return
    name = info["name"]
    if not db.is_watching(code):
        db.add_stock(code, name, "tse")
    db.add_target(code, price)
    await interaction.followup.send(
        f"🎯 已設定 **{name} ({code})** 目標價：**{price:.2f}** 元"
    )


@tree.command(name="stoploss", description="設定停損價警報（跌至此價位時通知）")
@app_commands.describe(code="股票代碼", price="停損價格")
async def stoploss(interaction: discord.Interaction, code: str, price: float):
    await interaction.response.defer()
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, get_stock_info, code)
    if not info:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")
        return
    name = info["name"]
    if not db.is_watching(code):
        db.add_stock(code, name, "tse")
    db.add_stop_target(code, price)
    await interaction.followup.send(
        f"🛡️ 已設定 **{name} ({code})** 停損價：**{price:.2f}** 元\n（跌破時將發出 @everyone 警告）"
    )


@tree.command(name="recommend", description="技術面分析與建議目標／停損價位")
@app_commands.describe(code="股票代碼，例如 2330")
async def recommend(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, get_stock_info, code)
    if not info:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")
        return

    rsi = await loop.run_in_executor(None, get_rsi, code)
    ma5 = await loop.run_in_executor(None, get_ma5, code)
    ma20 = await loop.run_in_executor(None, get_ma20, code)
    high20, low20 = await loop.run_in_executor(None, get_recent_high_low, code)

    embed = recommend_embed(code, info, rsi, ma5, ma20, high20, low20)
    await interaction.followup.send(embed=embed)


@tree.command(name="price", description="快速查詢台股現價")
@app_commands.describe(code="股票代碼，例如 2330")
async def price_cmd(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    loop = asyncio.get_running_loop()
    p = await loop.run_in_executor(None, get_realtime_price, code)
    if p:
        await interaction.followup.send(f"📈 **{code}** 現價：**{p:.2f}**")
    else:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")


@tree.command(name="hold", description="記錄持有股票（永久儲存）")
@app_commands.describe(code="股票代碼", shares="持有股數", cost="平均成本價")
async def hold(interaction: discord.Interaction, code: str, shares: int, cost: float):
    await interaction.response.defer()
    loop = asyncio.get_running_loop()
    name_from_db = None
    if db.is_watching(code):
        wl = db.get_watchlist()
        name_from_db = next((s["stock_name"] for s in wl if s["stock_code"] == code), None)
    if not name_from_db:
        name_from_db, _ = await loop.run_in_executor(None, validate_stock, code)
    if not name_from_db:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")
        return
    db.add_holding(code, name_from_db, shares, cost)
    await interaction.followup.send(
        f"💼 已記錄持倉：**{name_from_db} ({code})**　{shares} 股　成本 {cost:.2f} 元"
    )


@tree.command(name="unhold", description="刪除持倉紀錄")
@app_commands.describe(code="股票代碼")
async def unhold(interaction: discord.Interaction, code: str):
    holding = db.get_holding(code)
    if holding:
        db.remove_holding(code)
        await interaction.response.send_message(
            f"✅ 已刪除持倉：**{holding['stock_name']} ({code})**"
        )
    else:
        await interaction.response.send_message(f"ℹ️ {code} 沒有持倉紀錄")


@tree.command(name="holdings", description="查看持倉清單與損益")
async def holdings_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    held = db.get_holdings()
    if not held:
        await interaction.followup.send("📂 尚無持倉紀錄，用 `/hold` 新增。")
        return
    loop = asyncio.get_running_loop()
    wl = db.get_watchlist()
    exchange_map = {s["stock_code"]: s.get("exchange", "tse") for s in wl}
    codes_exchanges = [(h["stock_code"], exchange_map.get(h["stock_code"], "tse")) for h in held]
    prices = await loop.run_in_executor(None, fetch_watchlist_prices, codes_exchanges)
    embed = holdings_embed(held, prices)
    await interaction.followup.send(embed=embed)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("缺少 DISCORD_TOKEN，請設定 .env")
    client.run(TOKEN)
