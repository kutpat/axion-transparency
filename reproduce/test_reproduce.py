"""Pins the figures of 2026-09-05, so a change in the arithmetic is noticed.

    python -m unittest test_reproduce

ledger-2026-09-05.csv and figures-2026-09-05.json are the ledger and the
figures the site served that day, fetched a few seconds apart.
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import reproduce  # noqa: E402


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as handle:
        return handle.read()


class Day20260905(unittest.TestCase):
    def setUp(self):
        self.rows = reproduce.read_rows(load("ledger-2026-09-05.csv"))
        self.figures = reproduce.normalise(json.loads(load("figures-2026-09-05.json")))

    def test_every_published_figure_reproduces(self):
        results = reproduce.compare(self.rows, self.figures)
        self.assertEqual(len(results), 306)
        self.assertEqual([result.name for result in results if not result.ok], [])

    def test_ninety_day_headline(self):
        now = reproduce.parse_time(self.figures["generated_at"])
        ninety = reproduce.compute(self.rows, 90, now)
        self.assertEqual(ninety["closed_calls"], 229)
        self.assertEqual(ninety["r_qualified_calls"], 228)
        self.assertEqual(str(ninety["win_rate_pct"]), "65.14")
        self.assertEqual(str(ninety["cumulative_r"]), "99.61")
        self.assertEqual(str(ninety["average_r"]), "0.44")
        self.assertEqual(str(ninety["max_drawdown_r"]), "-5.26")
        self.assertEqual(str(ninety["cumulative_move_pct"]), "639.67")
        self.assertEqual(str(ninety["cumulative_follower_r"]), "90.74")

    def test_r_from_prices(self):
        checks = reproduce.check_rows(self.rows)
        self.assertEqual(len(checks), 228)
        # The CSV's entry is rounded to the tick, so one R lands 0.01 away.
        r_off = [check["row"]["signal_id"] for check in checks if check["r"] != check["row"]["r"]]
        self.assertEqual(r_off, ["AXN-2026-08-17-00269"])
        pct_off = [check for check in checks if check["pct"] != check["row"]["move_pct"]]
        self.assertEqual(len(pct_off), 18)


if __name__ == "__main__":
    unittest.main()
