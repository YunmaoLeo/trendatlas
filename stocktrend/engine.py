"""Deterministic interpretation of Edwards & Magee chart rules.

Book-specified percentages are kept distinct from detector engineering choices in
KNOWLEDGE.md. All pivots require bars to their right, so the last three bars can
never be labeled confirmed extrema. Results describe conditions, not forecasts.
"""

from __future__ import annotations

from datetime import date
from math import floor
from statistics import mean

from .data import validate_bars
from .score import buy_reference

BREAKOUT = 0.03  # Chapters 6, 7, 8, 14: roughly 3% closing penetration
UP_VOLUME = 1.5  # Engineering threshold for the book's qualitative "明显放量"
PIVOT_RADIUS = 3  # Engineering threshold to define a confirmed local turn
STOP_BUFFER = 0.06  # Chapter 28, section 28.4.1


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0


def _age_days(bars: list[dict], i: int) -> int:
    return (date.fromisoformat(bars[-1]["date"]) - date.fromisoformat(bars[i]["date"])).days


def _vol_ratio(bars: list[dict], i: int) -> float | None:
    sample = [bar["volume"] for bar in bars[max(0, i - 20):i] if bar["volume"] > 0]
    return bars[i]["volume"] / mean(sample) if len(sample) >= 5 and bars[i]["volume"] > 0 else None


def _pivots(bars: list[dict]) -> list[dict]:
    found = []
    r = PIVOT_RADIUS
    for i in range(r, len(bars) - r):
        window = bars[i - r:i + r + 1]
        is_high = bars[i]["high"] == max(item["high"] for item in window) and sum(item["high"] == bars[i]["high"] for item in window) == 1
        is_low = bars[i]["low"] == min(item["low"] for item in window) and sum(item["low"] == bars[i]["low"] for item in window) == 1
        if is_high and is_low:
            continue  # An outside bar has ambiguous high/low ordering on daily OHLC.
        if is_high or is_low:
            kind, value = ("H", bars[i]["high"]) if is_high else ("L", bars[i]["low"])
            found.append({"kind": kind, "i": i, "date": bars[i]["date"], "price": value, "volume": bars[i]["volume"]})
    found.sort(key=lambda item: item["i"])
    alternating = []
    for item in found:
        if alternating and alternating[-1]["kind"] == item["kind"]:
            last = alternating[-1]
            if (item["kind"] == "H" and item["price"] > last["price"]) or (item["kind"] == "L" and item["price"] < last["price"]):
                alternating[-1] = item
        else:
            alternating.append(item)
    return alternating


def _moving_average(bars: list[dict], period: int) -> list[dict]:
    result = []
    total = 0.0
    for i, bar in enumerate(bars):
        total += bar["close"]
        if i >= period:
            total -= bars[i - period]["close"]
        if i >= period - 1:
            result.append({"date": bar["date"], "value": _round(total / period)})
    return result


def _trend(bars: list[dict], pivots: list[dict]) -> dict:
    highs = [p for p in pivots if p["kind"] == "H"]
    lows = [p for p in pivots if p["kind"] == "L"]
    direction = "未确认"
    evidence = []
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1]["price"] > highs[-2]["price"] * 1.01
        hl = lows[-1]["price"] > lows[-2]["price"] * 1.01
        lh = highs[-1]["price"] < highs[-2]["price"] * 0.99
        ll = lows[-1]["price"] < lows[-2]["price"] * 0.99
        if hh and hl:
            direction = "上升趋势"
            evidence = ["最近两组确认波峰抬高", "最近两组确认波谷抬高"]
        elif lh and ll:
            direction = "下降趋势"
            evidence = ["最近两组确认波峰降低", "最近两组确认波谷降低"]
        else:
            direction = "区间或过渡"
            evidence = ["波峰与波谷未同向变化"]
    line = None
    anchors = lows[-2:] if direction == "上升趋势" else highs[-2:] if direction == "下降趋势" else []
    if len(anchors) == 2 and anchors[1]["i"] > anchors[0]["i"]:
        slope = (anchors[1]["price"] - anchors[0]["price"]) / (anchors[1]["i"] - anchors[0]["i"])
        now = anchors[1]["price"] + slope * (len(bars) - 1 - anchors[1]["i"])
        broken = bars[-1]["close"] < now * (1 - BREAKOUT) if direction == "上升趋势" else bars[-1]["close"] > now * (1 + BREAKOUT)
        line = {"from": anchors[0]["date"], "from_price": _round(anchors[0]["price"]),
                "to": bars[-1]["date"], "to_price": _round(now), "broken": broken,
                "touches": sum(1 for p in (lows if direction == "上升趋势" else highs)
                               if p["i"] >= anchors[0]["i"] and
                               (projected := anchors[0]["price"] + slope * (p["i"] - anchors[0]["i"])) > 0 and
                               abs(p["price"] / projected - 1) <= .02)}
        line["quality"] = "已验证" if line["touches"] >= 3 else "两点试验线"
        if broken:
            evidence.append(f"最新收盘价已越过{line['quality']} 3%")
    return {"direction": direction, "evidence": evidence, "trendline": line, "book_chapters": [3, 14]}


