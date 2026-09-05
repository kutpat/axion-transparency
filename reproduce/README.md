# Reproducing the performance page

`reproduce.py` downloads the ledger the site publishes, `https://axioncrypto.net/performance/ledger.csv`, recomputes every figure on `axioncrypto.net/performance` for the 7, 30 and 90 day windows, and prints each one beside the figure the site shows.

    python reproduce.py

Standard library only. The arithmetic is in Decimal, and the only rounding is the site's own: two places, half up, never a negative zero.

## Where the published figures come from

Trading Core's API is private, so the comparison target is what the website serves. The page at `/performance` is rendered on the server with its figures in the markup, and the script reads them from there. A JSON route beside the CSV, `/performance/figures.json`, is coming; the script asks for it first and reads the page until it answers.

## The windows

A window holds every closed call whose `closed_at` is strictly after the figures' generation time minus 7, 30 or 90 days. Cancelled calls never filled and are in no figure. From the rows in a window:

- calls closed is the number of rows; wins, losses and break-evens are counted from `outcome`;
- win rate is wins over wins plus losses, times 100, so break-evens are outside the denominator;
- cumulative R is the sum of `r_multiple` over the rows that have one, R-qualified calls is how many that is, average R divides the sum by it, and best call is the largest;
- max drawdown sums the rows per UTC day of `closed_at`, runs the daily totals from the first day of the window to today, and takes the deepest fall of the running sum below its previous peak, starting from zero;
- the percent figures are the same over `move_pct`, which every closed call carries, so their denominator is calls closed;
- the follower figures are the same over `follower_r` and `follower_move_pct`;
- the outcome histogram rounds each R to the nearest whole number and clamps it to the columns from -2 to +4; the percent histogram does the same in steps of five from -10 to +20;
- the analyst and instrument tables are the same sums grouped by `analyst` and by `symbol`, ordered by cumulative R.

The site prints display names, and the CSV already carries them trimmed, so a name the page shows with a suffix after a pipe is matched on the part before it.

## R from the prices

Each row's R is also recomputed as exit minus entry, divided by entry minus stop, with the sign of the side, and the percent as exit minus entry over entry. `entry_price` in the CSV is the weighted entry rounded to the instrument's tick, so the last digit of a recomputed figure can differ from what Core measured on the unrounded entry. The script lists every row where it does.

## Follower R

`follower_r` is the published R less one round trip of fees and slippage, from the assumption table the site publishes and the script prints:

    cost per unit = entry * entry_bps / 10000 + exit * exit_bps / 10000
    follower R    = R minus cost per unit / |entry minus stop|
    follower %    = move % minus cost per unit / entry * 100

The entry leg is maker for a limit, range or DCA entry and taker with slippage for a market, cmp or stop entry; the exit leg is maker for a reached target and taker with slippage for a stop or a manual close. No funding and no execution delay. The per-row `entry_bps`, `exit_bps` and `cost_r` are not in the CSV yet, so the column cannot be rebuilt from first principles here and its aggregates are summed from the column. Those three columns are being added; the script will check each row once they are there.

## The pinned day

`ledger-2026-09-05.csv` and `figures-2026-09-05.json` are what the site served on 2026-09-05, and `test_reproduce.py` checks that every figure of that day still reproduces:

    python -m unittest test_reproduce

On that day all 306 comparisons matched. Of the 228 rows with an R, one (AXN-2026-08-17-00269) recomputes 0.01 away from its column and 18 recompute a percent 0.01 to 0.03 away, all from the tick rounding of the entry.
