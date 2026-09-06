"""Pins two days of figures, so a change in the arithmetic is noticed.

    python -m unittest test_reproduce

Each pair is the ledger and the figures the site served that day, fetched a few
seconds apart. 2026-09-05 came off the page's own payload, which is the shape
the fallback still reads; 2026-09-06 came off /performance/figures.json, schema
axion-performance-figures/1, and its CSV carries the three columns the follower
rebuild needs.
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


class PinnedDay:
    """The checks every pinned day makes. One class per day mixes it in."""

    day = None

    def setUp(self):
        self.rows = reproduce.read_rows(load("ledger-%s.csv" % self.day))
        self.figures = reproduce.normalise(json.loads(load("figures-%s.json" % self.day)))
        self.follower = reproduce.check_follower(self.rows, self.figures.get("follower_assumptions"))

    def test_every_published_figure_reproduces(self):
        results = reproduce.compare(self.rows, self.figures)
        self.assertEqual(len(results), 306)
        self.assertEqual([result.name for result in results if not result.ok], [])

    def test_r_from_prices(self):
        checks = reproduce.check_rows(self.rows)
        self.assertEqual(len(checks), 228)
        # The CSV's entry is rounded to the tick, so one R lands 0.01 away.
        r_off = [check["row"]["signal_id"] for check in checks if check["r"] != check["row"]["r"]]
        self.assertEqual(r_off, ["AXN-2026-08-17-00269"])
        pct_off = [check for check in checks if check["pct"] != check["row"]["move_pct"]]
        self.assertEqual(len(pct_off), 18)


class Day20260905(PinnedDay, unittest.TestCase):
    day = "2026-09-05"

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

    def test_the_follower_column_cannot_be_rebuilt(self):
        # That day's CSV had no entry_bps and no exit_bps, so the follower
        # figures stay the column as published and the totals sum it.
        self.assertEqual(self.follower, [])


class Day20260906(PinnedDay, unittest.TestCase):
    day = "2026-09-06"

    def test_the_figures_are_the_json_route(self):
        self.assertEqual(self.figures["schema"], "axion-performance-figures/1")
        self.assertEqual(len(self.figures["windows"]), 3)
        self.assertEqual(len(self.figures["windows"][0]["daily"]), 8)

    def test_ninety_day_headline(self):
        now = reproduce.parse_time(self.figures["generated_at"])
        ninety = reproduce.compute(self.rows, 90, now)
        self.assertEqual(ninety["closed_calls"], 229)
        self.assertEqual(ninety["r_qualified_calls"], 228)
        self.assertEqual(str(ninety["win_rate_pct"]), "65.14")
        self.assertEqual(str(ninety["cumulative_r"]), "101.72")
        self.assertEqual(str(ninety["average_r"]), "0.45")
        self.assertEqual(str(ninety["max_drawdown_r"]), "-5.26")
        self.assertEqual(str(ninety["cumulative_move_pct"]), "648.53")
        self.assertEqual(str(ninety["cumulative_follower_r"]), "92.85")

    def test_every_follower_row_rebuilds(self):
        self.assertEqual(len(self.follower), 228)
        differing = [
            check["row"]["signal_id"]
            for check in self.follower
            if check["follower_r"] != check["row"]["column_follower_r"]
            or check["follower_move_pct"] != check["row"]["column_follower_move_pct"]
            or check["cost_r"] != check["row"]["cost_r"]
        ]
        self.assertEqual(differing, [])
        unknown = [check for check in self.follower if check["entry_leg"] is None or check["exit_leg"] is None]
        self.assertEqual(unknown, [])


class Shapes(unittest.TestCase):
    def test_a_schema_it_does_not_know_is_refused(self):
        with self.assertRaises(SystemExit):
            reproduce.normalise({"schema": "axion-performance-figures/9", "windows": [], "generated_at": "x"})

    def test_a_shape_with_no_windows_is_refused(self):
        with self.assertRaises(SystemExit):
            reproduce.normalise({"generatedAt": "x", "openCalls": 1})


if __name__ == "__main__":
    unittest.main()
