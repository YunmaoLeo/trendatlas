import unittest
from datetime import date, timedelta

from stocktrend.calibrate import evaluate, fit, predict, sample


def bars(count):
    start = date(2023, 1, 1)
    return [{"date": (start + timedelta(days=i)).isoformat(), "open": 100 + i,
             "high": 101 + i, "low": 99 + i, "close": 100 + i, "volume": 1000 + i}
            for i in range(count)]


class CalibrationTests(unittest.TestCase):
    def test_prefix_features_are_unchanged_by_later_bars(self):
        first = sample(bars(80), "TEST", horizon=5, warmup=60)
        extended = sample(bars(100), "TEST", horizon=5, warmup=60)
        self.assertEqual(first, extended[:len(first)])
        self.assertEqual([r["date"] for r in first], [bars(80)[i]["date"] for i in range(59, 75, 5)])

    def test_time_split_rejects_label_overlap(self):
        rows = [{"date": "2024-12-01", "end_date": "2025-02-10", "up": 1,
                 "return": .1, "features": [1, 0, 0, 0, 0], "old_score": 60, "symbol": "X"},
                {"date": "2025-02-01", "end_date": "2025-03-01", "up": 0,
                 "return": -.1, "features": [-1, 0, 0, 0, 0], "old_score": 30, "symbol": "X"}]
        with self.assertRaises(ValueError):
            evaluate(rows, "2025-01-01", "2025-02-01")

    def test_positive_condition_never_gets_negative_weight(self):
        rows = [{"up": i % 2, "features": [1 - 2 * (i % 2), 0, 0, 0, 0]}
                for i in range(30)]
        weights = fit(rows)
        self.assertTrue(all(weight >= 0 for weight in weights[1:]))
        self.assertLessEqual(predict(weights, {"features": [1, 0, 0, 0, 0]}),
                             predict(weights, {"features": [0, 0, 0, 0, 0]}))


if __name__ == "__main__":
    unittest.main()