def _levels(bars: list[dict], pivots: list[dict]) -> dict:
    close = bars[-1]["close"]
    result = {}
    for kind, name in (("L", "support"), ("H", "resistance")):
        candidates = [p for p in pivots[-30:] if p["kind"] == kind]
        groups = []
        for p in candidates:
            group = next((g for g in groups if abs(p["price"] / g["price"] - 1) <= .02), None)
            if group:
                group["points"].append(p)
                group["price"] = mean(item["price"] for item in group["points"])
            else:
                groups.append({"price": p["price"], "points": [p]})
        valid = [g for g in groups if g["price"] < close] if kind == "L" else [g for g in groups if g["price"] > close]
        if valid:
            best = max(valid, key=lambda g: g["price"]) if kind == "L" else min(valid, key=lambda g: g["price"])
            result[name] = {"price": _round(best["price"]), "touches": len(best["points"]), "method": "确认波段聚类 ±2%"}
        else:
            window = bars[-30:]
            price = min(b["low"] for b in window) if kind == "L" else max(b["high"] for b in window)
            result[name] = {"price": _round(price), "touches": 1, "method": "30 根 K 线区间极值"}
    return result


def _pattern(name: str, family: str, direction: str, status: str, start: dict, end: dict,
             boundary: float, target: float | None, evidence: list[str], warnings: list[str], chapters: list[int]) -> dict:
    return {"name": name, "family": family, "direction": direction, "status": status,
            "start_date": start["date"], "end_date": end["date"],
            "trigger": _round(boundary), "measured_target": _round(target),
            "evidence": evidence, "warnings": warnings, "book_chapters": chapters}


def _status(bars: list[dict], end_i: int, boundary: float, direction: str,
            require_volume: bool, boundary_at=None) -> tuple[str, list[str], int | None]:
    warnings = []
    # The final extremum cannot be known until three bars to its right exist.
    for i in range(end_i + PIVOT_RADIUS + 1, len(bars)):
        line = boundary_at(i) if boundary_at else boundary
        crossed = bars[i]["close"] >= line * (1 + BREAKOUT) if direction == "up" else bars[i]["close"] <= line * (1 - BREAKOUT)
        if crossed:
            ratio = _vol_ratio(bars, i)
            if require_volume and (ratio is None or ratio < UP_VOLUME):
                message = "向上突破尚缺少成交量确认（工程阈值：20 期均量的 1.5 倍）"
                if message not in warnings:
                    warnings.append(message)
                continue
            latest_line = boundary_at(len(bars) - 1) if boundary_at else boundary
            back_inside = bars[-1]["close"] < latest_line if direction == "up" else bars[-1]["close"] > latest_line
            return ("突破后回落" if back_inside else "已确认"), warnings, i
    return "待确认", warnings, None


def _double_patterns(bars: list[dict], pivots: list[dict]) -> list[dict]:
    found = []
    for a, middle, c in zip(pivots, pivots[1:], pivots[2:]):
        if a["kind"] != c["kind"] or a["kind"] == middle["kind"] or _age_days(bars, c["i"]) > 60:
            continue
        if not 18 <= c["i"] - a["i"] <= 130 or abs(c["price"] / a["price"] - 1) > .03:
            continue
        top = a["kind"] == "H"
        if (top and bars[-1]["close"] > max(a["price"], c["price"]) * 1.03) or (not top and bars[-1]["close"] < min(a["price"], c["price"]) * .97):
            continue  # Later price action invalidated the potential reversal.
        depth = (min(a["price"], c["price"]) / middle["price"] - 1) if top else (middle["price"] / max(a["price"], c["price"]) - 1)
        if depth < .08:  # engineering minimum to exclude ordinary noise
            continue
        direction = "down" if top else "up"
        level = middle["price"]
        status, warnings, breakout_i = _status(bars, c["i"], level, direction, not top)
        if (breakout_i is not None and _age_days(bars, breakout_i) > 45) or (breakout_i is None and _age_days(bars, c["i"]) > 45):
            continue
        height = abs(mean([a["price"], c["price"]]) - level)
        target = level - height if top else level + height
        evidence = ["两次测试价差不超过 3%", f"两端相隔 {c['i']-a['i']} 根 K 线", f"中间回撤/反弹 {depth*100:.1f}%"]
        if not top:
            vr = _vol_ratio(bars, len(bars) - 1)
            if vr is None:
                warnings.append("没有可用成交量，向上突破无法完成量能确认")
        found.append(_pattern("双重顶" if top else "双重底", "反转", direction, status, a, c, level, target, evidence, warnings, [9]))
    return found


