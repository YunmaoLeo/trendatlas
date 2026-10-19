"""Market data adapters and strict bar normalization."""

from __future__ import annotations

import csv
import math
import re
from datetime import date as calendar_date
from pathlib import Path

PERIODS = {"6mo", "1y", "2y", "5y"}
INTERVALS = {"1d", "1wk"}


def normalize_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if re.fullmatch(r"\d{6}", symbol):
        return symbol + (".SS" if symbol[0] in "569" else ".SZ")
    if re.fullmatch(r"\d{1,5}", symbol):
        return symbol.zfill(4) + ".HK"
    if not re.fullmatch(r"[A-Z0-9.^-]{1,24}", symbol):
        raise ValueError("股票代码只允许字母、数字、点、连字符和 ^")
    return symbol


def validate_bars(bars: list[dict]) -> list[dict]:
    cleaned = []
    seen = set()
    for row in bars:
        date = str(row["date"])[:10]
        try:
            calendar_date.fromisoformat(date)
        except ValueError as exc:
            raise ValueError(f"日期必须是 YYYY-MM-DD: {date}") from exc
        if date in seen:
            raise ValueError(f"重复日期: {date}")
        seen.add(date)
        bar = {"date": date}
        for key in ("open", "high", "low", "close", "volume"):
            value = float(row[key])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{date} 的 {key} 无效")
            bar[key] = value
        if min(bar[k] for k in ("open", "high", "low", "close")) <= 0:
            raise ValueError(f"{date} 的价格必须大于 0")
        if bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(bar["open"], bar["close"]):
            raise ValueError(f"{date} 的 OHLC 不一致")
        cleaned.append(bar)
    cleaned.sort(key=lambda bar: bar["date"])
    if len(cleaned) < 50:
        raise ValueError("至少需要 50 根 K 线；建议提供 120 根以上")
    return cleaned


def from_csv(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = [{key.lower(): value for key, value in row.items()} for row in reader]
    return validate_bars(rows)


def audit_bars(bars: list[dict], interval: str = "1d") -> dict:
    """Report suspicious observations without deleting genuine market moves."""
    if interval not in INTERVALS:
        raise ValueError("interval 应为 1d 或 1wk")
    rows = validate_bars(bars)
    zero_volume = [bar["date"] for bar in rows if bar["volume"] == 0]
    max_gap_days = 10 if interval == "1d" else 21
    long_gaps = []
    large_moves = []
    move_floor = .35 if interval == "1d" else .5
    for previous, current in zip(rows, rows[1:]):
        gap_days = (calendar_date.fromisoformat(current["date"]) - calendar_date.fromisoformat(previous["date"])).days
        if gap_days > max_gap_days:
            long_gaps.append({"after": previous["date"], "before": current["date"], "calendar_days": gap_days})
        move = current["close"] / previous["close"] - 1
        if abs(move) >= move_floor:
            large_moves.append({"date": current["date"], "close_change_pct": round(move * 100, 2)})
    issues = []
    if zero_volume:
        issues.append({"code": "zero_volume", "count": len(zero_volume), "examples": zero_volume[:5],
                       "message": "存在零成交量 K 线；量能确认可能无法使用"})
    if long_gaps:
        issues.append({"code": "long_calendar_gap", "count": len(long_gaps), "examples": long_gaps[:5],
                       "message": "相邻 K 线间隔异常长；请核查停牌或缺失数据"})
    if large_moves:
        issues.append({"code": "large_close_move", "count": len(large_moves), "examples": large_moves[:5],
                       "message": "存在大幅单期收盘变化；请核查公司行为、复权和真实行情"})
    return {"bar_count": len(rows), "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
            "interval": interval, "issues": issues, "status": "review" if issues else "ok"}


def from_yfinance(symbol: str, period: str = "2y", interval: str = "1d") -> tuple[list[dict], dict]:
    if period not in PERIODS or interval not in INTERVALS:
        raise ValueError("period 应为 6mo/1y/2y/5y；interval 应为 1d/1wk")
    import yfinance as yf

    ticker = yf.Ticker(normalize_symbol(symbol))
    frame = ticker.history(period=period, interval=interval, auto_adjust=True, actions=False, timeout=20)
    if frame.empty:
        raise ValueError("行情源没有返回价格。请检查代码或稍后重试，也可用 --csv 输入本地数据")
    rows = []
    for index, row in frame.iterrows():
        rows.append({
            "date": index.strftime("%Y-%m-%d"),
            "open": row["Open"], "high": row["High"], "low": row["Low"],
            "close": row["Close"], "volume": row["Volume"],
        })
    bars = validate_bars(rows)
    return bars, {
        "provider": "yfinance / Yahoo Finance",
        "symbol": normalize_symbol(symbol),
        "adjustment": "auto_adjust=True: OHLC 按拆股和分红调整；成交量为行情源原值",
        "interval": interval,
        "period": period,
        "as_of": bars[-1]["date"],
        "realtime": False,
    }
