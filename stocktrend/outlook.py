"""Plain-language, conditional outlook from the current chart structure.

The score is an engineering measure of directional evidence and distance from
a turning reference. It is not a calibrated probability.
"""

from __future__ import annotations

from datetime import date


def _downside_reference(analysis: dict) -> tuple[int | None, dict, list[dict], int, int | None]:
    """Mirror the uptrend structure score for an established downtrend."""
    close = analysis["last"]["close"]
    pivots = analysis.get("pivots", [])
    highs = [pivot for pivot in pivots if pivot["kind"] == "H"]
    lows = [pivot for pivot in pivots if pivot["kind"] == "L"]
    lower_high = len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"] * .99
    lower_low = len(lows) >= 2 and lows[-1]["price"] < lows[-2]["price"] * .99
    ma50 = analysis["indicators"]["ma50"]
    ma200 = analysis["indicators"]["ma200"]
    below_ma50 = bool(ma50 and close < ma50[-1]["value"])
    ma_bearish = bool(ma50 and ma200 and ma50[-1]["value"] < ma200[-1]["value"])
    parts = [
        {"label": "最近高点更低", "met": lower_high},
        {"label": "最近低点更低", "met": lower_low},
        {"label": "价格低于近 50 期平均价", "met": below_ma50},
        {"label": "近 50 期平均价低于近 200 期", "met": ma_bearish},
    ]
    structure_ceiling = 25 * sum(part["met"] for part in parts) if lower_high or lower_low else 0
    if highs:
        reference = {"price": highs[-1]["price"], "kind": "最近确认高点", "date": highs[-1]["date"]}
    else:
        reference = {"price": analysis["levels"]["resistance"]["price"],
                     "kind": "临时区间高点", "date": None}
    line = analysis["trend"].get("trendline")
    if line and line["touches"] >= 3 and line["to_price"] > 0:
        line_reference = {"price": line["to_price"], "kind": "多次触及的下降趋势线",
                          "date": analysis["last"]["date"]}
        reference = min((reference, line_reference), key=lambda item: item["price"])
    atr = analysis["risk"].get("atr20")
    distance = reference["price"] - close
    cushion = (round(100 * distance / (distance + atr)) if atr is not None and atr > 0 and distance > 0
               else (0 if atr is not None and atr > 0 else None))
    score = min(structure_ceiling, cushion) if cushion is not None else None
    return score, reference, parts, structure_ceiling, cushion


