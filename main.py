import os
import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot 已啟動：{client.user}")
    channel = client.get_channel(CHANNEL_ID)
    if channel:
        await channel.send("✅ 台股監控 Bot 已上線！輸入 `/ping` 測試連線。")


@tree.command(name="ping", description="測試 Bot 是否正常運作")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong！Bot 運作正常。")


@tree.command(name="price", description="快速查詢台股現價（測試用）")
@app_commands.describe(code="股票代碼，例如 2330")
async def price(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    import yfinance as yf
    ticker = yf.Ticker(f"{code}.TW")
    info = ticker.fast_info
    try:
        last_price = info.last_price
        await interaction.followup.send(f"📈 **{code}** 現價：**{last_price:.2f}**")
    except Exception:
        await interaction.followup.send(f"❌ 查無股票代碼：{code}")


client.run(TOKEN)
