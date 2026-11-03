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


def _lots_str(v: int | None) -> str:
    """籌碼數值顯示：負數紅（賣超）、正數（買超），None → 沒有資料。"""
    if v is None:
        return "—"
    return f"{v:+,}"


def _chip_summary(chip: dict, streaks: dict, drawdown_pct: float | None, rsi: float | None) -> str:
    """根據籌碼面＋跌深＋RSI 產生一句「現在該不該考慮買」的判讀。"""
    notes: list[str] = []
    foreign = chip.get("foreign_net")
    total = chip.get("total_net")

    if total is not None and foreign is not None:
        sell_streak = streaks.get("foreign_sell_streak", 0)
        if total < 0 and sell_streak >= 2:
            notes.append(f"🚫 外資連續 {sell_streak} 日賣超，賣壓尚未止息，**接刀風險高**")
        elif streaks.get("foreign_turned_buy"):
            notes.append(f"✅ 外資由賣轉買（首日轉正），可開始留意，但建議等量價確認後再分批")
        elif total > 0:
            notes.append("✅ 法人買超，籌碼面相對正向")
        else:
            notes.append("⚠️ 法人賣超中，短線趨勢仍偏弱")

    if drawdown_pct is not None:
        if drawdown_pct <= -20:
            notes.append(f"📉 自 20 日高點已回撤 **{abs(drawdown_pct):.1f}%**，進入急跌深區；跌深≠止跌")
        elif drawdown_pct <= -10:
            notes.append(f"📉 自 20 日高點回撤 {abs(drawdown_pct):.1f}%，留意止跌訊號")

    if drawdown_pct is not None and drawdown_pct <= -10 and (rsi or 50) < 40:
        notes.append("💡 跌深＋超賣並存：若法人止賣、量縮不再破底，才是較安全的分批時機")

    return "\n".join(notes) if notes else "資料不足，暫無判讀"


def chips_embed(
    code: str,
    chip: dict,
    history: list[dict],
    streaks: dict,
    rsi: float | None = None,
    price: float | None = None,
    high20: float | None = None,
) -> discord.Embed:
    name = chip.get("name", code)
    drawdown = None
    if price and high20:
        drawdown = (price - high20) / high20 * 100

    color = 0x3498db if (chip.get("total_net") or 0) >= 0 else 0xe74c3c
    embed = discord.Embed(title=f"🧮 籌碼面：{name} ({code})", color=color)
    date_str = chip.get("date") or "未知"
    embed.description = f"資料日期：{date_str}"

    embed.add_field(name="外資", value=_lots_str(chip.get("foreign_net")), inline=True)
    embed.add_field(name="投信", value=_lots_str(chip.get("trust_net")), inline=True)
    embed.add_field(name="自營商", value=_lots_str(chip.get("dealer_net")), inline=True)
    embed.add_field(name="三大法人合計", value=_lots_str(chip.get("total_net")), inline=True)
    embed.add_field(name="融資增減", value=_lots_str(chip.get("margin_change")), inline=True)
    if price:
        embed.add_field(name="現價", value=f"{price:.2f}", inline=True)

    if history:
        recent = history[:5]
        lines = []
        for h in recent:
            lines.append(f"{h['data_date']}　外資 {_lots_str(h.get('foreign_net'))}　投信 {_lots_str(h.get('trust_net'))}")
        embed.add_field(name="近期法人動向（新→舊）", value="\n".join(lines), inline=False)

    summary = _chip_summary(chip, streaks, drawdown, rsi)
    embed.add_field(name="🧭 買盤時機判讀", value=summary, inline=False)

    if rsi is not None:
        embed.add_field(name="RSI(14)", value=f"{rsi:.1f}", inline=True)
    if drawdown is not None:
        embed.add_field(name="距20日高點", value=f"{drawdown:+.1f}%", inline=True)

    embed.set_footer(text="⚠️ 籌碼資料由證交所/櫃買中心公開資訊彙整，僅供參考，非投資建議。")
    return embed


def daily_chip_embed(title: str, entries: list[dict]) -> discord.Embed:
    """每日籌碼速報：監控清單整體法人動向一覽。

    entries: [{"code", "chip", "streaks"}]
    """
    embed = discord.Embed(title=title, color=0x2c3e50)
    if not entries:
        embed.description = "今日尚無法人資料（可能未發布或非交易日）"
        return embed
    data_date = entries[0].get("chip", {}).get("date")
    if data_date:
        embed.description = f"資料日期：{data_date}"
    for e in entries:
        chip = e["chip"]
        streaks = e.get("streaks", {})
        code = e.get("code", "")
        name = chip.get("name", code)
        n_sell = streaks.get("foreign_sell_streak", 0) if streaks else 0
        tag = ""
        if n_sell >= 3:
            tag = f" 🔴外資連賣 {n_sell} 日"
        elif streaks.get("foreign_turned_buy") if streaks else False:
            tag = " 🟢外資轉買"
        total = chip.get("total_net")
        embed.add_field(
            name=f"{name} ({code}){tag}",
            value=(
                f"外資 {_lots_str(chip.get('foreign_net'))}　"
                f"投信 {_lots_str(chip.get('trust_net'))}　"
                f"合計 {_lots_str(total)}　"
                f"融資 {_lots_str(chip.get('margin_change'))}"
            ),
            inline=False,
        )
    embed.set_footer(text="單位：張　⚠️ 僅供參考，非投資建議")
    return embed
