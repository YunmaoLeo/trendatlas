"""Local-only HTTP API and chart UI."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .data import from_yfinance, normalize_symbol
from .engine import analyze
from .replay import replay

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="股市趋势技术分析 Lab", version="1.6.0")
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


@app.get("/")
def home():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/analyze")
def analyze_symbol(
    symbol: str = Query(default="AAPL", min_length=1, max_length=24),
    period: str = Query(default="2y", pattern="^(6mo|1y|2y|5y)$"),
    interval: str = Query(default="1d", pattern="^(1d|1wk)$"),
    capital: float | None = Query(default=None, gt=0),
    risk_pct: float = Query(default=1, gt=0, le=5),
    entry_date: str | None = Query(default=None, pattern="^\\d{4}-\\d{2}-\\d{2}$"),
):
    try:
        normalized = normalize_symbol(symbol)
        bars, source = from_yfinance(normalized, period, interval)
        return analyze(bars, normalized, source, capital, risk_pct, entry_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"行情获取失败: {exc}") from exc


@app.get("/api/replay")
def replay_symbol(
    symbol: str = Query(default="AAPL", min_length=1, max_length=24),
    period: str = Query(default="2y", pattern="^(6mo|1y|2y|5y)$"),
    interval: str = Query(default="1d", pattern="^(1d|1wk)$"),
    horizon: int = Query(default=20, ge=5, le=120),
    warmup: int = Query(default=120, ge=50),
):
    try:
        normalized = normalize_symbol(symbol)
        bars, source = from_yfinance(normalized, period, interval)
        return replay(bars, normalized, horizon, warmup, interval, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"历史回放失败: {exc}") from exc
