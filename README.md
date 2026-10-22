# 股市趋势技术分析 Lab

基于《股市趋势技术分析》（原书第 10 版）的**本地、可审计**股票图表工具。默认分析美股；支持 Yahoo 代码，如 `AAPL`、`0700.HK`、`600519.SS`。`KNOWLEDGE.md` 是规则来源与数学化流程；`COVERAGE.md` 逐章标出已实现和仍缺的内容；`stocktrend/engine.py` 是唯一的形态判定实现，UI 不自行猜测形态。

## 运行

安装、启动和停止命令见 [启动说明](./START.md)。默认启动地址为 [http://127.0.0.1:8001](http://127.0.0.1:8001)。图表库已包含在 `web/vendor/`，浏览器不需要 CDN。界面使用深色金融终端风格和 TradingView 开源 Lightweight Charts 图表组件，图表下方保留组件来源署名。

## Coding agent 调用

CLI 标准输出只有一份 JSON，错误写入标准错误并以非零状态退出：

```bash
.venv/bin/python -m stocktrend.cli AAPL --period 2y --interval 1d > /tmp/aapl-analysis.json
.venv/bin/python -m stocktrend.cli MSFT --capital 100000 --risk-pct 1
.venv/bin/python -m stocktrend.cli AAPL --entry-date 2025-10-01
.venv/bin/python -m stocktrend.cli TEST --csv ./sample.csv
.venv/bin/python -m stocktrend.portfolio --csv ./holdings.csv --capital 100000
.venv/bin/python -m stocktrend.replay AAPL --period 5y --horizon 20 --warmup 120 > /tmp/aapl-replay.json
.venv/bin/python -m stocktrend.replay TEST --csv ./sample.csv --horizon 20
.venv/bin/python -m stocktrend.calibrate --symbols VOO QQQ NVDA MU --horizon 20
```

行情 CSV 列为 `date,open,high,low,close,volume`；组合 CSV 列为 `symbol,shares,last,stop`。REST API：`GET /api/analyze?symbol=AAPL&period=2y&interval=1d`，可选 `entry_date=YYYY-MM-DD`；历史回放：`GET /api/replay?symbol=AAPL&period=2y&horizon=20&warmup=120`。OpenAPI 文档位于 `/docs`。请求参数经过白名单校验；无须 AI 模型或私有密钥。调用者应优先使用 `trend_outlook`、`patterns`、`events`、`levels`、`risk`、`warnings`，并保留 `source.as_of` 与 `method`。`trend_outlook.current`、`confidence_score`、`expected`、`watch`、`if_holds`、`if_breaks` 是给人读的趋势判断与条件情形；`buy_reference` 仍是单独的上升趋势结构分。`bars`/`indicators` 用于绘图。

## 数据与局限

- 历史价格通过开源 [yfinance](https://github.com/ranaroussi/yfinance) 获取。其背后的 Yahoo 数据接口供个人研究使用；该项目与 Yahoo 无关联。行情可延迟、缺失或被限流，界面显示实际最后交易日。取不到数据时 CLI 可用 CSV 离线复现。
- 默认 `auto_adjust=True`，价格按拆股与分红调整；成交量保持数据源数值。周线聚合由行情源完成。比较历史形态时需注意复权与真实成交价的差异。
- 本工具识别的是**规则匹配**，不是经样本外回测的预测模型。形态测算位和保护参考位均可能失效，跳空可能越过止损价。
- `buy_reference.score` 现在是 **上升趋势确信度**（0–100）：四项当前结构条件决定分数上限，价格到最近确认波谷或有效上升趋势线的距离以 ATR20 衡量；两者取较低值。越靠近转折参照位，分数越低。它只描述当前图形结构，不使用历史买点结果，不是未来上涨概率或买入指令。计算见 [KNOWLEDGE.md](./KNOWLEDGE.md) 第 17 节。旧买入分与样本外校准保留为研究归档，见 [CALIBRATION.md](./CALIBRATION.md)。
- `trend_outlook.confidence_score` 是页面显示的**当前方向把握分**。已确认上涨时沿用上升结构分，已确认下跌时按对称规则计算；波段未确认时只显示较强一侧的方向线索，双方无优势才为 0。`expected` 和两个条件情形只是当前图形的推演，不是确定预测或收益概率。规则见 [KNOWLEDGE.md](./KNOWLEDGE.md) 第 18 节。
- 历史回放逐日截断数据来生成信号，再用随后固定期数检验方向化价格变化；输出不是交易盈亏。复权历史可能被未来公司行为回溯改写，同一时段的形态窗口也可能重叠。详见 [REPLAY.md](./REPLAY.md)。
- 已实现趋势线、支撑/阻力、头肩、双/三重顶底、三角形、箱体、楔形、缺口/反转日候选、ATR、保护参考与组合正常风险。原书与工程参数区别见 [KNOWLEDGE.md](./KNOWLEDGE.md)，逐章差距见 [COVERAGE.md](./COVERAGE.md)。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m stocktrend.cli AAPL --period 2y > /tmp/aapl-analysis.json
```
