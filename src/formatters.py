import discord
from .twse_api import calc_limit_prices
from .indicators import get_rsi, get_ma5


def stock_list_embed(stocks: list[dict], prices: dict) -> discord.Embed:
    embed = discord.Embed(title="📋 監控股票清單", color=0x00bfff)
    if not stocks:
        embed.description = "清單為空，請用 `/watch` 新增股票"
        return embed
    for s in stocks:
        code = s["stock_code"]
        name = s["stock_name"]
        info = prices.get(code, {})
        price = info.get("close", 0)
        prev = info.get("prev_close", price)
        change = price - prev
        pct = (change / prev * 100) if prev else 0
        arrow = "🔺" if change > 0 else ("🔻" if change < 0 else "➡️")
        embed.add_field(
            name=f"{arrow} {name} ({code})",
            value=f"現價：**{price:.2f}**　漲跌：{change:+.2f} ({pct:+.2f}%)",
            inline=False,
        )
    return embed


def stock_status_embed(code: str, info: dict) -> discord.Embed:
    name = info.get("name", code)
    price = info.get("close", 0)
    prev = info.get("prev_close", price)
    change = price - prev
    pct = (change / prev * 100) if prev else 0
    limit_up, limit_down = calc_limit_prices(prev)
    rsi = get_rsi(code)
    ma5 = get_ma5(code)

    color = 0xff4444 if change > 0 else (0x44cc44 if change < 0 else 0x888888)
    embed = discord.Embed(title=f"📈 {name} ({code})", color=color)
    embed.add_field(name="現價", value=f"**{price:.2f}**", inline=True)
    embed.add_field(name="漲跌", value=f"{change:+.2f} ({pct:+.2f}%)", inline=True)
    embed.add_field(name="開盤", value=f"{info.get('open', 0):.2f}", inline=True)
    embed.add_field(name="最高", value=f"{info.get('high', 0):.2f}", inline=True)
    embed.add_field(name="最低", value=f"{info.get('low', 0):.2f}", inline=True)
    embed.add_field(name="成交量", value=f"{info.get('volume', 0):,}", inline=True)
    embed.add_field(name="漲停價", value=f"{limit_up:.2f}", inline=True)
    embed.add_field(name="跌停價", value=f"{limit_down:.2f}", inline=True)
    if rsi is not None:
        embed.add_field(name="RSI(14)", value=f"{rsi:.1f}", inline=True)
    if ma5 is not None:
        embed.add_field(name="5MA", value=f"{ma5:.2f}", inline=True)
    return embed


def daily_report_embed(title: str, stocks: list[dict], prices: dict) -> discord.Embed:
    embed = discord.Embed(title=title, color=0xffa500)
    for s in stocks:
        code = s["stock_code"]
        name = s["stock_name"]
        info = prices.get(code, {})
        price = info.get("close", 0)
        prev = info.get("prev_close", price)
        change = price - prev
        pct = (change / prev * 100) if prev else 0
        arrow = "🔺" if change > 0 else ("🔻" if change < 0 else "➡️")
        embed.add_field(
            name=f"{arrow} {name} ({code})",
            value=f"{price:.2f}　{change:+.2f} ({pct:+.2f}%)",
            inline=False,
        )
    return embed
