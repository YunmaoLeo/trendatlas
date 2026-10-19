(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, digits = 2) => Number.isFinite(Number(n)) ? Number(n).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '—';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {symbol:'AAPL', period:'2y', interval:'1d', entryDate:'', result:null, loading:false, logarithmic:false};
  let toastTimer, requestId = 0, chart, candles, volume, ma50, ma200, trendSeries, priceLines = [];

  function toast(message) {
    $('toast').textContent = message;
    $('toast').classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('toast').classList.remove('visible'), 3500);
  }

  function initChart() {
    const container = $('chart');
    chart = LightweightCharts.createChart(container, {
      width: container.clientWidth, height: container.clientHeight,
      layout: {background:{type:'solid',color:'#121925'},textColor:'#889ab2',fontFamily:'Inter, -apple-system, sans-serif',fontSize:11,attributionLogo:false},
      grid: {vertLines:{color:'#26314255'},horzLines:{color:'#26314277'}},
      crosshair:{vertLine:{color:'#6889b4',width:1,style:2,labelBackgroundColor:'#38577e'},horzLine:{color:'#6889b4',width:1,style:2,labelBackgroundColor:'#38577e'}},
      rightPriceScale:{borderColor:'#354155',scaleMargins:{top:0.08,bottom:0.25}},
      timeScale:{borderColor:'#354155',timeVisible:false,rightOffset:5,barSpacing:7,minBarSpacing:3},
      localization:{locale:'zh-CN'},
    });
    candles = chart.addSeries(LightweightCharts.CandlestickSeries, {upColor:'#16c79a',downColor:'#f26472',borderVisible:false,wickUpColor:'#16c79a',wickDownColor:'#f26472',priceLineVisible:false,lastValueVisible:true});
    volume = chart.addSeries(LightweightCharts.HistogramSeries, {priceFormat:{type:'volume'},priceScaleId:'',priceLineVisible:false,lastValueVisible:false});
    volume.priceScale().applyOptions({scaleMargins:{top:0.79,bottom:0.015}});
    ma50 = chart.addSeries(LightweightCharts.LineSeries, {color:'#568bff',lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    ma200 = chart.addSeries(LightweightCharts.LineSeries, {color:'#e7b966',lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    trendSeries = chart.addSeries(LightweightCharts.LineSeries, {color:'#a5b5d8',lineWidth:2,lineStyle:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    chart.subscribeCrosshairMove(param => {
      if (!state.result) return;
      const bar = param.seriesData?.get(candles);
      if (bar) $('legend-ohlc').textContent = `O ${fmt(bar.open)}   H ${fmt(bar.high)}   L ${fmt(bar.low)}   C ${fmt(bar.close)}`;
      else updateLegend(state.result.bars.at(-1));
    });
    new ResizeObserver(() => chart.applyOptions({width:container.clientWidth,height:container.clientHeight})).observe(container);
  }

  function updateLegend(bar) {
    if (bar) $('legend-ohlc').textContent = `O ${fmt(bar.open)}   H ${fmt(bar.high)}   L ${fmt(bar.low)}   C ${fmt(bar.close)}`;
  }

  function drawChart(result) {
    const bars = result.bars;
    candles.setData(bars.map(b => ({time:b.date,open:b.open,high:b.high,low:b.low,close:b.close})));
    volume.setData(bars.map(b => ({time:b.date,value:b.volume,color:b.close>=b.open?'#187f6b99':'#a9485899'})));
    ma50.setData(result.indicators.ma50.map(p => ({time:p.date,value:p.value})));
    ma200.setData(result.indicators.ma200.map(p => ({time:p.date,value:p.value})));
    const line = result.trend.trendline;
    trendSeries.setData(line && line.to_price > 0 ? [{time:line.from,value:line.from_price},{time:line.to,value:line.to_price}] : []);
    for (const line of priceLines) candles.removePriceLine(line);
    priceLines = [];
    const add = (price, color, title, style = 2) => {
      if (price > 0) priceLines.push(candles.createPriceLine({price,color,lineWidth:1,lineStyle:style,axisLabelVisible:true,title}));
    };
    add(result.levels.support.price,'#148c75','支撑');
    add(result.levels.resistance.price,'#b25965','阻力');
    add(result.risk.protective_reference,'#d4a64c','保护');
    const primary = result.patterns.find(p => p.status === '已确认');
    if (primary) add(primary.trigger,'#638dff','形态突破',0);
    chart.timeScale().fitContent();
    if (bars.length > 170) chart.timeScale().setVisibleLogicalRange({from:bars.length-160,to:bars.length+4});
  }

  function renderPatterns(result) {
    $('pattern-count').textContent = `${result.patterns.length} 个匹配 · 仅显示完整结构`;
    if (!result.patterns.length) {
      $('patterns').innerHTML = '<div class="empty-card">当前窗口没有满足结构条件的形态。继续观察波段、价位与成交量。</div>';
      return;
    }
    $('patterns').innerHTML = result.patterns.slice(0, 4).map(p => {
      const description = p.evidence.slice(0,2).join('；');
      const warning = p.warnings.length ? ` · ${p.warnings[0]}` : '';
      return `<article class="pattern-card ${p.direction === 'up' ? 'up' : p.direction === 'down' ? 'down' : ''}">
        <div class="card-top"><h3>${esc(p.name)}</h3><span class="status-pill ${p.status==='已确认'?'confirmed':''}">${esc(p.status)}</span></div>
        <p>${esc(description)}</p>
        <div class="numbers"><div><small>突破界线</small><strong>${fmt(p.trigger)}</strong></div><div><small>幅度测算位</small><strong>${p.measured_target == null ? '—' : fmt(p.measured_target)}</strong></div></div>
        <div class="card-foot">${esc(p.start_date)} — ${esc(p.end_date)} · 第 ${p.book_chapters.join('、')} 章 · ${esc(p.target_state)}${esc(warning)}</div>
      </article>`;
    }).join('');
  }

  function renderEvents(result) {
    const events = result.events || [];
    $('event-count').textContent = `${events.length} 条近期事件 · 仅显示最近 4 条`;
    $('events').innerHTML = events.length ? events.slice(0,4).map(event => `<div class="event-row ${event.direction==='up'?'up':'down'}"><div><strong>${esc(event.type)}</strong><span>${esc(event.date)} · ${esc(event.context)}</span></div><div class="event-state"><strong>${esc(event.status)}</strong><small>${event.magnitude_pct == null ? '' : `区间 ${fmt(event.magnitude_pct)}%`}</small></div></div>`).join('') : '<div class="empty-card">近 45 根 K 线未出现满足条件的缺口或关键反转日候选。</div>';
  }

  function render(result) {
    state.result = result;
    $('ticker-title').innerHTML = `${esc(result.symbol)} <span>· ${result.source.interval === '1wk' ? '周线' : '日线'}</span>`;
    $('ticker-meta').textContent = `${result.source.provider}  /  调整价格  /  K 线日期标签 ${result.last.date}`;
    $('legend-ticker').textContent = result.symbol;
    $('last-price').textContent = fmt(result.last.close);
    const change = result.last.change_pct;
    $('last-change').textContent = `${change >= 0 ? '+' : ''}${fmt(change)}%  最近一期`;
    $('last-change').className = change >= 0 ? 'positive' : 'negative';
    $('as-of-top').textContent = result.last.date;
    $('as-of').textContent = result.last.date;
    $('bar-count').textContent = `${result.last.bar_count} 根`;
    $('volume-ratio').textContent = result.last.volume_ratio_20 == null ? '无数据' : `${fmt(result.last.volume_ratio_20)} ×`;
    $('data-source').textContent = `${result.source.provider} · 非实时`;
    $('summary').textContent = result.summary;
    const direction = result.trend.direction;
    $('trend-badge').textContent = direction + (result.trend.trendline?.broken ? ` · ${result.trend.trendline.quality}穿透` : '');
    $('trend-badge').className = `trend-badge ${direction === '上升趋势' ? 'up' : direction === '下降趋势' ? 'down' : ''}`;
    const level = result.levels;
    $('levels').innerHTML = `<div class="level-row"><span>上方阻力<br><small>${esc(level.resistance.method)}</small></span><strong class="negative">${fmt(level.resistance.price)}</strong></div><div class="level-row"><span>下方支撑<br><small>${esc(level.support.method)}</small></span><strong class="positive">${fmt(level.support.price)}</strong></div>`;
    const risk = result.risk;
    $('risk').innerHTML = `<div class="risk-value">${fmt(risk.protective_reference)}</div><small>${esc(risk.method)} · 距现价 ${fmt(risk.distance_pct)}%</small><small>ATR 20 ${fmt(risk.atr20)} · 2× ATR 幅度 ${fmt(risk.atr20_x2_distance)}</small>${risk.position_sizing ? `<small>风险预算 ${fmt(risk.position_sizing.risk_budget)} · 风险上限 ${risk.position_sizing.max_shares_by_risk} 股</small>` : ''}`;
    const ladder = risk.basis_ladder;
    $('ladder-summary').textContent = ladder ? `假设 ${ladder.entry_date} 收盘入场 · 波谷法 ${fmt(ladder.variant1.stop)}${ladder.variant1.triggered_date ? `（${ladder.variant1.triggered_date} 触及）` : ''} · 新高增强法 ${fmt(ladder.variant2.stop)}${ladder.variant2.triggered_date ? `（${ladder.variant2.triggered_date} 触及）` : ''}。穿越价并非成交价。` : '选择历史建仓日后，展示两种基准点保护路径。仅作规则演示。';
    $('warnings').innerHTML = result.warnings.length ? result.warnings.map(w => `<div class="warning-item">${esc(w)}</div>`).join('') : '<div class="warning-item">数据时点正常；仍需留意假突破和复权价格差异。</div>';
    updateLegend(result.bars.at(-1));
    renderPatterns(result);
    renderEvents(result);
    drawChart(result);
  }

  async function load() {
    const id = ++requestId;
    state.loading = true;
    $('summary').textContent = '正在获取历史价格并匹配书籍规则…';
    $('ticker-meta').textContent = '正在获取历史日线…';
    const params = new URLSearchParams({symbol:state.symbol,period:state.period,interval:state.interval});
    if (state.entryDate) params.set('entry_date',state.entryDate);
    try {
      const response = await fetch(`/api/analyze?${params}`);
      const result = await response.json();
      if (id !== requestId) return;
      if (!response.ok) throw new Error(result.detail || '未知错误');
      render(result);
      history.replaceState(null,'',`?${params}`);
    } catch (error) {
      if (id !== requestId) return;
      $('summary').textContent = '行情读取失败。请检查股票代码、网络或稍后重试。';
      $('ticker-meta').textContent = String(error.message);
      toast(`无法载入：${error.message}`);
    } finally { if (id === requestId) state.loading = false; }
  }

  function select(group, attr, value) {
    document.querySelectorAll(`#${group} button`).forEach(b => b.classList.toggle('selected', b.dataset[attr] === value));
  }

  $('search-form').addEventListener('submit', e => {
    e.preventDefault();
    const value = $('symbol-input').value.trim().toUpperCase();
    if (!value) return toast('请输入股票代码');
    state.symbol = value;
    load();
  });
  $('period-control').addEventListener('click', e => {
    const value = e.target.dataset.period;
    if (!value) return;
    state.period = value;
    if (value === '6mo' && state.interval === '1wk') {
      state.interval = '1d'; select('interval-control','interval','1d'); toast('6M 区间已切换为日线，以提供足够的 K 线');
    }
    select('period-control','period',value); load();
  });
  $('interval-control').addEventListener('click', e => {
    const value = e.target.dataset.interval;
    if (!value) return;
    state.interval = value; select('interval-control','interval',value);
    if (value === '1wk' && state.period === '6mo') {
      state.period = '1y'; select('period-control','period','1y'); toast('周线至少需要约 50 根 K 线，已切换至 1Y');
    }
    load();
  });
  document.querySelectorAll('.watchlist button').forEach(button => button.addEventListener('click', () => {
    state.symbol = button.dataset.symbol; state.entryDate = ''; $('entry-date').value = ''; $('symbol-input').value = state.symbol; load();
  }));
  $('entry-form').addEventListener('submit', e => {
    e.preventDefault(); state.entryDate = $('entry-date').value; load();
  });
  $('log-toggle').addEventListener('click', () => {
    state.logarithmic = !state.logarithmic;
    chart.priceScale('right').applyOptions({mode:state.logarithmic ? LightweightCharts.PriceScaleMode.Logarithmic : LightweightCharts.PriceScaleMode.Normal});
    $('log-toggle').setAttribute('aria-pressed',String(state.logarithmic));
    $('log-toggle').style.color = state.logarithmic ? '#9dbaff' : '';
  });
  $('export-json').addEventListener('click', () => {
    if (!state.result) return toast('请先完成分析');
    const blob = new Blob([JSON.stringify(state.result,null,2)],{type:'application/json'});
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = `${state.result.symbol}-${state.result.last.date}-trend.json`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
  });
  $('rail-rules').addEventListener('click', () => $('rules-dialog').showModal());
  $('method-button').addEventListener('click', () => $('rules-dialog').showModal());
  $('close-rules').addEventListener('click', () => $('rules-dialog').close());
  const qs = new URLSearchParams(location.search);
  if (qs.get('symbol')) state.symbol = qs.get('symbol').toUpperCase();
  if (['6mo','1y','2y','5y'].includes(qs.get('period'))) state.period = qs.get('period');
  if (['1d','1wk'].includes(qs.get('interval'))) state.interval = qs.get('interval');
  if (/^\d{4}-\d{2}-\d{2}$/.test(qs.get('entry_date') || '')) state.entryDate = qs.get('entry_date');
  $('symbol-input').value = state.symbol;
  $('entry-date').value = state.entryDate;
  select('period-control','period',state.period);
  select('interval-control','interval',state.interval);
  initChart();
  load();
})();