def _head_shoulders(bars: list[dict], pivots: list[dict]) -> list[dict]:
    found = []
    for seq in zip(*(pivots[i:] for i in range(5))):
        a, b, head, d, e = seq
        if _age_days(bars, e["i"]) > 60 or e["i"] - a["i"] < 20 or e["i"] - a["i"] > 160:
            continue
        top = a["kind"] == "H"
        if [p["kind"] for p in seq] != (["H", "L", "H", "L", "H"] if top else ["L", "H", "L", "H", "L"]):
            continue
        if top and not (b["price"] < a["price"] and b["price"] < head["price"] and d["price"] < head["price"] and d["price"] < e["price"]):
            continue
        if not top and not (b["price"] > a["price"] and b["price"] > head["price"] and d["price"] > head["price"] and d["price"] > e["price"]):
            continue
        if (top and bars[-1]["close"] > head["price"] * 1.03) or (not top and bars[-1]["close"] < head["price"] * .97):
            continue
        if abs(e["price"] / a["price"] - 1) > .08 or abs(d["price"] / b["price"] - 1) > .08:
            continue
        if top and not (head["price"] >= max(a["price"], e["price"]) * 1.03):
            continue
        if not top and not (head["price"] <= min(a["price"], e["price"]) * .97):
            continue
        if top and e["volume"] >= head["volume"] and e["volume"] > 0:
            continue
        slope = (d["price"] - b["price"]) / (d["i"] - b["i"])
        if abs(slope) > mean([b["price"], d["price"]]) * .005:
            continue  # A steep neckline makes a distant projected trigger meaningless.
        line = lambda i: b["price"] + slope * (i - b["i"])
        trigger = line(len(bars) - 1)
        if trigger <= 0:
            continue
        direction = "down" if top else "up"
        status, warnings, breakout_i = _status(bars, e["i"], trigger, direction, not top, line)
        if (breakout_i is not None and _age_days(bars, breakout_i) > 45) or (breakout_i is None and _age_days(bars, e["i"]) > 45):
            continue
        head_line = line(head["i"])
        height = abs(head["price"] - head_line)
        target = trigger - height if top else trigger + height
        evidence = ["肩—头—肩共五个交替转折点", "头部越过双肩至少 3%", "颈线连接两个中间转折点"]
        if top:
            evidence.append("右肩成交量低于头部" if e["volume"] < head["volume"] else "右肩成交量未知")
        found.append(_pattern("头肩顶" if top else "头肩底", "反转", direction, status, a, e,
                              trigger, target, evidence, warnings, [6] if top else [7]))
    return found


