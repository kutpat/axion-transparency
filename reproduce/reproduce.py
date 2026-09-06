#!/usr/bin/env python3
"""Recompute every figure on axioncrypto.net/performance from the public CSV.

    python reproduce.py
    python reproduce.py --csv ledger-2026-09-05.csv --figures figures-2026-09-05.json
    python reproduce.py --save-csv today.csv --save-figures today.json

Downloads the ledger and the figures the site publishes, recomputes the
figures from the ledger, and prints the two side by side. All arithmetic is in
Decimal; the only rounding is the site's own, two places, half up. README.md
beside this file has the formulas.
"""

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.request import Request, urlopen

SITE = "https://axioncrypto.net"
CSV_URL = SITE + "/performance/ledger.csv"
FIGURES_URL = SITE + "/performance/figures.json"
PAGE_URL = SITE + "/performance"
FIGURES_SCHEMA = "axion-performance-figures/1"
WINDOWS = (7, 30, 90)
CENT = Decimal("0.01")
ONE = Decimal("1")
BUCKETS_R = (-2, -1, 0, 1, 2, 3, 4)
BUCKETS_PCT = (-10, -5, 0, 5, 10, 15, 20)
FIGURES = (
    ("calls closed", "closed_calls"),
    ("wins", "wins"),
    ("losses", "losses"),
    ("break-evens", "breakevens"),
    ("win rate %", "win_rate_pct"),
    ("cumulative R", "cumulative_r"),
    ("R-qualified calls", "r_qualified_calls"),
    ("average R", "average_r"),
    ("best call R", "best_call_r"),
    ("max drawdown R", "max_drawdown_r"),
    ("cumulative %", "cumulative_move_pct"),
    ("average %", "average_move_pct"),
    ("best call %", "best_call_pct"),
    ("max drawdown %", "max_drawdown_pct"),
    ("follower cumulative R", "cumulative_follower_r"),
    ("follower average R", "average_follower_r"),
    ("follower cumulative %", "cumulative_follower_move_pct"),
    ("follower average %", "average_follower_move_pct"),
)


# --- reading -----------------------------------------------------------------


def http(url):
    request = Request(url, headers={"User-Agent": "axion-transparency-reproduce"})
    with urlopen(request, timeout=60) as response:
        return response.read(), response.headers.get("Content-Type", "")


def decimal(text):
    return Decimal(text) if text not in (None, "") else None


def parse_time(text):
    text = text.strip().replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        fraction = re.match(r"\d*", tail).group(0)
        text = head + "." + fraction.ljust(6, "0")[:6] + tail[len(fraction) :]
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def read_rows(text):
    """The ledger. Columns are read by name, so appended columns do not matter."""
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        rows.append(
            {
                "closed_at": parse_time(record["closed_at"]),
                "symbol": record["symbol"],
                "side": record["side"],
                "analyst": record["analyst"].strip(),
                "outcome": record["outcome"],
                "signal_id": record.get("signal_id") or record["trade_id"],
                "entry": decimal(record["entry_price"]),
                "stop": decimal(record.get("stop_used")),
                "exit": decimal(record["exit_price"]),
                "r": decimal(record["r_multiple"]),
                "move_pct": decimal(record["move_pct"]),
                "follower_r": decimal(record.get("follower_r")),
                "follower_move_pct": decimal(record.get("follower_move_pct")),
                "cost_r": decimal(record.get("cost_r")),
                "entry_bps": decimal(record.get("entry_bps")),
                "exit_bps": decimal(record.get("exit_bps")),
            }
        )
    return rows


