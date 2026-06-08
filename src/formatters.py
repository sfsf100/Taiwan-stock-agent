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
        limit_up = info.get("limit_up", 0)
        limit_tag = " 🔒漲停" if limit_up > 0 and price >= limit_up else ""
        embed.add_field(
            name=f"{arrow} {name} ({code}){limit_tag}",
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

    # Use API-provided limit prices; fall back to calculation
    limit_up = info.get("limit_up") or calc_limit_prices(prev)[0]
    limit_down = info.get("limit_down") or calc_limit_prices(prev)[1]

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


def recommend_embed(
    code: str,
    info: dict,
    rsi: float | None,
    ma5: float | None,
    ma20: float | None,
    high20: float | None,
    low20: float | None,
) -> discord.Embed:
    name = info.get("name", code)
    price = info.get("close", 0)

    signals = []
    if rsi is not None:
        if rsi < 30:
            signals.append(f"RSI {rsi:.1f} — 超賣區，具反彈機會")
        elif rsi < 50:
            signals.append(f"RSI {rsi:.1f} — 偏弱")
        elif rsi < 70:
            signals.append(f"RSI {rsi:.1f} — 中性偏強")
        else:
            signals.append(f"RSI {rsi:.1f} — 超買，注意獲利了結風險")

    if ma5 is not None and ma20 is not None and price > 0:
        if price > ma5 > ma20:
            signals.append("現價 > 5MA > 20MA，多頭排列強勢")
        elif price < ma5 < ma20:
            signals.append("現價 < 5MA < 20MA，空頭排列弱勢")
        elif price > ma5 and ma5 < ma20:
            signals.append("短線反彈，但 20MA 仍是壓力")
        elif price < ma5 and ma5 > ma20:
            signals.append("跌破 5MA，短線轉弱")

    # Suggested target and stop-loss
    target_price = None
    stop_price = None

    if high20 and high20 > price * 1.01:
        target_price = high20
    elif price > 0:
        target_price = round(price * 1.08, 2)

    if ma20 and ma20 < price * 0.99:
        stop_price = round(ma20 * 0.99, 2)
    elif low20 and low20 < price:
        stop_price = low20
    elif price > 0:
        stop_price = round(price * 0.95, 2)

    embed = discord.Embed(title=f"🔍 技術分析：{name} ({code})", color=0x00bfff)
    embed.add_field(name="現價", value=f"**{price:.2f}**", inline=True)
    if rsi is not None:
        embed.add_field(name="RSI(14)", value=f"{rsi:.1f}", inline=True)
    if ma5 is not None:
        embed.add_field(name="5MA", value=f"{ma5:.2f}", inline=True)
    if ma20 is not None:
        embed.add_field(name="20MA", value=f"{ma20:.2f}", inline=True)
    if high20 is not None:
        embed.add_field(name="20日最高", value=f"{high20:.2f}", inline=True)
    if low20 is not None:
        embed.add_field(name="20日最低", value=f"{low20:.2f}", inline=True)

    if signals:
        embed.add_field(name="📊 技術訊號", value="\n".join(f"• {s}" for s in signals), inline=False)

    suggestion_parts = []
    if target_price:
        pct = (target_price - price) / price * 100
        suggestion_parts.append(f"🎯 目標價：**{target_price:.2f}**（{pct:+.1f}%）")
    if stop_price:
        pct = (stop_price - price) / price * 100
        suggestion_parts.append(f"🛡️ 建議停損：**{stop_price:.2f}**（{pct:+.1f}%）")

    if suggestion_parts:
        embed.add_field(name="建議價位", value="\n".join(suggestion_parts), inline=False)

    embed.set_footer(text="⚠️ 僅供參考，非投資建議，請自行評估風險。")
    return embed


def holdings_embed(holdings: list[dict], prices: dict) -> discord.Embed:
    embed = discord.Embed(title="💼 持倉清單", color=0x9b59b6)
    total_cost = 0.0
    total_value = 0.0
    for h in holdings:
        code = h["stock_code"]
        name = h["stock_name"]
        shares = h["shares"]
        cost = h["cost_price"]
        info = prices.get(code, {})
        price = info.get("close", 0)
        value = price * shares
        invested = cost * shares
        pnl = value - invested
        pct = (pnl / invested * 100) if invested else 0
        arrow = "🔺" if pnl > 0 else ("🔻" if pnl < 0 else "➡️")
        price_str = f"{price:.2f}" if price else "—"
        embed.add_field(
            name=f"{arrow} {name} ({code})",
            value=(
                f"持股：{shares} 股　成本：{cost:.2f}　現價：{price_str}\n"
                f"損益：**{pnl:+.0f}** 元　({pct:+.1f}%)"
            ),
            inline=False,
        )
        total_cost += invested
        total_value += value if price else invested
    total_pnl = total_value - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost else 0
    embed.set_footer(text=f"總損益：{total_pnl:+.0f} 元 ({total_pct:+.1f}%)　總市值：{total_value:,.0f} 元")
    return embed
