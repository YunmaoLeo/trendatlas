"""Chapter 42 ordinary portfolio risk from explicit, user-supplied long positions."""

import argparse
import csv
import json
import math
import sys


def assess(positions: list[dict], capital: float) -> dict:
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("capital 必须是大于 0 的有限数")
    rows = []
    warnings = []
    for raw in positions:
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError("每行都需要 symbol")
        try:
            shares, last, stop = (float(raw[key]) for key in ("shares", "last", "stop"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{symbol}: 需要数值列 shares,last,stop") from exc
        if not all(math.isfinite(value) for value in (shares, last, stop)) or shares <= 0 or last <= 0 or stop <= 0:
            raise ValueError(f"{symbol}: shares、last、stop 必须是正有限数")
        if stop >= last:
            warnings.append(f"{symbol}: 止损位已达到或高于现价，请核查持仓状态")
        normal_risk = shares * max(last - stop, 0)
        rows.append({"symbol": symbol, "shares": shares, "last": last, "stop": stop,
                     "market_value": round(shares * last, 2), "ordinary_risk": round(normal_risk, 2)})
    total = sum(row["ordinary_risk"] for row in rows)
    market_value = sum(row["market_value"] for row in rows)
    for row in rows:
        row["risk_share_pct"] = round(row["ordinary_risk"] / total * 100, 2) if total else 0
    return {"schema_version": "1.0", "capital": capital, "positions": rows,
            "portfolio_ordinary_risk": round(total, 2),
            "portfolio_risk_factor_pct": round(total / capital * 100, 2),
            "gross_market_value": round(market_value, 2),
            "gross_exposure_pct": round(market_value / capital * 100, 2),
            "warnings": warnings,
            "method": {"book_chapter": 42, "formula": "POR=sum(shares*max(last-stop,0)); PRF=POR/capital",
                       "limitations": "只计算多头仓位到止损价的正常风险，不估计跳空、流动性、相关性、时间风险、巨灾风险或最大回撤。"}}


def main() -> int:
    parser = argparse.ArgumentParser(description="从本地持仓 CSV 计算原书第42章的组合正常风险")
    parser.add_argument("--csv", required=True, help="包含 symbol,shares,last,stop 的 CSV")
    parser.add_argument("--capital", required=True, type=float, help="账户总资金")
    args = parser.parse_args()
    try:
        with open(args.csv, newline="", encoding="utf-8-sig") as stream:
            positions = list(csv.DictReader(stream))
        if not positions:
            raise ValueError("持仓 CSV 为空")
        print(json.dumps(assess(positions, args.capital), ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
