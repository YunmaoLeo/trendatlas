import unittest
from datetime import date, timedelta

from stocktrend.data import audit_bars, normalize_symbol, validate_bars
from stocktrend.engine import _pivots, analyze
from stocktrend.portfolio import assess
from stocktrend.replay import replay


def bars_from_points(points, volume=1000):
    """Synthetic path with chosen turning points and valid OHLC geometry."""
    closes = []
    for (start_i, start_v), (end_i, end_v) in zip(points, points[1:]):
        for i in range(start_i, end_i):
            closes.append(start_v + (end_v - start_v) * (i - start_i) / (end_i - start_i))
    closes.append(points[-1][1])
    out = []
    first_day = date(2026, 1, 1)
    for i, close in enumerate(closes):
        op = close
        out.append({"date": (first_day + timedelta(days=i)).isoformat(), "open": op,
                    "high": max(op, close) + .1, "low": min(op, close) - .1,
                    "close": close, "volume": volume})
    return out


class EngineTest(unittest.TestCase):
    def test_symbol_normalization(self):
        self.assertEqual(normalize_symbol("aapl"), "AAPL")
        self.assertEqual(normalize_symbol("600519"), "600519.SS")
        self.assertEqual(normalize_symbol("700"), "0700.HK")
        with self.assertRaises(ValueError):
            normalize_symbol("AAPL; rm -rf")

    def test_no_future_pivot(self):
        bars = bars_from_points([(0,100),(20,120),(40,100),(60,130)])
        self.assertTrue(all(p["i"] <= len(bars) - 4 for p in _pivots(bars)))

    def test_double_top_confirmed_after_neckline_break(self):
        bars = bars_from_points([(0,90),(20,100),(35,120),(55,100),(75,121),(86,94)])
        result = analyze(bars, "TEST")
        tops = [p for p in result["patterns"] if p["name"] == "双重顶"]
        self.assertTrue(tops, result["patterns"])
        self.assertEqual(tops[0]["status"], "已确认")
        self.assertAlmostEqual(tops[0]["trigger"], 99.9, delta=1)

    def test_double_bottom_needs_volume(self):
        bars = bars_from_points([(0,120),(20,110),(35,90),(55,110),(75,91),(86,116)])
        result = analyze(bars, "TEST")
        bottoms = [p for p in result["patterns"] if p["name"] == "双重底"]
        self.assertTrue(bottoms, result["patterns"])
        self.assertEqual(bottoms[0]["status"], "待确认")
        self.assertTrue(any("成交量" in w for w in bottoms[0]["warnings"]))
        for bar in bars[79:]:
            bar["volume"] = 3000
        result = analyze(bars, "TEST")
        bottoms = [p for p in result["patterns"] if p["name"] == "双重底"]
        self.assertEqual(bottoms[0]["status"], "已确认")

    def test_invalid_ohlc_rejected(self):
        bars = bars_from_points([(0,100),(50,110)])
        bars[4]["high"] = 1
        with self.assertRaises(ValueError):
            validate_bars(bars)

    def test_old_pattern_expires(self):
        bars = bars_from_points([(0,90),(20,100),(35,120),(55,100),(75,121),(86,94),(170,95)])
        result = analyze(bars, "TEST")
        self.assertFalse(any(p["name"] == "双重顶" for p in result["patterns"]))

    def test_rectangle_requires_breakout_volume(self):
        bars = bars_from_points([(0,90),(20,110),(35,100),(50,110),(65,100),(80,116)])
        bars[-1]["volume"] = 5000
        result = analyze(bars, "TEST")
        boxes = [p for p in result["patterns"] if p["name"] == "箱体"]
        self.assertEqual(boxes[0]["status"], "已确认")
        self.assertGreater(boxes[0]["measured_target"], boxes[0]["trigger"])

    def test_triple_top_confirmed(self):
        bars = bars_from_points([(0,90),(20,100),(35,120),(50,100),(65,121),(80,100),(95,120),(110,94)])
        result = analyze(bars, "TEST")
        tops = [p for p in result["patterns"] if p["name"] == "三重顶"]
        self.assertEqual(tops[0]["status"], "已确认")

    def test_gap_event_tracks_later_fill(self):
        bars = bars_from_points([(0,100),(60,100)])
        bars[51].update(open=105,high=105.1,low=104.9,close=105)
        bars[52].update(open=106,high=106.1,low=105.9,close=106)
        events = analyze(bars,"TEST")["events"]
        gap = next(e for e in events if e["type"] == "价格区间缺口" and e["date"] == bars[51]["date"])
        self.assertEqual(gap["status"], "已回补")
        self.assertEqual(gap["filled_date"], bars[53]["date"])

    def test_portfolio_ordinary_risk(self):
        result = assess([{"symbol":"AAPL","shares":"10","last":"120","stop":"100"},
                         {"symbol":"MSFT","shares":"5","last":"80","stop":"70"}], 5000)
        self.assertEqual(result["portfolio_ordinary_risk"], 250)
        self.assertEqual(result["portfolio_risk_factor_pct"], 5)
        with self.assertRaises(ValueError):
            assess([{"symbol":"AAPL","shares":"nan","last":"120","stop":"100"}], 5000)

    def test_new_high_ladder_compounds_from_reference_high(self):
        bars = bars_from_points([(0,90),(10,100),(40,110),(60,120)])
        ladder = analyze(bars, "TEST", entry_date=bars[10]["date"])["risk"]["basis_ladder"]
        self.assertTrue(any(update["reason"] == "越过前高3%" for update in ladder["recent_updates"]))
        self.assertGreaterEqual(ladder["variant2"]["stop"], ladder["variant1"]["stop"])

    def test_replay_signal_uses_only_historical_prefix(self):
        bars = bars_from_points([(0,90),(20,100),(35,120),(55,100),(75,121),
                                 (86,94),(120,91),(150,93)])
        early = replay(bars[:110], "TEST", horizon=10, warmup=60)
        later = replay(bars, "TEST", horizon=10, warmup=60)
        self.assertEqual(early["signal_count"], 1)
        self.assertEqual(early["signals"][0], later["signals"][0])
        self.assertEqual(early["signals"][0]["pattern"], "双重顶")
        self.assertTrue(early["signals"][0]["outcome"]["complete"])

    def test_data_audit_flags_without_dropping_bars(self):
        bars = bars_from_points([(0,100),(60,100)])
        bars[20]["volume"] = 0
        bars[30].update(open=150, high=151, low=149, close=150)
        audit = audit_bars(bars)
        self.assertEqual(audit["bar_count"], len(bars))
        self.assertEqual({issue["code"] for issue in audit["issues"]},
                         {"zero_volume", "large_close_move"})


if __name__ == "__main__":
    unittest.main()
