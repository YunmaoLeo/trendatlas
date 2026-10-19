"""Transparent, book-inspired technical buy reference for the current bar.

The book does not prescribe a 0-100 score. Weights and cutoffs are engineering
choices, disclosed with every result. This is not a probability or order.
"""

from datetime import date


def buy_reference(analysis: dict) -> dict:
    close = analysis["last"]["close"]
    direction = analysis["trend"]["direction"]
    patterns = analysis["patterns"]
    parts = []

    trend_points = {"上升趋势": 25, "区间或过渡": 12, "下降趋势": 0, "未确认": 8}.get(direction, 8)
    parts.append({"key": "trend", "label": "价格趋势", "points": trend_points, "max_points": 25,
                  "reason": direction})

    confirmed_up = [p for p in patterns if p["status"] == "已确认" and p["direction"] == "up"]
    confirmed_down = [p for p in patterns if p["status"] == "已确认" and p["direction"] == "down"]
    if confirmed_up and confirmed_down:
        pattern_points, pattern_reason = 0, "看涨和看跌形态同时出现，信号冲突"
    elif confirmed_down:
        pattern_points, pattern_reason = 0, f"{confirmed_down[0]['name']}已确认向下"
    elif confirmed_up:
        main = confirmed_up[0]
        if main.get("target_state") == "已触及":
            pattern_points, pattern_reason = 12, f"{main['name']}已向上突破，但已到达形态测算位"
        else:
            pattern_points, pattern_reason = 30, f"{main['name']}已确认向上"
    else:
        pending_up = next((p for p in patterns if p["direction"] == "up"), None)
        pending_down = next((p for p in patterns if p["direction"] == "down"), None)
        if pending_down:
            pattern_points, pattern_reason = 5, f"{pending_down['name']}偏向下，尚未确认"
        elif pending_up:
            pattern_points, pattern_reason = 15, f"{pending_up['name']}偏向上，尚未确认"
        else:
            pattern_points, pattern_reason = 10, "目前没有已确认的向上突破"
    parts.append({"key": "pattern", "label": "形态确认", "points": pattern_points,
                  "max_points": 30, "reason": pattern_reason})

    ma50 = analysis["indicators"]["ma50"]
    ma200 = analysis["indicators"]["ma200"]
    if not ma50 or not ma200:
        ma_points, ma_reason = 5, "历史 K 线不足，均线信息不完整"
    elif close > ma50[-1]["value"] and ma50[-1]["value"] > ma200[-1]["value"]:
        ma_points, ma_reason = 10, "现价高于 50 期线，50 期线高于 200 期线"
    elif close > ma50[-1]["value"] or ma50[-1]["value"] > ma200[-1]["value"]:
        ma_points, ma_reason = 5, "均线只有部分支持向上"
    else:
        ma_points, ma_reason = 0, "现价与均线位置偏弱"
    parts.append({"key": "averages", "label": "均线位置", "points": ma_points,
                  "max_points": 10, "reason": ma_reason})

    if analysis["last"]["volume_ratio_20"] is None:
        volume_points, volume_reason = 0, "成交量不足，无法核对向上突破"
    elif confirmed_up and not confirmed_down:
        volume_points, volume_reason = 10, "向上突破已通过成交量检验"
    else:
        volume_points, volume_reason = 5, "目前没有已确认的放量向上突破"
    parts.append({"key": "volume", "label": "量价配合", "points": volume_points,
                  "max_points": 10, "reason": volume_reason})

    resistance = analysis["levels"]["resistance"]
    stop = analysis["risk"]["protective_reference"]
    if stop is None or stop >= close:
        position_points, position_reason, room_risk_ratio = 0, "保护参考位不在现价下方，需人工核查", None
    elif resistance["method"] == "30 根 K 线区间极值":
        position_points, position_reason, room_risk_ratio = 12, "没有可靠的上方阻力簇，空间暂按中性处理", None
    else:
        room_risk_ratio = max(0, resistance["price"] - close) / (close - stop)
        if room_risk_ratio >= 2:
            position_points = 25
        elif room_risk_ratio >= 1:
            position_points = 18
        elif room_risk_ratio >= .5:
            position_points = 10
        elif room_risk_ratio >= .25:
            position_points = 5
        else:
            position_points = 0
        position_reason = (f"到最近阻力约 {max(0, resistance['price']-close):.2f}；"
                           f"到保护参考位约 {close-stop:.2f}，两者比值 {room_risk_ratio:.2f}")
    if analysis["risk"]["distance_pct"] > 15 and position_points > 12:
        position_points = 12
        position_reason += "；保护参考位距离超过现价 15%"
    parts.append({"key": "price_position", "label": "价格位置", "points": position_points,
                  "max_points": 25, "reason": position_reason})

    score = sum(part["points"] for part in parts)
    if score >= 75:
        label = "技术条件较强"
    elif score >= 60:
        label = "部分条件支持买入，仍需确认"
    elif score >= 40:
        label = "先观察"
    else:
        label = "当前条件偏弱，暂缓"
    interval = analysis.get("source", {}).get("interval", "1d")
    max_age = 21 if interval == "1wk" else 7
    age = (date.today() - date.fromisoformat(analysis["last"]["date"])).days
    if age > max_age:
        return {"score": None, "label": "行情过期，暂不评分", "parts": parts,
                "room_risk_ratio": round(room_risk_ratio, 4) if room_risk_ratio is not None else None,
                "as_of": analysis["last"]["date"], "note": "行情距今过久，不能称为当前买入参考值。"}
    return {"score": score, "label": label, "parts": parts,
            "room_risk_ratio": round(room_risk_ratio, 4) if room_risk_ratio is not None else None,
            "as_of": analysis["last"]["date"],
            "note": "仅按本书相关技术条件形成的工程参考分；权重不是原书公式，也不是上涨概率或个人投资建议。"}
