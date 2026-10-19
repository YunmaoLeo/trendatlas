"""Book-inspired experimental conditions, with evidence-gated buy assessment.

The book does not prescribe a 0-100 score. Weights and cutoffs are engineering
choices. Their historical validation failed, so no actionable score is emitted.
"""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _calibration() -> dict | None:
    path = Path(__file__).resolve().parent.parent / "research" / "calibration.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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

    experimental_score = sum(part["points"] for part in parts)
    calibration = _calibration()
    validation = None
    if calibration:
        results = calibration["evaluation"]
        symbol = analysis.get("symbol", "")
        validation = {
            "as_of": calibration["as_of"], "horizon_trading_days": calibration["horizon_trading_days"],
            "symbols": calibration["symbols"], "symbol_in_sample": symbol in calibration["symbols"],
            "holdout": results["holdout"], "baseline": results["holdout_constant_baseline"],
            "old_score_at_least_60": results["old_score_at_least_60"],
            "this_symbol": results["by_symbol"].get(symbol),
            "this_symbol_old_score_at_least_60": results["by_symbol_old_score_at_least_60"].get(symbol),
            "candidate_beats_baseline": results["candidate_beats_baseline"],
        }
    interval = analysis.get("source", {}).get("interval", "1d")
    max_age = 21 if interval == "1wk" else 7
    age = (date.today() - date.fromisoformat(analysis["last"]["date"])).days
    common = {"score": None, "experimental_score": experimental_score, "parts": parts,
              "validation": validation,
              "room_risk_ratio": round(room_risk_ratio, 4) if room_risk_ratio is not None else None,
              "as_of": analysis["last"]["date"]}
    if age > max_age:
        return {**common, "label": "行情过期，无法评估", "note": "最后一根行情距今过久；旧规则分仅供检查计算。"}
    if validation is None:
        return {**common, "label": "缺少历史校准，暂无可靠买入分",
                "note": "没有可核对的历史校准报告；旧规则分仅供审计。"}
    if validation["candidate_beats_baseline"]:
        return {**common, "label": "候选模型待审核，暂无正式买入分",
                "note": "旧规则门槛未获支持；候选模型即使在本次留出集优于基准，也还未完成独立确认或部署。"}
    return {**common, "label": "历史检验未通过，暂无可靠买入分",
            "note": "旧规则分保留供审计。其 60/75 分门槛没有在留出样本中证明有效；新拟合模型的误差也高于简单基准。"}
