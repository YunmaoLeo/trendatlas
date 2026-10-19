# 股市趋势技术分析 Lab

基于《股市趋势技术分析》（原书第 10 版）的**本地、可审计**股票图表工具。默认分析美股；支持 Yahoo 代码，如 `AAPL`、`0700.HK`、`600519.SS`。`KNOWLEDGE.md` 是规则来源与数学化流程；`COVERAGE.md` 逐章标出已实现和仍缺的内容；`stocktrend/engine.py` 是唯一的形态判定实现，UI 不自行猜测形态。

## 运行

```bash
cd /Users/lejieliu/Documents/stocks/stocktrend-lab
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn stocktrend.api:app --host 127.0.0.1 --port 8000
```

打开 [本地界面](http://127.0.0.1:8000)。图表库已包含在 `web/vendor/`，浏览器不需要 CDN。界面使用深色金融终端风格和 TradingView 开源 Lightweight Charts 图表组件，图表下方保留组件来源署名。

## Coding agent 调用

CLI 标准输出只有一份 JSON，错误写入标准错误并以非零状态退出：

```bash
.venv/bin/python -m stocktrend.cli AAPL --period 2y --interval 1d > aapl-analysis.json
.venv/bin/python -m stocktrend.cli MSFT --capital 100000 --risk-pct 1
.venv/bin/python -m stocktrend.cli AAPL --entry-date 2025-10-01
.venv/bin/python -m stocktrend.cli TEST --csv ./sample.csv
.venv/bin/python -m stocktrend.portfolio --csv ./holdings.csv --capital 100000
```

行情 CSV 列为 `date,open,high,low,close,volume`；组合 CSV 列为 `symbol,shares,last,stop`。REST API：`GET /api/analyze?symbol=AAPL&period=2y&interval=1d`，可选 `entry_date=YYYY-MM-DD`；OpenAPI 文档位于 `/docs`。请求参数经过白名单校验；无须 AI 模型或私有密钥。调用者应优先使用 `summary`、`trend`、`patterns`、`events`、`levels`、`risk`、`warnings`，并保留 `source.as_of` 与 `method`。`bars`/`indicators` 用于绘图。

## 数据与局限

- 历史价格通过开源 [yfinance](https://github.com/ranaroussi/yfinance) 获取。其背后的 Yahoo 数据接口供个人研究使用；该项目与 Yahoo 无关联。行情可延迟、缺失或被限流，界面显示实际最后交易日。取不到数据时 CLI 可用 CSV 离线复现。
- 默认 `auto_adjust=True`，价格按拆股与分红调整；成交量保持数据源数值。周线聚合由行情源完成。比较历史形态时需注意复权与真实成交价的差异。
- 本工具识别的是**规则匹配**，不是经样本外回测的预测模型。形态测算位和保护参考位均可能失效，跳空可能越过止损价。
- 已实现趋势线、支撑/阻力、头肩、双/三重顶底、三角形、箱体、楔形、缺口/反转日候选、ATR、保护参考与组合正常风险。原书与工程参数区别见 [KNOWLEDGE.md](./KNOWLEDGE.md)，逐章差距见 [COVERAGE.md](./COVERAGE.md)。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m stocktrend.cli AAPL --period 2y > /tmp/aapl-analysis.json
```