def _triangles(bars: list[dict], pivots: list[dict]) -> list[dict]:
    found = []
    recent = [p for p in pivots if p["i"] >= len(bars) - 130]
    for seq in zip(*(recent[i:] for i in range(4))):
        if len({p["kind"] for p in seq}) != 2 or any(seq[i]["kind"] == seq[i+1]["kind"] for i in range(3)):
            continue
        highs = [p for p in seq if p["kind"] == "H"]
        lows = [p for p in seq if p["kind"] == "L"]
        start, end = seq[0], seq[-1]
        if _age_days(bars, end["i"]) > 60 or end["i"] - start["i"] < 15:
            continue
        hs = (highs[1]["price"] - highs[0]["price"]) / (highs[1]["i"] - highs[0]["i"])
        ls = (lows[1]["price"] - lows[0]["price"]) / (lows[1]["i"] - lows[0]["i"])
        width = highs[0]["price"] - lows[0]["price"]
        if width <= 0 or hs >= ls:
            continue
        rel_h = (highs[1]["price"] / highs[0]["price"] - 1)
        rel_l = (lows[1]["price"] / lows[0]["price"] - 1)
        if rel_h < -.01 and rel_l > .01:
            name = "对称三角形"
        elif abs(rel_h) <= .02 and rel_l > .01:
            name = "上升三角形"
        elif rel_h < -.01 and abs(rel_l) <= .02:
            name = "下降三角形"
        else:
            continue
        upper = lambda i: highs[0]["price"] + hs * (i - highs[0]["i"])
        lower = lambda i: lows[0]["price"] + ls * (i - lows[0]["i"])
        apex = (lows[0]["price"] - ls*lows[0]["i"] - highs[0]["price"] + hs*highs[0]["i"]) / (hs - ls)
        if apex <= end["i"] or apex > len(bars) + 150:
            continue
        progress = (len(bars) - 1 - start["i"]) / (apex - start["i"])
        if progress > 1:
            continue
        up_status, up_warning, up_i = _status(bars, end["i"], upper(len(bars)-1), "up", True, upper)
        down_status, down_warning, down_i = _status(bars, end["i"], lower(len(bars)-1), "down", False, lower)
        if (up_status == "已确认" and up_i is not None and _age_days(bars, up_i) > 45) or (down_status == "已确认" and down_i is not None and _age_days(bars, down_i) > 45):
            continue
        if up_status == "已确认" and up_i is not None and _age_days(bars, up_i) <= 45:
            direction, status, boundary, warnings = "up", up_status, upper(up_i), up_warning
        elif down_status == "已确认" and down_i is not None and _age_days(bars, down_i) <= 45:
            direction, status, boundary, warnings = "down", down_status, lower(down_i), down_warning
        else:
            direction, status, boundary, warnings = "undetermined", "待突破", None, []
            if _age_days(bars, end["i"]) > 45:
                continue
        if progress > .75:
            warnings.append("已越过书中较有效的起点至顶点 1/2—3/4 突破区间")
        first_vol = mean(p["volume"] for p in seq[:2])
        last_vol = mean(p["volume"] for p in seq[2:])
        if first_vol > 0 and last_vol >= first_vol:
            warnings.append("形成期成交量未出现收缩")
        target = (boundary + width if direction == "up" else boundary - width) if boundary else None
        evidence = ["两个波峰和两个波谷界定边界", f"上沿变化 {rel_h*100:.1f}%，下沿变化 {rel_l*100:.1f}%", f"当前约位于起点至顶点的 {progress*100:.0f}%"]
        found.append(_pattern(name, "整固或反转", direction, status, start, end, boundary or mean([upper(len(bars)-1), lower(len(bars)-1)]), target, evidence, warnings, [8]))
    return found