def trend_outlook(analysis: dict) -> dict:
    """Explain the current direction and what would support or weaken it."""
    raw = analysis["trend"]["direction"]
    close = analysis["last"]["close"]
    interval = analysis.get("source", {}).get("interval", "1d")
    horizon = "接下来几周" if interval == "1wk" else "接下来几个交易日"
    max_age = 21 if interval == "1wk" else 7
    stale = (date.today() - date.fromisoformat(analysis["last"]["date"])).days > max_age
    atr = analysis["risk"].get("atr20")
    direction = "unclear"
    reference = None
    parts = []
    ceiling = 0
    cushion = None

    if raw == "上升趋势":
        direction = "up"
        rising = analysis["buy_reference"]
        score = rising["score"]
        reference = rising["turning_level"]
        parts = rising["parts"]
        ceiling = rising["structure_ceiling"]
        cushion = rising["cushion_score"]
        price = reference["price"]
        touched = close <= price
        current = "上涨走势正在转弱" if touched else "目前仍偏上涨"
        why = ("最近的高点和低点一波比一波高，但价格已碰到下方关键价。" if touched
               else "最近的高点和低点一波比一波高。")
        if touched:
            expected = f"{horizon}先留意震荡或回落，原来的上涨需要重新确认。"
        elif atr and close - price < atr:
            expected = f"{horizon}仍可能向上，但已经靠近关键价，走势容易反复。"
        else:
            expected = f"{horizon}可先按上涨可能延续观察，同时留意回落。"
        watch = f"重点看 {price:.2f} 附近"
        holds = f"若价格继续守在 {price:.2f} 上方，上涨结构仍有依据。"
        breaks = f"若收盘跌到 {price:.2f} 下方，先重新判断，不能直接当作已进入跌势。"
        summary = f"{current}。{watch}；守住时原来的走势可能继续，失守则要重新判断。"
    elif raw == "下降趋势":
        direction = "down"
        score, reference, parts, ceiling, cushion = _downside_reference(analysis)
        price = reference["price"]
        touched = close >= price
        current = "下跌走势正在转弱" if touched else "目前仍偏下跌"
        why = ("最近的高点和低点一波比一波低，但价格已回到上方关键价。" if touched
               else "最近的高点和低点一波比一波低。")
        if touched:
            expected = f"{horizon}可能先反弹或横盘，原来的下跌需要重新确认。"
        elif atr and price - close < atr:
            expected = f"{horizon}仍可能偏弱，但已经靠近关键价，反弹和反复的可能性增加。"
        else:
            expected = f"{horizon}可先按偏弱走势可能延续观察，同时留意反弹。"
        watch = f"重点看 {price:.2f} 附近"
        holds = f"若价格仍在 {price:.2f} 下方，下跌结构仍有依据。"
        breaks = f"若收盘升到 {price:.2f} 上方，先重新判断，不能直接当作已进入涨势。"
        summary = f"{current}。{watch}；未站回时弱势可能继续，站回则要重新判断。"
    else:
        rising = analysis["buy_reference"]
        up_ceiling = 25 * rising["conditions_met"]
        up_cushion = rising["cushion_score"]
        up_clue = min(up_ceiling, up_cushion) if up_cushion is not None else 0
        _, down_reference, down_parts, _, down_cushion = _downside_reference(analysis)
        down_ceiling = 25 * sum(part["met"] for part in down_parts)
        down_clue = min(down_ceiling, down_cushion) if down_cushion is not None else 0
        lower = analysis["levels"]["support"]["price"]
        upper = analysis["levels"]["resistance"]["price"]
        upper_trigger = upper * 1.03
        lower_trigger = lower * .97
        watch = f"先看下方 {lower:.2f}、上方 {upper:.2f}"
        holds = f"若收盘高于 {upper_trigger:.2f} 且成交量增加，上涨线索会更强。"
        breaks = f"若收盘低于 {lower_trigger:.2f}，下跌线索会更强。"
        ma50 = analysis["indicators"]["ma50"]
        ma200 = analysis["indicators"]["ma200"]
        if up_clue > down_clue:
            direction = "up_lean"
            score = up_clue
            reference = rising["turning_level"]
            parts = rising["parts"]
            ceiling, cushion = up_ceiling, up_cushion
            averages_agree = bool(ma50 and ma200 and close > ma50[-1]["value"] > ma200[-1]["value"])
            if averages_agree:
                current = "整体偏上涨，最近在横盘" if raw == "区间或过渡" else "整体偏上涨，波段证据还不够"
                why = "价格高于近 50 期平均价，近 50 期平均价又高于近 200 期；"
                why += ("但最近的高点和低点没有一起抬高。" if raw == "区间或过渡" else
                        "但可确认的高点和低点还不够。")
            else:
                current = "有上涨迹象，趋势尚未确认"
                why = "有一些偏上的图形线索，但高点和低点还没有一起抬高。"
            expected = (f"{horizon}可能先来回波动；若向上走出当前范围，偏上涨判断会更有依据。"
                        if raw == "区间或过渡" else "先等更多价格变化，才能判断上涨是否会继续。")
        elif down_clue > up_clue:
            direction = "down_lean"
            score = down_clue
            reference = down_reference
            parts = down_parts
            ceiling, cushion = down_ceiling, down_cushion
            averages_agree = bool(ma50 and ma200 and close < ma50[-1]["value"] < ma200[-1]["value"])
            if averages_agree:
                current = "整体偏下跌，最近在横盘" if raw == "区间或过渡" else "整体偏下跌，波段证据还不够"
                why = "价格低于近 50 期平均价，近 50 期平均价又低于近 200 期；"
                why += ("但最近的高点和低点没有一起降低。" if raw == "区间或过渡" else
                        "但可确认的高点和低点还不够。")
            else:
                current = "有下跌迹象，趋势尚未确认"
                why = "有一些偏下的图形线索，但高点和低点还没有一起降低。"
            expected = (f"{horizon}可能先来回波动；若向下走出当前范围，偏下跌判断会更有依据。"
                        if raw == "区间或过渡" else "先等更多价格变化，才能判断下跌是否会继续。")
        else:
            score = 0
            current = "现在还看不出明确方向" if raw == "区间或过渡" else "目前数据还不够判断趋势"
            why = ("上涨和下跌的图形线索差不多，暂时不押一个方向。"
                   if raw == "区间或过渡" else "还没有足够的已确认高点和低点。")
            expected = f"{horizon}先按来回波动观察，等价格走出目前的上下范围再判断。"
        summary = f"{current}。{watch}；走出这个范围后再判断后续方向。"

    if stale:
        direction = "stale"
        score = None
        current = "行情未更新，暂不判断当前趋势"
        why = f"最后一条价格记录是 {analysis['last']['date']}。"
        expected = "先更新价格，再看后续走势。"
        watch = "等待新的价格数据"
        holds = ""
        breaks = ""
        reference = None
        parts = []
        summary = f"{why}先更新行情，再判断趋势。"
    elif atr is None or atr <= 0:
        score = None
        why += " 当前价格记录不足，无法衡量普通波动幅度。"

    if direction == "stale":
        confidence_meaning = "行情尚未更新，请先补充最新价格。"
    elif score is None:
        confidence_meaning = "波动幅度数据不足，暂时无法计算把握分。"
    elif direction == "unclear":
        confidence_meaning = "0 分表示目前没有明确的单边趋势可延续，不代表一定下跌。"
    elif direction in {"up_lean", "down_lean"}:
        confidence_meaning = "这是偏向该方向的图形线索分，近期趋势尚未确认；不是未来概率。"
    else:
        confidence_meaning = "当前图形对这一方向继续发展的支持程度，不是未来涨跌概率。"

    return {
        "direction": direction, "current": current, "confidence_score": score,
        "confidence_meaning": confidence_meaning,
        "why": why, "expected": expected, "watch": watch,
        "if_holds": holds, "if_breaks": breaks, "summary": summary,
        "reference": reference, "parts": parts, "structure_ceiling": ceiling,
        "cushion_score": cushion, "as_of": analysis["last"]["date"],
        "method": "确认波峰波谷决定趋势；四项波段/均线条件决定上限；离最近可信反转位越近，ATR 缓冲分越低。波段未确认时只输出较强一侧的线索分；两侧相同则为0。",
        "book_chapters": [3, 13, 14, 36],
    }
