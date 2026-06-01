import os
import asyncio
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
from datetime import datetime, time as dtime

from src import database as db
from src.twse_api import get_stock_info, validate_stock, get_realtime_price, is_trading_time
from src.alert_engine import check_alerts, check_technical_alerts
from src.formatters import stock_list_embed, stock_status_embed, daily_report_embed
from src.indicators import preload

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
GUILD_ID = 1511001003716116510

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ── 定時輪詢（30 秒）────────────────────────────────────────
@tasks.loop(seconds=30)
async def price_monitor():
    if not is_trading_time():
        return
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        return

    watchlist = db.get_watchlist()
    for s in watchlist:
        code = s["stock_code"]
        name = s["stock_name"]
        info = get_stock_info(code)
        if not info:
            continue
        price = info["close"]
        prev = info["prev_close"]

        alerts = check_alerts(code, name, price, prev)
        for alert in alerts:
            await channel.send(alert["message"], allowed_mentions=discord.AllowedMentions(everyone=True))

        tech_alerts = check_technical_alerts(code, name)
        for alert in tech_alerts:
            await channel.send(alert["message"], allowed_mentions=discord.AllowedMentions(everyone=True))


async def send_daily_report(title: str):
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        return
    watchlist = db.get_watchlist()
    if not watchlist:
        return
    prices = {}
    for s in watchlist:
        info = get_stock_info(s["stock_code"])
        if info:
            prices[s["stock_code"]] = info
    embed = daily_report_embed(title, watchlist, prices)
    await channel.send(embed=embed)


# ── 定時報告 ─────────────────────────────────────────────
@tasks.loop(seconds=60)
async def scheduled_reports():
    now = datetime.now()
    if now.weekday() >= 5:
        return
    t = now.time()
    if dtime(9, 5) <= t <= dtime(9, 6):
        await send_daily_report("🌅 09:05 開盤報告")
    elif dtime(12, 0) <= t <= dtime(12, 1):
        await send_daily_report("☀️ 12:00 盤中報告")
    elif dtime(13, 35) <= t <= dtime(13, 36):
        await send_daily_report("🌆 13:35 收盤報告")


@client.event
async def on_ready():
    try:
        db.init_db()
        db.clear_today_alerts()
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

        print(f"Bot 已啟動：{client.user}，監控 {len(watchlist)} 檔股票")
        channel = client.get_channel(CHANNEL_ID)
        if channel:
            await channel.send(f"@everyone ✅ 台股監控 Bot 已上線！監控中：{len(watchlist)} 檔股票", allowed_mentions=discord.AllowedMentions(everyone=True))
    except Exception as e:
        import traceback
        print(f"on_ready 錯誤：{e}\n{traceback.format_exc()}")


# ── Slash Commands ────────────────────────────────────────

@tree.command(name="ping", description="測試 Bot 是否正常運作")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong！Bot 運作正常。")


@tree.command(name="watch", description="新增監控股票")
@app_commands.describe(codes="股票代碼，空格分隔，例如：2330 2454 0050")
async def watch(interaction: discord.Interaction, codes: str):
    await interaction.response.defer()
    results = []
    for code in codes.split():
        code = code.strip()
        if db.is_watching(code):
            results.append(f"ℹ️ {code} 已在監控清單")
            continue
        name = await asyncio.get_running_loop().run_in_executor(None, validate_stock, code)
        if name:
            db.add_stock(code, name)
            results.append(f"✅ 已新增：{name} ({code})")
        else:
            results.append(f"❌ 找不到代碼：{code}")
    await interaction.followup.send("\n".join(results))


@tree.command(name="unwatch", description="移除監控股票")
@app_commands.describe(code="股票代碼，例如 2330")
async def unwatch(interaction: discord.Interaction, code: str):
    if db.is_watching(code):
        info = get_stock_info(code)
        name = info["name"] if info else code
        db.remove_stock(code)
        await interaction.response.send_message(f"✅ 已移除監控：{name} ({code})")
    else:
        await interaction.response.send_message(f"ℹ️ {code} 不在監控清單中")


@tree.command(name="list", description="顯示監控清單與即時價位")
async def list_stocks(interaction: discord.Interaction):
    await interaction.response.defer()
    watchlist = db.get_watchlist()
    prices = {}
    for s in watchlist:
        info = get_stock_info(s["stock_code"])
        if info:
            prices[s["stock_code"]] = info
    embed = stock_list_embed(watchlist, prices)
    await interaction.followup.send(embed=embed)


@tree.command(name="status", description="查詢單檔股票詳細資訊")
@app_commands.describe(code="股票代碼，例如 2330")
async def status(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    info = get_stock_info(code)
    if not info:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")
        return
    embed = stock_status_embed(code, info)
    await interaction.followup.send(embed=embed)


@tree.command(name="target", description="設定目標價警報")
@app_commands.describe(code="股票代碼", price="目標價格")
async def target(interaction: discord.Interaction, code: str, price: float):
    info = get_stock_info(code)
    name = info["name"] if info else code
    db.add_target(code, price)
    await interaction.response.send_message(f"✅ 已設定 **{name} ({code})** 目標價：**{price:.2f}** 元")


@tree.command(name="price", description="快速查詢台股現價")
@app_commands.describe(code="股票代碼，例如 2330")
async def price_cmd(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    p = await asyncio.get_running_loop().run_in_executor(None, get_realtime_price, code)
    if p:
        await interaction.followup.send(f"📈 **{code}** 現價：**{p:.2f}**")
    else:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")


client.run(TOKEN)
