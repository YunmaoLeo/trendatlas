"""Causal, descriptive replay of the same pattern engine used by the chart."""

from __future__ import annotations

import argparse
import json
import sys
from statistics import mean, median

from .data import audit_bars, from_csv, from_yfinance, normalize_symbol, validate_bars
from .engine import analyze


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _outcome(bars: list[dict], index: int, horizon: int, direction: str,
             target: float | None) -> dict:
    if index + horizon >= len(bars):
        return {"complete": False, "directional_return_pct": None,
                "max_favorable_pct": None, "max_adverse_pct": None,
                "target_touched": None, "evaluation_end_date": None}
    start = bars[index]["close"]
    future = bars[index + 1:index + horizon + 1]
    sign = 1 if direction == "up" else -1
    directional_return = sign * (future[-1]["close"] / start - 1) * 100
    if direction == "up":
        favorable = max(0, (max(bar["high"] for bar in future) / start - 1) * 100)
        adverse = max(0, (1 - min(bar["low"] for bar in future) / start) * 100)
        touched = any(bar["high"] >= target for bar in future) if target is not None else None
    else:
        favorable = max(0, (1 - min(bar["low"] for bar in future) / start) * 100)
        adverse = max(0, (max(bar["high"] for bar in future) / start - 1) * 100)
        touched = any(bar["low"] <= target for bar in future) if target is not None else None
    return {"complete": True, "directional_return_pct": _rounded(directional_return),
            "max_favorable_pct": _rounded(favorable), "max_adverse_pct": _rounded(adverse),
            "target_touched": touched, "evaluation_end_date": future[-1]["date"]}


def _summarize(events: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for event in events:
        groups.setdefault((event["pattern"], event["direction"]), []).append(event)
    result = []
    for (name, direction), group in sorted(groups.items()):
        complete = [event for event in group if event["outcome"]["complete"]]
        moves = [event["outcome"]["directional_return_pct"] for event in complete]
        with_target = [event for event in complete if event["outcome"]["target_touched"] is not None]
        result.append({"pattern": name, "direction": direction, "signals": len(group),
                       "complete_windows": len(complete), "pending_windows": len(group) - len(complete),
                       "mean_directional_return_pct": _rounded(mean(moves)) if moves else None,
                       "median_directional_return_pct": _rounded(median(moves)) if moves else None,
                       "positive_directional_count": sum(move > 0 for move in moves),
                       "target_touched_count": sum(event["outcome"]["target_touched"] for event in with_target),
                       "target_evaluable_count": len(with_target),
                       "small_sample": len(complete) < 20})
    return result


def replay(bars: list[dict], symbol: str, horizon: int = 20, warmup: int = 120,
           interval: str = "1d", source: dict | None = None) -> dict:
    """Discover confirmations using only each date's prefix; evaluate later bars separately.

    Signal reference is the confirmation bar close, not an executable entry.
    Evaluation windows may overlap and no cost, slippage or short borrow is modeled.
    """
    bars = validate_bars(bars)
    if not 5 <= horizon <= 120:
        raise ValueError("horizon 必须在 5 至 120 根 K 线之间")
    if not 50 <= warmup < len(bars):
        raise ValueError("warmup 必须至少为 50 且小于行情 K 线数量")
    quality = audit_bars(bars, interval)
    seen: set[tuple[str, str, str, str]] = set()
    events = []
    for index in range(warmup - 1, len(bars)):
        prefix = bars[:index + 1]
        snapshot = analyze(prefix, symbol, source={"provider": "prefix replay", "as_of": prefix[-1]["date"],
                                                    "interval": interval})
        for pattern in snapshot["patterns"]:
            if pattern["status"] != "已确认" or pattern["direction"] not in {"up", "down"}:
                continue
            key = (pattern["name"], pattern["start_date"], pattern["end_date"], pattern["direction"])
            if key in seen:
                continue
            seen.add(key)
            if index == warmup - 1:
                continue  # A confirmation that predates the observation window is not a new signal.
            events.append({"signal_date": bars[index]["date"], "pattern": pattern["name"],
                           "direction": pattern["direction"], "book_chapters": pattern["book_chapters"],
                           "structure_start_date": pattern["start_date"],
                           "structure_end_date": pattern["end_date"],
                           "signal_close": _rounded(bars[index]["close"]),
                           "trigger": pattern["trigger"], "measured_target": pattern["measured_target"],
                           "volume_ratio_20": snapshot["last"]["volume_ratio_20"],
                           "outcome": _outcome(bars, index, horizon, pattern["direction"], pattern["measured_target"])})
    completed = [event for event in events if event["outcome"]["complete"]]
    warnings = []
    if not completed:
        warnings.append("没有完整的信号观察窗口；请延长历史区间或缩短 horizon")
    if any(group["small_sample"] for group in _summarize(events)):
        warnings.append("至少一个形态的完整样本少于 20；统计量仅供描述")
    if quality["issues"]:
        warnings.append("数据质量审计发现需人工核查的记录")
    adjustment = (source or {}).get("adjustment", "")
    if "auto_adjust" in adjustment:
        warnings.append("复权历史可能受后续拆股和分红回溯修订；这不是严格的点时可得数据回测")
    return {"schema_version": "1.0", "symbol": symbol, "source": source or {"provider": "supplied bars", "as_of": bars[-1]["date"]},
            "horizon_bars": horizon, "warmup_bars": warmup, "data_quality": quality,
            "signal_count": len(events), "unique_signal_days": len({event["signal_date"] for event in events}),
            "complete_count": len(completed),
            "pending_count": len(events) - len(completed), "by_pattern": _summarize(events),
            "signals": events, "warnings": warnings,
            "method": {"signal_generation": "每一历史日期仅将该日及之前 K 线传入当前规则引擎；新确认形态只计一次",
                       "measurement": "确认日收盘价到未来第 horizon 根 K 线收盘的方向化变动；未来高低价只用于事后有利/不利幅度和目标触及",
                       "limitations": "描述性历史回放；未模拟下单、止损成交、滑点、手续费、税、借券、仓位、样本外校准或多重检验。窗口可能重叠，不能将方向化正收益比例称为策略胜率。"}}


def main() -> int:
    parser = argparse.ArgumentParser(description="逐根历史回放书籍形态，stdout 输出 JSON")
    parser.add_argument("symbol")
    parser.add_argument("--csv", help="离线 OHLCV CSV 文件")
    parser.add_argument("--period", default="5y", choices=["6mo", "1y", "2y", "5y"])
    parser.add_argument("--interval", default="1d", choices=["1d", "1wk"])
    parser.add_argument("--horizon", type=int, default=20, help="事后观察 K 线根数，5–120")
    parser.add_argument("--warmup", type=int, default=120, help="信号扫描前预热 K 线根数，至少 50")
    args = parser.parse_args()
    try:
        symbol = normalize_symbol(args.symbol)
        if args.csv:
            bars = from_csv(args.csv)
            source = {"provider": "local CSV", "symbol": symbol, "as_of": bars[-1]["date"],
                      "interval": args.interval, "adjustment": "由输入文件决定", "realtime": False}
        else:
            bars, source = from_yfinance(symbol, args.period, args.interval)
        print(json.dumps(replay(bars, symbol, args.horizon, args.warmup, args.interval, source),
                         ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