def _rectangles(bars: list[dict], pivots: list[dict]) -> list[dict]:
    """Chapter 9: two comparable highs and lows before a directional exit."""
    found = []
    for seq in zip(*(pivots[i:] for i in range(4))):
        highs = [p for p in seq if p["kind"] == "H"]
        lows = [p for p in seq if p["kind"] == "L"]
        if len(highs) != 2 or len(lows) != 2 or _age_days(bars, seq[-1]["i"]) > 60:
            continue
        if not 15 <= seq[-1]["i"] - seq[0]["i"] <= 160:
            continue
        if abs(highs[1]["price"] / highs[0]["price"] - 1) > .025 or abs(lows[1]["price"] / lows[0]["price"] - 1) > .025:
            continue
        upper, lower = mean(p["price"] for p in highs), mean(p["price"] for p in lows)
        width = upper - lower
        if lower <= 0 or not .04 <= width / lower <= .25:
            continue
        up, up_warn, up_i = _status(bars, seq[-1]["i"], upper, "up", True)
        down, down_warn, down_i = _status(bars, seq[-1]["i"], lower, "down", False)
        if up == "已确认" and up_i is not None and _age_days(bars, up_i) <= 45:
            direction, status, boundary, target, warnings = "up", up, upper, upper + width, up_warn
        elif down == "已确认" and down_i is not None and _age_days(bars, down_i) <= 45:
            direction, status, boundary, target, warnings = "down", down, lower, lower - width, down_warn
        elif _age_days(bars, seq[-1]["i"]) <= 45 and lower * .97 <= bars[-1]["close"] <= upper * 1.03:
            direction, status, boundary, target, warnings = "undetermined", "待突破", upper, None, up_warn
        else:
            continue
        first_vol = mean(bars[i]["volume"] for i in range(seq[0]["i"], (seq[0]["i"] + seq[-1]["i"]) // 2 + 1))
        last_vol = mean(bars[i]["volume"] for i in range((seq[0]["i"] + seq[-1]["i"]) // 2 + 1, seq[-1]["i"] + 1))
        if first_vol > 0 and last_vol >= first_vol:
            warnings.append("箱体形成期未见成交量收缩")
        evidence = [f"两次高点价差 {abs(highs[1]['price']/highs[0]['price']-1)*100:.1f}%",
                    f"两次低点价差 {abs(lows[1]['price']/lows[0]['price']-1)*100:.1f}%",
                    f"区间宽度 {width/lower*100:.1f}%，上沿 {upper:.2f}，下沿 {lower:.2f}"]
        found.append(_pattern("箱体", "整固或反转", direction, status, seq[0], seq[-1],
                              boundary, target, evidence, warnings, [9]))
    return found


def _triple_patterns(bars: list[dict], pivots: list[dict]) -> list[dict]:
    """Chapter 9: a third test is distinct from an H&S because all three ends align."""
    found = []
    for seq in zip(*(pivots[i:] for i in range(5))):
        ends = [seq[0], seq[2], seq[4]]
        middles = [seq[1], seq[3]]
        if _age_days(bars, seq[-1]["i"]) > 60 or seq[-1]["i"] - seq[0]["i"] < 30:
            continue
        top = ends[0]["kind"] == "H"
        if [p["kind"] for p in seq] != (["H", "L", "H", "L", "H"] if top else ["L", "H", "L", "H", "L"]):
            continue
        end_prices = [p["price"] for p in ends]
        if max(end_prices) / min(end_prices) - 1 > .03:
            continue
        boundary = min(p["price"] for p in middles) if top else max(p["price"] for p in middles)
        depth = (min(end_prices) / boundary - 1) if top else (boundary / max(end_prices) - 1)
        if depth < .08:
            continue
        direction = "down" if top else "up"
        if (top and bars[-1]["close"] > max(end_prices) * 1.03) or (not top and bars[-1]["close"] < min(end_prices) * .97):
            continue
        status, warnings, breakout_i = _status(bars, seq[-1]["i"], boundary, direction, not top)
        if (breakout_i is not None and _age_days(bars, breakout_i) > 45) or (breakout_i is None and _age_days(bars, seq[-1]["i"]) > 45):
            continue
        if top and ends[2]["volume"] > ends[0]["volume"]:
            warnings.append("第三次顶部量能未低于第一次，形态质量较弱")
        if not top and ends[2]["volume"] > 0 and ends[2]["volume"] > ends[0]["volume"]:
            warnings.append("第三次底部量能未萎缩")
        height = abs(mean(end_prices) - boundary)
        target = boundary - height if top else boundary + height
        evidence = ["三次高点/低点价差不超过 3%", f"两次中间调整幅度至少 {depth*100:.1f}%", "最终突破中间两点界线"]
        found.append(_pattern("三重顶" if top else "三重底", "反转", direction, status,
                              seq[0], seq[-1], boundary, target, evidence, warnings, [9]))
    return found


def _wedges(bars: list[dict], pivots: list[dict]) -> list[dict]:
    """Chapter 10: both bounds lean together and converge; counter-slope exit matters."""
    found = []
    for seq in zip(*(pivots[i:] for i in range(4))):
        highs = [p for p in seq if p["kind"] == "H"]
        lows = [p for p in seq if p["kind"] == "L"]
        if len(highs) != 2 or len(lows) != 2 or _age_days(bars, seq[-1]["i"]) > 60:
            continue
        span_days = (date.fromisoformat(seq[-1]["date"]) - date.fromisoformat(seq[0]["date"])).days
        if span_days < 21:
            continue
        hs = (highs[1]["price"] - highs[0]["price"]) / (highs[1]["i"] - highs[0]["i"])
        ls = (lows[1]["price"] - lows[0]["price"]) / (lows[1]["i"] - lows[0]["i"])
        if not hs < ls:
            continue
        rising = hs > 0 and ls > 0
        falling = hs < 0 and ls < 0
        if not (rising or falling):
            continue
        if abs(highs[1]["price"] / highs[0]["price"] - 1) < .015 or abs(lows[1]["price"] / lows[0]["price"] - 1) < .015:
            continue
        upper = lambda i: highs[0]["price"] + hs * (i - highs[0]["i"])
        lower = lambda i: lows[0]["price"] + ls * (i - lows[0]["i"])
        width_start = upper(seq[0]["i"]) - lower(seq[0]["i"])
        width_end = upper(seq[-1]["i"]) - lower(seq[-1]["i"])
        if width_start <= 0 or width_end <= 0 or width_end / width_start > .8:
            continue
        apex = (lows[0]["price"] - ls*lows[0]["i"] - highs[0]["price"] + hs*highs[0]["i"]) / (hs - ls)
        if apex <= seq[-1]["i"]:
            continue
        progress = (len(bars)-1-seq[0]["i"]) / (apex-seq[0]["i"])
        if progress < .55 or progress > 1.1:
            continue
        direction = "down" if rising else "up"
        line = lower if rising else upper
        status, warnings, breakout_i = _status(bars, seq[-1]["i"], line(len(bars)-1), direction, not rising, line)
        if (breakout_i is not None and _age_days(bars, breakout_i) > 45) or (breakout_i is None and _age_days(bars, seq[-1]["i"]) > 45):
            continue
        if status == "待确认":
            status = "待突破"
        first_vol = mean(p["volume"] for p in seq[:2])
        last_vol = mean(p["volume"] for p in seq[2:])
        if first_vol > 0 and last_vol >= first_vol:
            warnings.append("楔形内成交量未明显收缩")
        evidence = ["上下边界同向倾斜并收敛", f"形态持续 {span_days} 天",
                    f"边界宽度收缩 {(1-width_end/width_start)*100:.1f}%", f"距顶点进度 {progress*100:.0f}%"]
        found.append(_pattern("上升楔形" if rising else "下降楔形", "短中线形态",
                              direction, status, seq[0], seq[-1], line(len(bars)-1), None,
                              evidence, warnings, [10]))
    return found


def _events(bars: list[dict]) -> list[dict]:
    """Chapters 10 and 12: observable events, without speculative gap taxonomy."""
    events = []
    first = max(20, len(bars) - 45)
    for i in range(first, len(bars)):
        today, previous = bars[i], bars[i-1]
        gap_direction = "up" if today["low"] > previous["high"] else "down" if today["high"] < previous["low"] else None
        if gap_direction:
            edge = previous["high"] if gap_direction == "up" else previous["low"]
            gap_edge = today["low"] if gap_direction == "up" else today["high"]
            gap_pct = abs(gap_edge / edge - 1) * 100
            if gap_pct >= 1:  # engineering noise floor
                later = bars[i+1:]
                filled_at = next((b["date"] for b in later if (b["low"] <= edge if gap_direction == "up" else b["high"] >= edge)), None)
                prior_high = max(b["high"] for b in bars[i-20:i])
                prior_low = min(b["low"] for b in bars[i-20:i])
                breakout_context = (today["close"] > prior_high * 1.03 if gap_direction == "up" else today["close"] < prior_low * .97)
                events.append({"type": "价格区间缺口", "direction": gap_direction, "date": today["date"],
                               "price": _round(gap_edge), "magnitude_pct": _round(gap_pct),
                               "status": "已回补" if filled_at else "尚未回补", "filled_date": filled_at,
                               "context": "同时突破前20期极值" if breakout_context else "未同时突破前20期极值",
                               "note": "缺口类别需结合形态位置及后续走势；复权图上的缺口须用原始交易价核查。",
                               "book_chapters": [12]})
        if i >= 20:
            former_high = max(b["high"] for b in bars[i-20:i])
            former_low = min(b["low"] for b in bars[i-20:i])
            bearish = today["high"] > former_high and today["close"] < previous["close"]
            bullish = today["low"] < former_low and today["close"] > previous["close"]
            if bearish or bullish:
                invalidated = (bars[-1]["close"] > today["high"] if bearish else bars[-1]["close"] < today["low"])
                events.append({"type": "关键反转日候选", "direction": "down" if bearish else "up",
                               "date": today["date"], "price": _round(today["close"]),
                               "status": "后续已失效" if invalidated else "待结合趋势核验",
                               "magnitude_pct": None, "filled_date": None,
                               "context": "创20期新高后收盘低于前收" if bearish else "创20期新低后收盘高于前收",
                               "note": "单日形态只有短线意义；需要与趋势线、支撑阻力和量能复核。",
                               "book_chapters": [10]})
    return events[-12:][::-1]


def _atr(bars: list[dict], period: int = 20) -> float | None:
    if len(bars) < period + 1:
        return None
    ranges = []
    for i in range(len(bars)-period, len(bars)):
        bar, prev = bars[i], bars[i-1]
        ranges.append(max(bar["high"]-bar["low"], abs(bar["high"]-prev["close"]), abs(bar["low"]-prev["close"])))
    return mean(ranges)


def _basis_ladder(bars: list[dict], pivots: list[dict], entry_date: str | None) -> dict | None:
    """Illustrative long-only Chapter 28 stop states from a supplied entry date."""
    if entry_date is None:
        return None
    date.fromisoformat(entry_date)
    if entry_date < bars[0]["date"]:
        raise ValueError("entry_date 早于可用行情起点")
    entry_i = next((i for i, bar in enumerate(bars) if bar["date"] >= entry_date), None)
    if entry_i is None or entry_i >= len(bars)-3:
        raise ValueError("entry_date 必须位于至少 3 根后续 K 线之前")
    earlier_lows = [p for p in pivots if p["kind"] == "L" and p["i"] + PIVOT_RADIUS <= entry_i and p["price"] < bars[entry_i]["close"]]
    basis = earlier_lows[-1]["price"] if earlier_lows else min(b["low"] for b in bars[max(0,entry_i-20):entry_i+1])
    variant1 = variant2 = basis * (1 - STOP_BUFFER)
    reference_high = bars[entry_i]["high"]
    updates = []
    triggered1 = triggered2 = None
    troughs_at_confirmation = {}
    for p in pivots:
        if p["kind"] == "L" and p["i"] > entry_i:
            troughs_at_confirmation[p["i"] + PIVOT_RADIUS] = p
    for i in range(entry_i+1, len(bars)):
        bar = bars[i]
        if triggered1 is None and bar["low"] <= variant1:
            triggered1 = bar["date"]
        if triggered2 is None and bar["low"] <= variant2:
            triggered2 = bar["date"]
        if triggered1 is not None and triggered2 is not None:
            break
        pivot = troughs_at_confirmation.get(i)
        if pivot:
            candidate = pivot["price"] * (1 - STOP_BUFFER)
            if triggered1 is None and candidate > variant1:
                variant1 = candidate
                updates.append({"date": bar["date"], "variant": 1, "stop": _round(variant1), "reason": "确认波谷"})
            if triggered2 is None and candidate > variant2:
                variant2 = candidate
                updates.append({"date": bar["date"], "variant": 2, "stop": _round(variant2), "reason": "确认波谷"})
        if bar["high"] > reference_high * 1.03:
            reference_high = bar["high"]
            candidate = bar["low"] * (1 - STOP_BUFFER)
            if triggered2 is None and candidate > variant2:
                variant2 = candidate
                updates.append({"date": bar["date"], "variant": 2, "stop": _round(variant2), "reason": "越过前高3%"})
    return {"entry_date": bars[entry_i]["date"], "assumed_entry_close": _round(bars[entry_i]["close"]),
            "variant1": {"stop": _round(variant1), "triggered_date": triggered1},
            "variant2": {"stop": _round(variant2), "triggered_date": triggered2},
            "recent_updates": updates[-20:],
            "note": "假设在所选 K 线收盘建仓；先检查既有止损触发，再在收盘后抬升。波谷以左右各3根K线确认，是原书三天法则的工程近似；周线不可按日线三天法则解读。若触发，价格仅标示首次穿越日期，不模拟成交、滑点或再入场。"}


def _stop_reference(bars: list[dict], pivots: list[dict], capital: float | None, risk_pct: float) -> dict:
    close = bars[-1]["close"]
    lows = [p for p in pivots if p["kind"] == "L" and p["price"] < close and p["i"] >= len(bars) - 120]
    pivot = lows[-1] if lows else None
    basis = pivot["price"] if pivot else min(b["low"] for b in bars[-30:])
    stop = basis * (1 - STOP_BUFFER)
    risk_per_share = max(0, close - stop)
    sizing = None
    if capital is not None:
        if capital <= 0 or not 0 < risk_pct <= 5:
            raise ValueError("capital 必须大于 0，risk_pct 必须在 0 至 5 之间")
        sizing = {"capital": capital, "risk_pct": risk_pct,
                  "risk_budget": _round(capital * risk_pct / 100),
                  "max_shares_by_risk": floor((capital * risk_pct / 100) / risk_per_share) if risk_per_share > 0 else 0}
    return {"basis_date": pivot["date"] if pivot else None, "basis_price": _round(basis),
            "protective_reference": _round(stop), "distance_pct": _round((close - stop) / close * 100),
            "risk_per_share": _round(risk_per_share), "position_sizing": sizing,
            "method": "最近确认波谷下方 6%" if pivot else "30 根 K 线低点下方 6%（缺少近期确认波谷）",
            "book_chapters": [27, 28],
            "limitation": "仅为多头风险参考；跳空时实际成交价可能越过该价位。"}


def analyze(bars: list[dict], symbol: str, source: dict | None = None,
            capital: float | None = None, risk_pct: float = 1,
            entry_date: str | None = None) -> dict:
    bars = validate_bars(bars)
    pivots = _pivots(bars)
    trend = _trend(bars, pivots)
    levels = _levels(bars, pivots)
    candidates = (_double_patterns(bars, pivots) + _head_shoulders(bars, pivots) +
                  _triangles(bars, pivots) + _rectangles(bars, pivots) +
                  _triple_patterns(bars, pivots) + _wedges(bars, pivots))
    # Keep the most recent instance of each named pattern; never count duplicate pivot windows as independent evidence.
    by_name = {}
    for candidate in candidates:
        if candidate["name"] not in by_name or candidate["end_date"] > by_name[candidate["name"]]["end_date"]:
            by_name[candidate["name"]] = candidate
    patterns = sorted(by_name.values(), key=lambda p: (p["status"] == "已确认", p["end_date"]), reverse=True)
    close = bars[-1]["close"]
    for pattern in patterns:
        target = pattern["measured_target"]
        if target is None or pattern["status"] != "已确认":
            pattern["target_state"] = "仅在确认突破后参考"
        else:
            reached = close >= target if pattern["direction"] == "up" else close <= target
            pattern["target_state"] = "已触及" if reached else "未触及"
    volume_ratio = _vol_ratio(bars, len(bars) - 1)
    warnings = []
    if all(bar["volume"] == 0 for bar in bars[-20:]):
        warnings.append("最近 20 期成交量为空；向上突破不会被确认")
    if len(bars) < 120:
        warnings.append("样本少于 120 根 K 线，长线形态和 200 期均线不可用")
    try:
        age = (date.today() - date.fromisoformat(bars[-1]["date"])).days
        if age > 7:
            warnings.append(f"最后一根 K 线距今 {age} 天，请检查数据是否过期")
    except ValueError:
        pass
    confirmed = [p for p in patterns if p["status"] == "已确认"]
    primary = confirmed[0] if confirmed else (patterns[0] if patterns else None)
    if primary:
        interpretation = f"{trend['direction']}；识别到{primary['name']}（{primary['status']}）。"
    else:
        interpretation = f"{trend['direction']}；当前窗口未满足已实现形态的完整确认条件。"
    if trend["trendline"] and trend["trendline"]["broken"]:
        interpretation += f" {trend['trendline']['quality']}已出现 3% 收盘穿透，需复核是否为反转或整理。"
    risk = _stop_reference(bars, pivots, capital, risk_pct)
    atr20 = _atr(bars)
    risk["atr20"] = _round(atr20)
    risk["atr20_x2_distance"] = _round(2 * atr20) if atr20 is not None else None
    risk["basis_ladder"] = _basis_ladder(bars, pivots, entry_date)
    if risk["distance_pct"] > 15:
        warnings.append("保护参考位距现价超过 15%；单独用它规划新仓位可能承担较大波动")
    if risk["basis_date"] and (date.fromisoformat(bars[-1]["date"]) - date.fromisoformat(risk["basis_date"])).days > 60:
        warnings.append("最近确认波谷距今超过 60 天；保护参考位可能已不适合短线决策")
    result = {
        "schema_version": "1.1", "symbol": symbol, "source": source or {"provider": "supplied bars", "as_of": bars[-1]["date"]},
        "summary": interpretation, "last": {"date": bars[-1]["date"], "close": _round(close),
            "change_pct": _round(_pct(close, bars[-2]["close"])), "volume_ratio_20": _round(volume_ratio),
            "bar_count": len(bars)},
        "trend": trend, "levels": levels, "patterns": patterns, "events": _events(bars),
        "risk": risk,
        "indicators": {"ma50": _moving_average(bars, 50), "ma200": _moving_average(bars, 200)},
        "pivots": [{"kind": p["kind"], "date": p["date"], "price": _round(p["price"])} for p in pivots[-30:]],
        "bars": [{**bar, "open": _round(bar["open"]), "high": _round(bar["high"]),
                  "low": _round(bar["low"]), "close": _round(bar["close"])} for bar in bars],
        "warnings": warnings,
        "method": {"book": "《股市趋势技术分析》原书第 10 版", "rules_version": "1.1", "breakout_close_pct": 3,
                   "up_volume_ratio": UP_VOLUME, "pivot_radius": PIVOT_RADIUS,
                   "note": "量化阈值中部分为工程选择；详见 KNOWLEDGE.md。测算目标为形态幅度，不是价格预测。"},
    }
    result["buy_reference"] = buy_reference(result)
    return result
