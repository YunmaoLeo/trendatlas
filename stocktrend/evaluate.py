"""Causal, non-trading comparison of trend direction with simple baselines.

The evaluation clock is the snapshot date. Future bars are used only after the
snapshot has been generated, to score its stated direction.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from .data import from_csv, from_yfinance, normalize_symbol, validate_bars
from .engine import analyze


SIGN = {"up": 1, "up_lean": 1, "down": -1, "down_lean": -1}


def summarize(rows: list[dict]) -> dict:
    scored = [row for row in rows if row["direction"] in SIGN]
    return {
        "observation_count": len(rows),
        "directional_count": len(scored),
        "unclear_count": len(rows) - len(scored),
        "direction_aligned_count": sum(row["direction_aligned"] for row in scored),
        "past_momentum_aligned_same_dates": sum(row["past_momentum_aligned"] for row in scored),
        "always_up_aligned_same_dates": sum(row["always_up_aligned"] for row in scored),
    }


def evaluate_trend(bars: list[dict], symbol: str, horizon: int = 20,
                   warmup: int = 200, interval: str = "1d",
                   source: dict | None = None, split_date: str | None = None) -> dict:
    """Take non-overlapping snapshots and compare only on emitted-direction dates."""
    bars = validate_bars(bars)
    if not 5 <= horizon <= 120:
        raise ValueError("horizon 必须在 5 至 120 根 K 线之间")
    if warmup < max(50, horizon + 1):
        raise ValueError("warmup 必须至少为 50，且大于 horizon")
    if split_date is not None:
        date.fromisoformat(split_date)
    rows = []
    for index in range(warmup - 1, len(bars) - horizon, horizon):
        today = bars[index]["date"]
        snapshot = analyze(bars[:index + 1], symbol,
                           source={"provider": "historical prefix", "as_of": today, "interval": interval},
                           evaluation_date=date.fromisoformat(today))
        outlook = snapshot["trend_outlook"]
        direction = outlook["direction"]
        sign = SIGN.get(direction, 0)
        past = bars[index]["close"] / bars[index - horizon]["close"] - 1
        future = bars[index + horizon]["close"] / bars[index]["close"] - 1
        rows.append({
            "date": today, "evaluation_end_date": bars[index + horizon]["date"],
            "direction": direction, "structure_score": outlook["confidence_score"],
            "past_horizon_change_pct": round(past * 100, 4),
            "future_horizon_change_pct": round(future * 100, 4),
            "direction_aligned": sign * future > 0 if sign else None,
            "past_momentum_aligned": (1 if past > 0 else -1) * future > 0,
            "always_up_aligned": future > 0,
        })
    result = {
        "symbol": symbol, "source": source or {"provider": "supplied bars", "as_of": bars[-1]["date"]},
        "horizon_bars": horizon, "warmup_bars": warmup,
        "available": bool(rows), "summary": summarize(rows), "observations": rows,
        "method": {
            "sampling": "每只标的从预热结束起每隔 horizon 根 K 线取一次快照；该标的的评价窗口不重叠",
            "causality": "快照仅用当日及之前 K 线，并以快照日期判断行情是否过期；未来价格只用于事后对照",
            "comparison": "过去同等期数方向延续与一律看涨，仅在规则给出方向的相同日期比较",
            "limits": "价格方向对照，不是交易回测、预测概率或样本外优势证明；复权历史可回溯修订，不同标的可能相关",
        },
    }
    if split_date is not None:
        result["split_date"] = split_date
        result["before_split"] = summarize([row for row in rows if row["date"] < split_date])
        result["from_split"] = summarize([row for row in rows if row["date"] >= split_date])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="逐日可得趋势方向与简单基线的价格对照；stdout 输出 JSON")
    parser.add_argument("symbols", nargs="+", help="例如 VOO QQQ NVDA MU")
    parser.add_argument("--period", default="5y", choices=["1y", "2y", "5y"])
    parser.add_argument("--interval", default="1d", choices=["1d", "1wk"])
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=200)
    parser.add_argument("--split-date", help="只用于分段汇总，不训练或选择规则；YYYY-MM-DD")
    parser.add_argument("--csv", help="单只标的的离线 OHLCV CSV")
    args = parser.parse_args()
    if args.csv and len(args.symbols) != 1:
        parser.error("--csv 只能与一只股票代码一起使用")
    try:
        results = []
        for raw in args.symbols:
            symbol = normalize_symbol(raw)
            if args.csv:
                bars = from_csv(args.csv)
                source = {"provider": "local CSV", "symbol": symbol, "as_of": bars[-1]["date"],
                          "interval": args.interval, "adjustment": "由输入文件决定"}
            else:
                bars, source = from_yfinance(symbol, args.period, args.interval)
            results.append(evaluate_trend(bars, symbol, args.horizon, args.warmup,
                                          args.interval, source, args.split_date))
        combined = [row for result in results for row in result["observations"]]
        output = {"schema_version": "1.0", "results": results, "combined": summarize(combined),
                  "note": "同一日期的不同标的可能相关；对照结果不等于交易收益或可预测的成功率。"}
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
