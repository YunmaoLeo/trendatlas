"""Walk-forward evaluation of book-derived buy conditions on adjusted daily bars.

This is a research command, not a trading simulator. A signal uses that day's
closing price; its label is the close after ``horizon`` trading sessions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median

from .data import audit_bars, from_yfinance
from .engine import analyze
from .legacy_score import buy_reference as legacy_buy_reference
from .replay import replay

FEATURES = ("trend", "confirmed_pattern", "averages", "volume", "room_to_risk")


def conditions(snapshot: dict) -> list[float]:
    """Five values derived from the same causal analysis used by the UI."""
    trend = {"上升趋势": 1, "下降趋势": -1}.get(snapshot["trend"]["direction"], 0)
    patterns = snapshot["patterns"]
    up = any(p["status"] == "已确认" and p["direction"] == "up" for p in patterns)
    down = any(p["status"] == "已确认" and p["direction"] == "down" for p in patterns)
    pattern = int(up) - int(down)
    close = snapshot["last"]["close"]
    ma50 = snapshot["indicators"]["ma50"]
    ma200 = snapshot["indicators"]["ma200"]
    if ma50 and ma200:
        checks = (close > ma50[-1]["value"], ma50[-1]["value"] > ma200[-1]["value"])
        averages = sum(checks) - 1
    else:
        averages = 0
    ratio = snapshot["last"]["volume_ratio_20"]
    volume = max(-1, min(1, (ratio or 1) - 1)) if ratio is not None else 0
    resistance = snapshot["levels"]["resistance"]
    stop = snapshot["risk"]["protective_reference"]
    if stop is not None and stop < close and resistance["method"] != "30 根 K 线区间极值":
        room = min(3, max(0, resistance["price"] - close) / (close - stop)) / 3
    else:
        room = 0
    return [float(trend), float(pattern), float(averages), float(volume), float(room)]


def sample(bars: list[dict], symbol: str, horizon: int, warmup: int = 200) -> list[dict]:
    """One observation per non-overlapping horizon for each symbol."""
    observations = []
    for index in range(warmup - 1, len(bars) - horizon, horizon):
        prefix = bars[:index + 1]
        snapshot = analyze(prefix, symbol, source={"provider": "historical prefix", "interval": "1d"})
        future = bars[index + horizon]
        forward_return = future["close"] / bars[index]["close"] - 1
        observations.append({"symbol": symbol, "date": bars[index]["date"], "end_date": future["date"],
                             "features": conditions(snapshot),
                             "old_score": legacy_buy_reference(snapshot)["experimental_score"],
                             "return": forward_return, "up": int(forward_return > 0)})
    return observations


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def fit(rows: list[dict], penalty: float = 1.0) -> list[float]:
    """L2 logistic loss; nonnegative condition weights retain book direction."""
    if not rows:
        raise ValueError("训练集为空")
    rate = max(.01, min(.99, mean(row["up"] for row in rows)))
    weights = [math.log(rate / (1 - rate))] + [0.0] * len(FEATURES)
    # Features are bounded by one. Full-batch projected descent is deterministic.
    for _ in range(4000):
        gradient = [0.0] * len(weights)
        for row in rows:
            values = [1.0] + row["features"]
            error = sigmoid(sum(a * b for a, b in zip(weights, values))) - row["up"]
            for j, value in enumerate(values):
                gradient[j] += error * value
        step = .25
        weights[0] -= step * gradient[0] / len(rows)
        for j in range(1, len(weights)):
            weights[j] = max(0.0, weights[j] - step * (
                gradient[j] / len(rows) + penalty * weights[j] / len(rows)))
    return weights


def predict(weights: list[float], row: dict) -> float:
    return sigmoid(weights[0] + sum(a * b for a, b in zip(weights[1:], row["features"])))


def metrics(rows: list[dict], scores: list[float] | None = None) -> dict:
    if not rows:
        return {"count": 0}
    result = {"count": len(rows), "rise_pct": round(100 * mean(r["up"] for r in rows), 2),
              "mean_return_pct": round(100 * mean(r["return"] for r in rows), 2),
              "median_return_pct": round(100 * median(r["return"] for r in rows), 2),
              "worst_return_pct": round(100 * min(r["return"] for r in rows), 2)}
    if scores is not None:
        result["brier_loss"] = round(mean((p - r["up"]) ** 2 for p, r in zip(scores, rows)), 5)
        result["log_loss"] = round(-mean(r["up"] * math.log(max(1e-8, p)) +
                                          (1 - r["up"]) * math.log(max(1e-8, 1 - p))
                                          for p, r in zip(scores, rows)), 5)
    return result


def evaluate(rows: list[dict], train_end: str, validation_start: str, penalty: float = 1.0) -> dict:
    """Train labels must end before train_end; validation begins after embargo."""
    train = [r for r in rows if r["end_date"] < train_end]
    holdout = [r for r in rows if r["date"] >= validation_start]
    if not train or not holdout or max(r["end_date"] for r in train) >= min(r["date"] for r in holdout):
        raise ValueError("训练/验证边界无效或样本不足")
    weights = fit(train, penalty)
    base = mean(r["up"] for r in train)
    predictions = [predict(weights, r) for r in holdout]
    old_high = [r for r in holdout if r["old_score"] >= 60]
    old_very_high = [r for r in holdout if r["old_score"] >= 75]
    # Select the top quartile threshold on training predictions only.
    train_predictions = sorted(predict(weights, r) for r in train)
    threshold = train_predictions[int(.75 * (len(train_predictions) - 1))]
    model_high = [r for r, p in zip(holdout, predictions) if p >= threshold]
    by_symbol = defaultdict(list)
    by_symbol_high = defaultdict(list)
    for row in holdout:
        by_symbol[row["symbol"]].append(row)
        if row["old_score"] >= 60:
            by_symbol_high[row["symbol"]].append(row)
    baseline_metrics = metrics(holdout, [base] * len(holdout))
    model_metrics = metrics(holdout, predictions)
    return {"train": metrics(train), "holdout": model_metrics,
            "holdout_constant_baseline": baseline_metrics,
            "old_score_at_least_60": metrics(old_high), "old_score_at_least_75": metrics(old_very_high),
            "model_top_quartile": metrics(model_high),
            "by_symbol": {symbol: metrics(group) for symbol, group in sorted(by_symbol.items())},
            "by_symbol_old_score_at_least_60": {symbol: metrics(by_symbol_high[symbol])
                                                for symbol in sorted(by_symbol)},
            "train_rate": round(base, 5), "model_top_quartile_cutoff": round(threshold, 5),
            "weights": {key: round(value, 6) for key, value in zip(("intercept",) + FEATURES, weights)},
            "train_end_exclusive": train_end, "validation_start_inclusive": validation_start,
            "candidate_beats_baseline": model_metrics["brier_loss"] < baseline_metrics["brier_loss"]}


def confirmed_buy_events(bars: list[dict], symbol: str, horizon: int, validation_start: str,
                         source: dict) -> dict:
    """Separate descriptive check of newly confirmed upward book patterns."""
    history = replay(bars, symbol, horizon, 200, "1d", source)
    up = [event for event in history["signals"] if event["direction"] == "up" and
          event["outcome"]["complete"]]
    # Several named patterns on one close are one observable buy date.
    distinct = {event["signal_date"]: event for event in up}
    test = [event for event in distinct.values() if event["signal_date"] >= validation_start]
    def describe(events: list[dict]) -> dict:
        rows = [{"return": event["outcome"]["directional_return_pct"] / 100,
                 "up": int(event["outcome"]["directional_return_pct"] > 0)} for event in events]
        return metrics(rows)
    return {"all": describe(list(distinct.values())), "holdout": describe(test),
            "all_pattern_count": len(up), "distinct_signal_day_count": len(distinct),
            "overlap_warning": "不同确认日的未来观察窗口仍可能重叠"}


def run(symbols: list[str], horizon: int, train_end: str, validation_start: str) -> dict:
    rows = []
    sources = {}
    events = {}
    for symbol in symbols:
        bars, source = from_yfinance(symbol, "5y", "1d")
        digest = hashlib.sha256(json.dumps(bars, sort_keys=True).encode()).hexdigest()
        sources[symbol] = {"first_date": bars[0]["date"], "last_date": bars[-1]["date"],
                           "bar_count": len(bars), "sha256": digest,
                           "data_quality": audit_bars(bars), "adjustment": source["adjustment"]}
        rows.extend(sample(bars, symbol, horizon))
        events[symbol] = confirmed_buy_events(bars, symbol, horizon, validation_start, source)
        print(f"{symbol}: {len(bars)} bars, {len(rows)} observations total", flush=True)
    report = {"as_of": date.today().isoformat(), "provider": "yfinance / Yahoo Finance",
              "symbols": symbols, "horizon_trading_days": horizon,
              "sampling": "每只股票每隔 horizon 根日线取一个信号，未来窗口不重叠；不同股票仍相关",
              "target": "从信号当日复权收盘到第 horizon 个交易日复权收盘，涨幅大于零",
              "features": list(FEATURES), "sources": sources, "observations": rows,
              "confirmed_upward_pattern_events": events,
              "evaluation": evaluate(rows, train_end, validation_start),
              "limitations": ["复权历史可能被后续公司行为回溯修订；不是真正的点时数据",
                              "收盘信号与收盘价作比较，不是可成交的收盘入场回测",
                              "没有手续费、滑点、税费或仓位管理；股票样本只有四只，存在选择偏差"]}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate and audit technical buy conditions")
    parser.add_argument("--symbols", nargs="+", default=["VOO", "QQQ", "NVDA", "MU"])
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--train-end", default="2025-01-01")
    parser.add_argument("--validation-start", default="2025-02-01")
    parser.add_argument("--output", type=Path, default=Path("research/calibration.json"))
    parser.add_argument("--verify-report", type=Path, help="离线复算已有报告，不重新取数")
    args = parser.parse_args()
    if args.verify_report:
        saved = json.loads(args.verify_report.read_text(encoding="utf-8"))
        previous = saved["evaluation"]
        recomputed = evaluate(saved["observations"], previous["train_end_exclusive"],
                              previous["validation_start_inclusive"])
        if recomputed != previous:
            parser.error("报告中的结果与观察点重算结果不一致")
        print("报告内观察点与评估结果一致")
        return
    if not 5 <= args.horizon <= 120:
        parser.error("--horizon must be between 5 and 120")
    report = run(args.symbols, args.horizon, args.train_end, args.validation_start)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["evaluation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
