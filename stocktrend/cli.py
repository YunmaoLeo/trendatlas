"""Stable command-line contract for coding agents."""

import argparse
import json
import sys

from .data import from_csv, from_yfinance, normalize_symbol
from .engine import analyze


def main() -> int:
    parser = argparse.ArgumentParser(description="书籍规则驱动的股票趋势分析，stdout 输出 JSON")
    parser.add_argument("symbol", help="例如 AAPL、MSFT、0700.HK、600519.SS")
    parser.add_argument("--period", default="2y", choices=["6mo", "1y", "2y", "5y"])
    parser.add_argument("--interval", default="1d", choices=["1d", "1wk"])
    parser.add_argument("--csv", help="离线 OHLCV CSV 文件路径")
    parser.add_argument("--capital", type=float, help="账户资金，用于计算可承受数量")
    parser.add_argument("--risk-pct", type=float, default=1.0, help="每次分析的账户风险上限百分比，默认 1")
    parser.add_argument("--entry-date", help="假设建仓日期 YYYY-MM-DD，用于基准点动态保护示例")
    args = parser.parse_args()
    try:
        symbol = normalize_symbol(args.symbol)
        if args.csv:
            bars = from_csv(args.csv)
            source = {"provider": "local CSV", "symbol": symbol, "as_of": bars[-1]["date"], "interval": args.interval, "adjustment": "由输入文件决定", "realtime": False}
        else:
            bars, source = from_yfinance(symbol, args.period, args.interval)
        result = analyze(bars, symbol=symbol, source=source, capital=args.capital,
                         risk_pct=args.risk_pct, entry_date=args.entry_date)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
