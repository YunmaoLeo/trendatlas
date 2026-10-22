"""Deterministic 0-100 confidence in the *current uptrend structure*.

This number is a transparent chart-state index, not an estimated probability of
future gains. No historical outcomes, fitted coefficients, or buy thresholds
enter the calculation.
"""

from __future__ import annotations

from datetime import date


def buy_reference(analysis: dict) -> dict:
    """Measure swing/MA agreement and the volatility-scaled reversal cushion.

    Four binary tests set a ceiling of 0, 25, 50, 75, or 100. The distance from
    the closest credible turning level is converted to 0..100 with
    ``100 * distance / (distance + ATR20)``. The score is the lower of those
    two values: weakness in either structural evidence or price cushion cannot
    be hidden by strength in the other.
    """
    close = analysis["last"]["close"]
    pivots = analysis.get("pivots", [])
    highs = [pivot for pivot in pivots if pivot["kind"] == "H"]
    lows = [pivot for pivot in pivots if pivot["kind"] == "L"]
    hh = len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"] * 1.01
    hl = len(lows) >= 2 and lows[-1]["price"] > lows[-2]["price"] * 1.01
    ma50 = analysis["indicators"]["ma50"]
    ma200 = analysis["indicators"]["ma200"]
    above_ma50 = bool(ma50 and close > ma50[-1]["value"])
    ma_aligned = bool(ma50 and ma200 and ma50[-1]["value"] > ma200[-1]["value"])
    checks = [
        {"key": "higher_high", "label": "波峰抬高", "met": hh,
         "reason": (f"最近两处确认波峰 {highs[-2]['price']:.2f} → {highs[-1]['price']:.2f}，"
                    "需抬高超过 1%" if len(highs) >= 2 else "确认波峰不足两处")},
        {"key": "higher_low", "label": "波谷抬高", "met": hl,
         "reason": (f"最近两处确认波谷 {lows[-2]['price']:.2f} → {lows[-1]['price']:.2f}，"
                    "需抬高超过 1%" if len(lows) >= 2 else "确认波谷不足两处")},
        {"key": "above_ma50", "label": "现价高于 50 期线", "met": above_ma50,
         "reason": f"现价 {close:.2f}；50 期线 {ma50[-1]['value']:.2f}" if ma50 else "50 期均线尚不可用"},
        {"key": "ma_alignment", "label": "50 期线高于 200 期线", "met": ma_aligned,
         "reason": (f"50 期线 {ma50[-1]['value']:.2f}；200 期线 {ma200[-1]['value']:.2f}"
                    if ma50 and ma200 else "200 期均线尚不可用")},
    ]
    met_count = sum(item["met"] for item in checks)
    # MA alignment alone cannot establish that recent swing prices are rising.
    structure_ceiling = 25 * met_count if hh or hl else 0

    turning_levels = []
    if lows:
        latest = lows[-1]
        turning_levels.append({"price": latest["price"], "kind": "最近确认波谷",
                               "date": latest["date"]})
    else:
        support = analysis["levels"]["support"]
        turning_levels.append({"price": support["price"], "kind": "临时区间低点",
                               "date": None})
    line = analysis["trend"].get("trendline")
    line_note = None
    if line and analysis["trend"]["direction"] == "上升趋势":
        if line["touches"] >= 3 and line["to_price"] > 0:
            turning_levels.append({"price": line["to_price"], "kind": "至少三次触及的上升趋势线",
                                   "date": analysis["last"]["date"]})
        else:
            line_note = "上升线仅由两个转折点画出，尚属试验线；不作决定分数的转折位。"
    turning_level = max(turning_levels, key=lambda level: level["price"])
    distance = close - turning_level["price"]
    atr = analysis["risk"].get("atr20")
    if atr is not None and atr > 0 and distance > 0:
        cushion = 100 * distance / (distance + atr)
        score = round(min(structure_ceiling, cushion))
    else:
        cushion = 0.0 if atr is not None and atr > 0 else None
        score = 0 if atr is not None and atr > 0 else None

    interval = analysis.get("source", {}).get("interval", "1d")
    max_age = 21 if interval == "1wk" else 7
    age = (date.today() - date.fromisoformat(analysis["last"]["date"])).days
    if age > max_age:
        score = None
        label = "行情过期，无法评估当前趋势"
    elif atr is None or atr <= 0:
        label = "波动幅度不可用，无法计算距离分"
    elif distance <= 0:
        label = "现价已触及或跌破转折参照位，需重判趋势"
    elif not (hh or hl):
        label = "近期波段未呈现上升结构"
    elif analysis["trend"]["direction"] == "上升趋势":
        label = "波峰波谷仍抬高；观察下方转折位"
    else:
        label = "上升证据不完整，处于过渡阶段"
    return {
        "score": score, "label": label, "as_of": analysis["last"]["date"],
        "parts": checks, "conditions_met": met_count, "conditions_total": len(checks),
        "structure_ceiling": structure_ceiling,
        "cushion_score": round(cushion) if cushion is not None else None,
        "turning_level": turning_level, "distance_pct": round(distance / close * 100, 2),
        "distance_atr": round(distance / atr, 2) if atr is not None and atr > 0 else None,
        "atr20": atr, "line_note": line_note,
        "method": "score=min(25×已满足条件数, 100×max(现价-转折位,0)/(max(现价-转折位,0)+ATR20))；无上升波段证据时为0",
        "note": "这是上升趋势结构的规则化参考分，不是上涨概率、未来收益预测或买入指令。",
    }