def snake(obj):
    """Key names as Core writes them, whichever way the site spelled them."""
    if isinstance(obj, dict):
        return {re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): snake(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [snake(value) for value in obj]
    return obj


def normalise(figures):
    """Both shapes the site serves, in one form: windows, each with a daily series.

    /performance/figures.json is schema axion-performance-figures/1: snake_case,
    with windows[] and daily[]. The page carries the same figures in its own
    payload under ranges[] and dailyR[] and names no schema, and that is what the
    fallback reads when the route does not answer. Only a schema name this script
    does not know is refused.
    """
    if "performance" in figures and "ranges" not in figures and "windows" not in figures:
        figures = figures["performance"]
    figures = snake(figures)
    schema = figures.get("schema")
    if schema is not None and schema != FIGURES_SCHEMA:
        raise SystemExit("the figures are schema %r, which is not one this script knows" % schema)
    windows = figures.get("windows") or figures.get("ranges")
    if not windows:
        raise SystemExit("the figures carry no windows; the shape is not one this script knows")
    figures["windows"] = [with_daily(window) for window in windows]
    return figures


def with_daily(window):
    """One window, its daily series under one name whichever shape named it."""
    window = dict(window)
    window["daily"] = window.get("daily") or window.get("daily_r") or []
    return window


def figures_from_page(html):
    """The page carries the figures it renders in its React payload."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    text = "".join(json.loads('"' + chunk + '"') for chunk in chunks)
    for line in text.split("\n"):
        if '"rQualifiedCalls"' not in line:
            continue
        found = _find_figures(json.loads(line.split(":", 1)[1]))
        if found:
            return found
    raise SystemExit("could not find the performance figures in the page")


def _find_figures(node):
    if isinstance(node, dict):
        if "ranges" in node and "generatedAt" in node:
            return node
        for value in node.values():
            found = _find_figures(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_figures(value)
            if found:
                return found
    return None


def fetch_figures():
    data, content_type = http(FIGURES_URL)
    if "json" in content_type:
        return json.loads(data), FIGURES_URL
    html, _ = http(PAGE_URL)
    return figures_from_page(html.decode("utf-8")), PAGE_URL


# --- the arithmetic ----------------------------------------------------------


def rounded(value):
    """The site's rounding: two places, half up, and never a negative zero."""
    if value is None:
        return None
    quantized = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return Decimal("0.00") if quantized == 0 else quantized


def total(rows, key):
    return sum((row[key] for row in rows if row[key] is not None), Decimal(0))


def utc_day(moment):
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_r(r):
    return max(-2, min(4, int(r.quantize(ONE, rounding=ROUND_HALF_UP))))


def bucket_pct(pct):
    return max(-10, min(20, 5 * int((pct / 5).quantize(ONE, rounding=ROUND_HALF_UP))))


def analyst_table(name, rows):
    wins = sum(1 for row in rows if row["outcome"] == "win")
    losses = sum(1 for row in rows if row["outcome"] == "loss")
    decided = wins + losses
    return {
        "analyst": name,
        "closed_calls": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": rounded(Decimal(wins) / Decimal(decided) * 100) if decided else None,
        "cumulative_r": rounded(total(rows, "r")),
        "cumulative_move_pct": rounded(total(rows, "move_pct")),
    }


def compute(rows, window_days, now):
    """One window, cut and summed the way the site does it."""
    start = now - timedelta(days=window_days)
    # Cancellations never filled; they are in the ledger but in no figure.
    window = [row for row in rows if row["closed_at"] > start and row["outcome"] != "cancelled"]

    wins = sum(1 for row in window if row["outcome"] == "win")
    losses = sum(1 for row in window if row["outcome"] == "loss")
    breakevens = sum(1 for row in window if row["outcome"] == "breakeven")
    decided = wins + losses
    multiples = [row["r"] for row in window if row["r"] is not None]
    percents = [row["move_pct"] for row in window if row["move_pct"] is not None]
    follower_r = [row["follower_r"] for row in window if row["follower_r"] is not None]
    follower_pct = [row["follower_move_pct"] for row in window if row["follower_move_pct"] is not None]

    # One point per UTC day, from the day the window starts to today, empty
    # days included. The drawdown runs over the unrounded daily totals.
    days = defaultdict(lambda: [Decimal(0), Decimal(0), 0])
    for row in window:
        day = days[utc_day(row["closed_at"])]
        day[0] += row["r"] or Decimal(0)
        day[1] += row["move_pct"] or Decimal(0)
        day[2] += 1
    series = []
    running = peak = drawdown = Decimal(0)
    running_pct = peak_pct = drawdown_pct = Decimal(0)
    first = utc_day(start)
    for offset in range(window_days + 1):
        day = first + timedelta(days=offset)
        if day > now:
            break
        r, pct, count = days.get(day, (Decimal(0), Decimal(0), 0))
        series.append({"day": day, "r": rounded(r), "pct": rounded(pct), "closed_calls": count})
        running += r
        peak = max(peak, running)
        drawdown = min(drawdown, running - peak)
        running_pct += pct
        peak_pct = max(peak_pct, running_pct)
        drawdown_pct = min(drawdown_pct, running_pct - peak_pct)

    by_analyst = defaultdict(list)
    by_symbol = defaultdict(list)
    for row in window:
        by_analyst[row["analyst"]].append(row)
        by_symbol[row["symbol"]].append(row)
    buckets = Counter(bucket_r(r) for r in multiples)
    buckets_pct = Counter(bucket_pct(pct) for pct in percents)

    return {
        "window_days": window_days,
        "window_start": start,
        "closed_calls": len(window),
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate_pct": rounded(Decimal(wins) / Decimal(decided) * 100) if decided else None,
        "cumulative_r": rounded(sum(multiples, Decimal(0))),
        "r_qualified_calls": len(multiples),
        "average_r": rounded(sum(multiples, Decimal(0)) / len(multiples)) if multiples else None,
        "best_call_r": rounded(max(multiples)) if multiples else None,
        "max_drawdown_r": rounded(drawdown),
        "cumulative_move_pct": rounded(sum(percents, Decimal(0))),
        "average_move_pct": rounded(sum(percents, Decimal(0)) / len(percents)) if percents else None,
        "best_call_pct": rounded(max(percents)) if percents else None,
        "max_drawdown_pct": rounded(drawdown_pct),
        "cumulative_follower_r": rounded(sum(follower_r, Decimal(0))),
        "average_follower_r": rounded(sum(follower_r, Decimal(0)) / len(follower_r)) if follower_r else None,
        "cumulative_follower_move_pct": rounded(sum(follower_pct, Decimal(0))),
        "average_follower_move_pct": (
            rounded(sum(follower_pct, Decimal(0)) / len(follower_pct)) if follower_pct else None
        ),
        "daily": series,
        "outcome_buckets": [buckets.get(key, 0) for key in BUCKETS_R],
        "outcome_buckets_pct": [buckets_pct.get(key, 0) for key in BUCKETS_PCT],
        "analysts": sorted(
            (analyst_table(name, group) for name, group in by_analyst.items()),
            key=lambda table: table["cumulative_r"],
            reverse=True,
        ),
        "instruments": sorted(
            (
                {
                    "symbol": symbol,
                    "closed_calls": len(group),
                    "cumulative_r": rounded(total(group, "r")),
                    "cumulative_move_pct": rounded(total(group, "move_pct")),
                }
                for symbol, group in by_symbol.items()
            ),
            key=lambda table: table["cumulative_r"],
            reverse=True,
        ),
    }


def check_rows(rows):
    """R and percent from the prices on each row, against the row's own columns.

    R is (exit minus entry) over (entry minus stop), with the sign of the side;
    the percent is (exit minus entry) over entry, times 100, same sign. Entry
    prices are rounded to the instrument's tick in the CSV, so the last digit of
    a recomputed R can differ from the one Core measured on the unrounded entry.
    """
    checks = []
    for row in rows:
        if row["r"] is None:
            continue
        if None in (row["entry"], row["stop"], row["exit"]) or row["entry"] == row["stop"]:
            checks.append({"row": row, "r": None, "pct": None})
            continue
        sign = 1 if row["side"].upper() == "LONG" else -1
        move = sign * (row["exit"] - row["entry"])
        checks.append(
            {
                "row": row,
                "r": rounded(move / abs(row["entry"] - row["stop"])),
                "pct": rounded(move / row["entry"] * 100),
            }
        )
    return checks


def leg_costs(assumptions):
    """What each published leg costs in bps, by leg and by that total."""
    legs = {}
    for leg in (assumptions or {}).get("legs", []):
        total = num(leg["fee_bps"]) + num(leg["slippage_bps"])
        legs.setdefault(leg["leg"], {}).setdefault(total, leg["condition"])
    return legs


def check_follower(rows, assumptions):
    """Rebuild every row's follower figures from its prices and the published legs.

        cost per unit = entry * entry bps / 10000 + exit * exit bps / 10000
        follower R    = R minus cost per unit / |entry minus stop|
        follower %    = move % minus cost per unit / entry * 100
        cost R        = R minus follower R, both already rounded

    A row's entry_bps and exit_bps must be the fee plus the slippage of one of
    the legs the assumption table publishes; a row whose bps name no leg is
    reported. The rebuilt figures then replace the row's follower columns, so
    the window totals are summed from this arithmetic and not from the column,
    and column_follower_r keeps what the CSV said so the two can be compared.
    """
    legs = leg_costs(assumptions)
    checks = []
    for row in rows:
        if row["r"] is None or row["entry_bps"] is None or row["exit_bps"] is None:
            continue
        check = {
            "row": row,
            "entry_leg": legs.get("ENTRY", {}).get(row["entry_bps"]),
            "exit_leg": legs.get("EXIT", {}).get(row["exit_bps"]),
            "follower_r": None,
            "follower_move_pct": None,
            "cost_r": None,
        }
        if None not in (row["entry"], row["stop"], row["exit"]) and row["entry"] != row["stop"]:
            cost = row["entry"] * row["entry_bps"] / 10000 + row["exit"] * row["exit_bps"] / 10000
            check["follower_r"] = rounded(row["r"] - cost / abs(row["entry"] - row["stop"]))
            check["cost_r"] = rounded(row["r"] - check["follower_r"])
            if row["move_pct"] is not None:
                check["follower_move_pct"] = rounded(row["move_pct"] - cost / row["entry"] * 100)
        checks.append(check)
        row.setdefault("column_follower_r", row["follower_r"])
        row.setdefault("column_follower_move_pct", row["follower_move_pct"])
        if check["follower_r"] is not None:
            row["follower_r"] = check["follower_r"]
        if check["follower_move_pct"] is not None:
            row["follower_move_pct"] = check["follower_move_pct"]
    return checks


# --- comparing ---------------------------------------------------------------


def num(value):
    if value is None:
        return None
    return Decimal(str(value)) if isinstance(value, (int, float)) else Decimal(value)


class Result:
    def __init__(self, window, name, recomputed, published):
        self.window = window
        self.name = name
        self.recomputed = recomputed
        self.published = published

    @property
    def ok(self):
        return self.recomputed == self.published


def display_name(published_name, names):
    """The site prints display names; the CSV already carries them trimmed."""
    if published_name in names:
        return published_name
    short = published_name.split("|")[0].strip()
    return short if short in names else published_name


def compare(rows, figures):
    """Every published figure beside its recomputation, as a flat list."""
    now = parse_time(figures["generated_at"])
    results = []
    for published in figures["windows"]:
        days = int(published["window_days"])
        ours = compute(rows, days, now)
        results.append(Result(days, "window start", ours["window_start"], parse_time(published["window_start"])))
        for label, key in FIGURES:
            theirs = published.get(key)
            if key in ("closed_calls", "wins", "losses", "breakevens", "r_qualified_calls"):
                results.append(Result(days, label, ours[key], int(theirs)))
            else:
                results.append(Result(days, label, ours[key], num(theirs)))

        theirs = [
            (parse_time(point["day"]), num(point["r"]), num(point.get("pct", 0)), int(point["closed_calls"]))
            for point in published["daily"]
        ]
        mine = [(point["day"], point["r"], point["pct"], point["closed_calls"]) for point in ours["daily"]]
        results.append(Result(days, "daily series (%d days)" % len(theirs), mine, theirs))

        for key, label in (("outcome_buckets", "outcome buckets R"), ("outcome_buckets_pct", "outcome buckets %")):
            theirs = [int(bucket["calls"]) for bucket in published.get(key, [])]
            results.append(Result(days, label, ours[key], theirs))

        names = {table["analyst"] for table in ours["analysts"]}
        seen = set()
        for theirs in published["analysts"]:
            name = display_name(theirs["analyst"], names)
            seen.add(name)
            mine = next((table for table in ours["analysts"] if table["analyst"] == name), None)
            results.append(
                Result(
                    days,
                    "analyst %s" % name,
                    _analyst_tuple(mine) if mine else None,
                    (
                        int(theirs["closed_calls"]),
                        int(theirs["wins"]),
                        int(theirs["losses"]),
                        num(theirs.get("win_rate_pct")),
                        num(theirs["cumulative_r"]),
                        num(theirs.get("cumulative_move_pct", 0)),
                    ),
                )
            )
        for name in sorted(names - seen):
            results.append(Result(days, "analyst %s" % name, _analyst_tuple(_by(ours["analysts"], "analyst", name)), None))

        symbols = {table["symbol"] for table in ours["instruments"]}
        seen = set()
        for theirs in published["instruments"]:
            symbol = theirs["symbol"]
            seen.add(symbol)
            mine = _by(ours["instruments"], "symbol", symbol)
            results.append(
                Result(
                    days,
                    "instrument %s" % symbol,
                    (mine["closed_calls"], mine["cumulative_r"], mine["cumulative_move_pct"]) if mine else None,
                    (int(theirs["closed_calls"]), num(theirs["cumulative_r"]), num(theirs.get("cumulative_move_pct", 0))),
                )
            )
        for symbol in sorted(symbols - seen):
            mine = _by(ours["instruments"], "symbol", symbol)
            results.append(
                Result(days, "instrument %s" % symbol, (mine["closed_calls"], mine["cumulative_r"], mine["cumulative_move_pct"]), None)
            )
        results.append(
            Result(
                days,
                "analysts ordered by cumulative R",
                [table["cumulative_r"] for table in ours["analysts"]],
                [num(table["cumulative_r"]) for table in published["analysts"]],
            )
        )
        results.append(
            Result(
                days,
                "instruments ordered by cumulative R",
                [table["cumulative_r"] for table in ours["instruments"]],
                [num(table["cumulative_r"]) for table in published["instruments"]],
            )
        )
    return results


def _by(tables, key, value):
    return next((table for table in tables if table[key] == value), None)


def _analyst_tuple(table):
    return (
        table["closed_calls"],
        table["wins"],
        table["losses"],
        table["win_rate_pct"],
        table["cumulative_r"],
        table["cumulative_move_pct"],
    )


# --- printing ----------------------------------------------------------------


def show(value):
    if value is None:
        return "none"
    if isinstance(value, Decimal):
        return "%.2f" % value
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%SZ")
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(show(item) for item in value) + ")"
    return str(value)


def print_results(results):
    for days in sorted({result.window for result in results}):
        print()
        print("last %d days" % days)
        print("  %-38s %14s %14s" % ("", "recomputed", "published"))
        for result in results:
            if result.window != days:
                continue
            if isinstance(result.recomputed, list) or isinstance(result.published, list):
                # a series or a table: one line, with the differing entries spelled out
                if result.ok:
                    print("  %-38s %30s   ok" % (result.name, "all %d match" % len(result.published)))
                    continue
                print("  %-38s %30s   DIFFERS" % (result.name, ""))
                mine = result.recomputed or []
                theirs = result.published or []
                for index in range(max(len(mine), len(theirs))):
                    a = mine[index] if index < len(mine) else None
                    b = theirs[index] if index < len(theirs) else None
                    if a != b:
                        print("    %-36s %14s %14s" % ("entry %d" % (index + 1), show(a), show(b)))
                continue
            flag = "ok" if result.ok else "DIFFERS"
            print("  %-38s %14s %14s   %s" % (result.name, show(result.recomputed), show(result.published), flag))


def print_row_checks(checks):
    print()
    print("R and percent recomputed from each row's prices")
    r_off = [check for check in checks if check["r"] != check["row"]["r"]]
    pct_off = [check for check in checks if check["pct"] != check["row"]["move_pct"]]
    differing = [check for check in checks if check in r_off or check in pct_off]
    print(
        "  %d rows carry an R; the recomputed R differs from the column on %d, the recomputed percent on %d"
        % (len(checks), len(r_off), len(pct_off))
    )
    if differing:
        print("  %-22s %-14s %-6s %9s %9s %9s %9s" % ("signal", "symbol", "side", "R calc", "R col", "% calc", "% col"))
    for check in differing:
        row = check["row"]
        print(
            "  %-22s %-14s %-6s %9s %9s %9s %9s"
            % (row["signal_id"], row["symbol"], row["side"], show(check["r"]), show(row["r"]), show(check["pct"]), show(row["move_pct"]))
        )


def print_assumptions(figures):
    table = figures.get("follower_assumptions")
    if not table:
        print()
        print("the site published no follower assumptions")
        return
    print()
    print(
        "follower assumptions as published: maker %s bps, taker %s bps, market slippage %s bps, stop slippage %s bps, "
        "funding %s, execution delay %s, policy %s v%s"
        % (
            table.get("maker_fee_bps"),
            table.get("taker_fee_bps"),
            table.get("market_slippage_bps"),
            table.get("stop_slippage_bps"),
            "applied" if table.get("funding_applied") else "not applied",
            "applied" if table.get("execution_delay_applied") else "not applied",
            table.get("policy_key"),
            table.get("policy_version"),
        )
    )
    for leg in table.get("legs", []):
        print(
            "  %-5s %-20s %-5s fee %4s bps  slippage %4s bps  %s"
            % (leg["leg"], leg["condition"], leg["liquidity"], leg["fee_bps"], leg["slippage_bps"], leg["applies_when"])
        )
    print("  follower R = R minus (entry * entry bps + exit * exit bps) / 10000 / |entry minus stop|")


def print_follower_checks(checks):
    print()
    print("follower R and follower percent rebuilt from each row's prices and bps")
    if not checks:
        print("  no row carries entry_bps and exit_bps, so the follower columns are summed as published")
        return
    rebuilt = [check for check in checks if check["follower_r"] is not None]
    unknown = [check for check in checks if check["entry_leg"] is None or check["exit_leg"] is None]
    differing = [
        check
        for check in rebuilt
        if check["follower_r"] != check["row"]["column_follower_r"]
        or check["follower_move_pct"] != check["row"]["column_follower_move_pct"]
        or check["cost_r"] != check["row"]["cost_r"]
    ]
    print(
        "  %d of %d rows rebuilt, %d differ from the column; the follower totals above are summed from the rebuilt rows"
        % (len(rebuilt), len(checks), len(differing))
    )
    if unknown:
        print("  %d rows carry bps that are no published leg" % len(unknown))
        for check in unknown[:20]:
            print(
                "    %-22s entry %s bps %s, exit %s bps %s"
                % (
                    check["row"]["signal_id"],
                    show(check["row"]["entry_bps"]),
                    check["entry_leg"] or "no leg",
                    show(check["row"]["exit_bps"]),
                    check["exit_leg"] or "no leg",
                )
            )
    if differing:
        print(
            "  %-22s %-14s %9s %9s %9s %9s %9s %9s"
            % ("signal", "symbol", "R calc", "R col", "% calc", "% col", "cost calc", "cost col")
        )
    for check in differing:
        row = check["row"]
        print(
            "  %-22s %-14s %9s %9s %9s %9s %9s %9s"
            % (
                row["signal_id"],
                row["symbol"],
                show(check["follower_r"]),
                show(row["column_follower_r"]),
                show(check["follower_move_pct"]),
                show(row["column_follower_move_pct"]),
                show(check["cost_r"]),
                show(row["cost_r"]),
            )
        )


def main():
    parser = argparse.ArgumentParser(description="Recompute the figures on axioncrypto.net/performance from its CSV.")
    parser.add_argument("--csv", help="a saved ledger.csv instead of downloading it")
    parser.add_argument("--figures", help="saved figures (figures.json, or the object the page carries) instead of downloading")
    parser.add_argument("--save-csv", help="write the CSV that was used here")
    parser.add_argument("--save-figures", help="write the figures that were used here, as fetched")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # analyst names are whatever Discord allows

    if args.csv:
        with open(args.csv, encoding="utf-8", newline="") as handle:
            text = handle.read()
        csv_source = args.csv
    else:
        data, _ = http(CSV_URL)
        text = data.decode("utf-8")
        csv_source = CSV_URL
    if args.figures:
        with open(args.figures, encoding="utf-8") as handle:
            raw_figures = json.load(handle)
        figures_source = args.figures
    else:
        raw_figures, figures_source = fetch_figures()
    if args.save_csv:
        with open(args.save_csv, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    if args.save_figures:
        with open(args.save_figures, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(raw_figures, handle, indent=1)
            handle.write("\n")

    rows = read_rows(text)
    figures = normalise(raw_figures)
    follower = check_follower(rows, figures.get("follower_assumptions"))
    print("ledger: %s, %d rows" % (csv_source, len(rows)))
    if rows:
        print("  closed between %s and %s" % (show(min(r["closed_at"] for r in rows)), show(max(r["closed_at"] for r in rows))))
    print(
        "figures: %s, %s, generated %s, calculation version %s"
        % (
            figures_source,
            figures.get("schema") or "the page's own payload, which names no schema",
            figures.get("generated_at"),
            figures.get("calculation_version"),
        )
    )
    print("  portfolio %s, %s calls open" % (figures.get("portfolio_name"), figures.get("open_calls")))
    if figures_source == PAGE_URL:
        print("  read from the page because %s did not answer with JSON" % FIGURES_URL)
    print("windows are cut at the figures' generation time minus 7, 30 and 90 days, closed_at strictly after the cut")

    results = compare(rows, figures)
    print_results(results)
    print_row_checks(check_rows(rows))
    print_assumptions(figures)
    print_follower_checks(follower)

    differing = [result for result in results if not result.ok]
    print()
    if differing:
        print("%d of %d comparisons differ" % (len(differing), len(results)))
        return 1
    print("all %d comparisons match" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
