"""A plain-language, conditional trend scenario from the latest visible bars.

This is a directional hypothesis for planning, not a calibrated probability or
an expected return. The structural score does not vote on the direction.
"""

from __future__ import annotations


def trend_forecast(analysis: dict) -> dict:
    interval = analysis.get("source", {}).get("interval", "1d")
    horizon = 8 if interval == "1wk" else 20
    horizon_label = "未来 8 周" if interval == "1wk" else "未来 20 个交易日"
    bars = analysis["bars"]
    outlook = analysis["trend_outlook"]
    ma50 = analysis["indicators"]["ma50"]
    as_of = analysis["last"]["date"]
    unavailable = outlook["direction"] == "stale" or len(bars) <= horizon or not ma50
    if unavailable:
        return {
            "direction": "unavailable", "label": "等待更新数据", "horizon_bars": horizon,
            "horizon_label": horizon_label, "summary": "价格过期或记录不足，暂不预测后续走势。",
            "reason": "先补齐最新价格和 50 期均价，再判断方向。", "watch_price": None,
            "watch_label": None, "reconsider_if": "", "as_of": as_of,
            "validation": "历史对照未显示预测优势；不表示未来方向的概率。",
        }

    close = analysis["last"]["close"]
    momentum = close / bars[-horizon - 1]["close"] - 1
    above_ma = close > ma50[-1]["value"]
    below_ma = close < ma50[-1]["value"]
    current = outlook["direction"]
    turning_price = (outlook.get("reference") or {}).get("price")
    up_evidence = current in {"up", "up_lean"} and above_ma and momentum > 0
    down_evidence = current in {"down", "down_lean"} and below_ma and momentum < 0
    if up_evidence:
        direction = "up" if current == "up" and turning_price is not None and close > turning_price else "up_range"
        label = "偏向继续上涨" if direction == "up" else "偏强震荡"
        reason = "当前图形偏上，现价高于 50 期均价，最近一段价格也在上涨。"
        level = analysis["levels"]["resistance"]["price"]
        watch_price = round(level, 2) if level > close else None
        watch_label = "上方观察位" if watch_price is not None else None
        summary = (f"{horizon_label}，基准情景是{label}；仍可能出现回落。"
                   + (f"先看 {watch_price:.2f} 附近能否突破。" if watch_price is not None else "继续观察新高能否保持。"))
        reconsider_if = outlook["if_breaks"]
    elif down_evidence:
        direction = "down" if current == "down" and turning_price is not None and close < turning_price else "down_range"
        label = "偏向继续下跌" if direction == "down" else "偏弱震荡"
        reason = "当前图形偏下，现价低于 50 期均价，最近一段价格也在下跌。"
        level = analysis["levels"]["support"]["price"]
        watch_price = round(level, 2) if level < close else None
        watch_label = "下方观察位" if watch_price is not None else None
        summary = (f"{horizon_label}，基准情景是{label}；中途仍可能反弹。"
                   + (f"先看 {watch_price:.2f} 附近能否守住。" if watch_price is not None else "留意是否再创新低。"))
        reconsider_if = outlook["if_breaks"] if current == "down" else outlook["if_holds"]
    else:
        direction = "range"
        label = "先按震荡观察"
        reason = "当前图形、50 期均价与最近一段涨跌没有给出一致方向。"
        watch_price = None
        watch_label = None
        summary = f"{horizon_label}，基准情景是反复震荡；先等价格走出当前范围。"
        reconsider_if = outlook["if_holds"] + " " + outlook["if_breaks"]
    return {
        "direction": direction, "label": label, "horizon_bars": horizon,
        "horizon_label": horizon_label, "summary": summary, "reason": reason,
        "watch_price": watch_price, "watch_label": watch_label,
        "reconsider_if": reconsider_if.strip(), "as_of": as_of,
        "validation": "这是图形情景，不是概率；VOO、QQQM、NVDA、MU 的历史对照未显示它优于简单基准。",
    }
