"""Backtest: monthly rotation into the top 2 Small Cap funds that pass all
three screens, with a sticky hold rule (don't switch out a holding that
still qualifies, even if something else now ranks higher).

Screens, computed as of each rebalance date using ONLY data up to that date
(no look-ahead):
  a) 4W momentum > 0            - current trailing-4-week RS momentum is positive
  b) Consistency >= 75%         - of the last 12 weekly 4W-momentum readings, at least 75% positive
  c) 3M/6M signal freshly Above - trailing 3-month RS change is above its own trailing
                                  6-month average, AND has held that side <= 4 weeks
                                  ("turned positive recently", not a stale/already-priced-in cross)

Ranking among qualifiers: 3-month RS change, descending (same horizon as the
crossover's short leg). Unfilled slots (fewer than 2 qualifiers) sit in cash
for that month rather than forcing a pick that fails the screen.

Rebalance dates: first available Friday NAV of each calendar month (data is
weekly-Friday only, so "check on the 1st-5th" is approximated as "the first
weekly point at or after the 1st" - stated explicitly since it's a simplification).

Known, unfixable limitation: this can only pick from the 36 Small Cap funds
verified as CURRENTLY open-ended and active. Funds that existed at some
historical rebalance date but have since closed/merged are invisible to
this backtest - the same survivorship-bias caveat that applies to the whole
leaderboard, but it matters more here because a strategy is actually being
graded on simulated decisions, not just shown a snapshot.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
CONSISTENCY_WINDOW = 12
CONSISTENCY_MIN_PCT = 75.0
CROSSOVER_SHORT, CROSSOVER_LONG = 13, 26
CROSSOVER_RECENT_WEEKS = 4  # "turned positive recently"
RANK_WINDOW_WEEKS = 13      # ~3 months, matches the crossover's short leg
N_HOLDINGS = 2


def first_valid_idx(values):
    for i, v in enumerate(values):
        if v is not None:
            return i
    return None


def ratio_change(fv, bv, i0, i1):
    f0, f1, b0, b1 = fv[i0], fv[i1], bv[i0], bv[i1]
    if None in (f0, f1, b0, b1) or f0 == 0 or b0 == 0:
        return None
    return (f1 / f0) / (b1 / b0) - 1


def rolling_rs_series(fv, bv, n, upto, count):
    """Trailing-n-week RS change ending at every index in the last `count`
    positions up to `upto` (inclusive). Same definition used on the page."""
    out = []
    start = max(n, upto - count + 1)
    for i in range(start, upto + 1):
        out.append(ratio_change(fv, bv, i - n, i))
    return out


def crossover_signal(fv, bv, upto):
    series = rolling_rs_series(fv, bv, CROSSOVER_SHORT, upto, CROSSOVER_LONG + 40)
    sides = []
    for i in range(CROSSOVER_LONG, len(series)):
        window = series[i - CROSSOVER_LONG:i]
        if series[i] is None or any(v is None for v in window):
            sides.append(None)
            continue
        avg = sum(window) / len(window)
        sides.append(series[i] > avg)
    last = next((s for s in reversed(sides) if s is not None), None)
    if last is None:
        return None, 0
    weeks = 0
    for s in reversed(sides):
        if s != last:
            break
        weeks += 1
    return last, weeks


def momentum_4w(fv, bv, upto):
    return ratio_change(fv, bv, upto - 4, upto)


def consistency_pct(fv, bv, upto):
    vals = rolling_rs_series(fv, bv, 4, upto, CONSISTENCY_WINDOW)
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return 100.0 * sum(1 for v in vals if v > 0) / len(vals)


def rs_change_window(fv, bv, upto, weeks):
    return ratio_change(fv, bv, upto - weeks, upto)


def eligible(fv, bv, upto):
    fvi = first_valid_idx(fv)
    bvi = first_valid_idx(bv)
    if fvi is None or bvi is None:
        return False
    start = max(fvi, bvi)
    return (upto - start) >= (CROSSOVER_LONG + CROSSOVER_SHORT)


def screen(fv, bv, upto):
    """Returns dict of computed signals if eligible, else None."""
    if not eligible(fv, bv, upto):
        return None
    mom = momentum_4w(fv, bv, upto)
    cons = consistency_pct(fv, bv, upto)
    above, weeks = crossover_signal(fv, bv, upto)
    rs3m = rs_change_window(fv, bv, upto, RANK_WINDOW_WEEKS)
    if mom is None or cons is None or above is None or rs3m is None:
        return None
    entry_ok = (mom > 0) and (cons >= CONSISTENCY_MIN_PCT) and above and (weeks <= CROSSOVER_RECENT_WEEKS)
    # "stay" drops the freshness requirement - momentum and consistency still
    # have to hold up, but the crossover just needs to still be Above, not
    # Above-within-the-last-4-weeks (that would force an exit almost every
    # single month purely from the clock, independent of whether the fund
    # is still strong).
    stay_ok = (mom > 0) and (cons >= CONSISTENCY_MIN_PCT) and above
    return {"mom": mom, "consistency": cons, "above": above, "weeks_above": weeks,
            "rs3m": rs3m, "entry_ok": entry_ok, "stay_ok": stay_ok}


def monthly_rebalance_indices(dates):
    """First index in each calendar month, approximating 'checked 1st-5th'
    given weekly-Friday-only data."""
    out = []
    seen = set()
    for i, d in enumerate(dates):
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(i)
    return out


def cagr(eq, months):
    years = months / 12.0
    return (eq[-1] ** (1 / years) - 1) * 100 if years > 0 and eq[-1] > 0 else float("nan")


def max_dd(eq):
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd * 100


def run_strategy(mode, funds, values, bench, dates, rebal_idx, names):
    """mode='strict': condition (c) - fresh crossover - must hold true every
    month to KEEP a position, not just to enter it.
    mode='entry_only': condition (c) gates entry only; staying held only
    needs momentum>0 and consistency>=75 (crossover can be Above but stale)."""
    holdings, log, port_ret, bench_ret, n_held = [], [], [], [], []
    for k, idx in enumerate(rebal_idx):
        screens = {f["key"]: s for f in funds
                   if (s := screen(values[f["key"]], bench, idx)) is not None}

        qualifiers = [k2 for k2, s in screens.items() if s["entry_ok"]]
        qualifiers.sort(key=lambda k2: screens[k2]["rs3m"], reverse=True)

        stay_field = "entry_ok" if mode == "strict" else "stay_ok"
        new_holdings = [h for h in holdings if h in screens and screens[h][stay_field]]
        for h in holdings:
            if h not in new_holdings:
                reason = "no longer eligible" if h not in screens else \
                    ("mom<=0" if not screens[h]["mom"] > 0 else
                     "consistency<75" if screens[h]["consistency"] < CONSISTENCY_MIN_PCT else
                     "signal not fresh-above" if mode == "strict" else "signal turned Below")
                log.append(f"{dates[idx]}: DROP {names[h]} ({reason})")

        for k2 in qualifiers:
            if len(new_holdings) >= N_HOLDINGS:
                break
            if k2 not in new_holdings:
                new_holdings.append(k2)
                verb = "ADD" if k2 not in holdings else "KEEP"
                log.append(f"{dates[idx]}: {verb} {names[k2]} "
                           f"(mom={screens[k2]['mom']*100:+.1f}% cons={screens[k2]['consistency']:.0f}% "
                           f"above={screens[k2]['weeks_above']}w rs3m={screens[k2]['rs3m']*100:+.1f}%)")

        holdings = new_holdings
        end_idx = rebal_idx[k + 1] if k < len(rebal_idx) - 1 else len(dates) - 1

        slot_returns = [0.0] * N_HOLDINGS
        for si, h in enumerate(holdings[:N_HOLDINGS]):
            fv = values[h]
            if fv[idx] is not None and fv[end_idx] is not None and fv[idx] != 0:
                slot_returns[si] = fv[end_idx] / fv[idx] - 1
        port_ret.append(sum(slot_returns) / N_HOLDINGS)
        n_held.append(len(holdings))
        b0, b1 = bench[idx], bench[end_idx]
        bench_ret.append((b1 / b0 - 1) if (b0 and b1) else 0.0)

        if not holdings:
            log.append(f"{dates[idx]}: no qualifiers - fully in cash this period")
        elif len(holdings) < N_HOLDINGS:
            log.append(f"{dates[idx]}: only {len(holdings)}/{N_HOLDINGS} slots filled - rest in cash")

    eq = [1.0]
    for r in port_ret:
        eq.append(eq[-1] * (1 + r))
    switches = sum(1 for l in log if l.split(": ", 1)[1].startswith(("ADD", "DROP")))
    cash_months = sum(1 for l in log if "in cash" in l)

    # decompose: was the fund SELECTION any good, separate from the cash-
    # timing drag of sitting out unqualified months? Compare each period's
    # return to what the SAME invested fraction of the index would have
    # earned - this isolates picking skill from the (much bigger) effect of
    # being out of the market so often.
    selection_excess = [port_ret[i] - bench_ret[i] * (n_held[i] / N_HOLDINGS) for i in range(len(port_ret))]
    avg_selection_excess = sum(selection_excess) / len(selection_excess) * 100 if selection_excess else float("nan")

    # alternative: park any unfilled slot in the index instead of cash - a
    # more realistic choice than literal cash for most investors.
    indexed_ret = [port_ret[i] + bench_ret[i] * (1 - n_held[i] / N_HOLDINGS) for i in range(len(port_ret))]
    indexed_eq = [1.0]
    for r in indexed_ret:
        indexed_eq.append(indexed_eq[-1] * (1 + r))

    return {"equity": eq, "returns": port_ret, "log": log, "switches": switches, "cash_months": cash_months,
            "avg_selection_excess_pp_per_month": avg_selection_excess, "indexed_equity": indexed_eq}


LIGHT_MIN_WEEKS = 4  # only what momentum itself needs - no consistency/crossover screen in this variant
EXIT_LOAD_PCT = 0.01   # typical small-cap fund exit load within 1 year
STCG_RATE = 0.20       # equity STCG if held under 1 year - every switch here qualifies


def light_eligible(fv, upto, min_weeks=LIGHT_MIN_WEEKS):
    fvi = first_valid_idx(fv)
    return fvi is not None and (upto - fvi) >= min_weeks


def run_strategy_c(funds, values, bench, dates, rebal_idx, names, min_hold_periods=0):
    """Always fully invested, no screens beyond having enough history for a
    4-week momentum reading. Each HELD fund is only replaced if some specific
    non-held fund's momentum beats THAT fund's own momentum - evaluated per
    slot, one challenger consumed per swap. This is deliberately NOT "hold
    the current top-2 by momentum every month": a naive "swap the weakest
    holding whenever anything ranks higher" cascades into exactly that
    (every non-top-2 fund keeps getting bumped by the process working its
    way down the ranked list), which is full rebalancing in disguise, not
    the sticky "stay unless personally overtaken" rule that was asked for.

    min_hold_periods: a slot can't be swapped out until it's been held for
    at least this many rebalance periods, regardless of momentum - a lock-up
    to curb the tax/exit-load churn from switching almost every month.
    """
    holdings, log, port_ret, port_ret_costed, bench_ret, n_held = [], [], [], [], [], []
    held_since = {}  # fund_key -> period index (k) it entered the portfolio
    for k, idx in enumerate(rebal_idx):
        mom = {}
        for f in funds:
            fv = values[f["key"]]
            if light_eligible(fv, idx):
                m = momentum_4w(fv, bench, idx)
                if m is not None:
                    mom[f["key"]] = m
        ranked = sorted(mom.items(), key=lambda kv: kv[1], reverse=True)

        new_holdings = list(holdings)
        new_slots = set()  # slot indices that changed this round - for the cost-adjusted variant below
        # each already-held fund is checked, one at a time, against the best
        # AVAILABLE (not-yet-held-this-round) challenger - swap only if that
        # specific challenger beats this specific holding's own momentum AND
        # the fund is out of its minimum-hold lock-up.
        for slot, h in enumerate(list(new_holdings)):
            if h not in mom:
                continue  # fund ran out of history (delisted from our view) - handled by fill-empty pass below
            if k - held_since.get(h, k) < min_hold_periods:
                continue  # still locked up, can't be swapped out yet regardless of momentum
            challenger = next((ck for ck, _ in ranked if ck not in new_holdings), None)
            if challenger is not None and mom[challenger] > mom[h]:
                log.append(f"{dates[idx]}: SWITCH {names[h]} (mom={mom[h]*100:+.1f}%) -> "
                           f"{names[challenger]} (mom={mom[challenger]*100:+.1f}%)")
                new_holdings[slot] = challenger
                new_slots.add(slot)
                held_since[challenger] = k

        new_holdings = [h for h in new_holdings if h in mom]  # drop anything that lost history entirely
        while len(new_holdings) < N_HOLDINGS:
            nxt = next((ck for ck, _ in ranked if ck not in new_holdings), None)
            if nxt is None:
                break
            log.append(f"{dates[idx]}: ADD {names[nxt]} (mom={mom[nxt]*100:+.1f}%) - filling empty slot")
            held_since[nxt] = k
            new_slots.add(len(new_holdings))
            new_holdings.append(nxt)

        holdings = new_holdings
        end_idx = rebal_idx[k + 1] if k < len(rebal_idx) - 1 else len(dates) - 1
        slot_returns, slot_returns_costed = [], []
        for slot, h in enumerate(holdings[:N_HOLDINGS]):
            fv = values[h]
            r = (fv[end_idx] / fv[idx] - 1) if (fv[idx] not in (None, 0) and fv[end_idx] is not None) else 0.0
            slot_returns.append(r)
            # approximate round-trip cost on any slot that changed this period: ~1% exit
            # load plus ~20% STCG on the gain (funds switched monthly are always held
            # under a year) - a blended assumption, not real tax-lot accounting, stated
            # as such in the report.
            if slot in new_slots:
                cost = EXIT_LOAD_PCT + (STCG_RATE * max(r, 0.0))
                slot_returns_costed.append(r - cost)
            else:
                slot_returns_costed.append(r)
        n = max(len(slot_returns), 1)
        port_ret.append(sum(slot_returns) / n if slot_returns else 0.0)
        port_ret_costed.append(sum(slot_returns_costed) / n if slot_returns_costed else 0.0)
        n_held.append(len(holdings))
        b0, b1 = bench[idx], bench[end_idx]
        bench_ret.append((b1 / b0 - 1) if (b0 and b1) else 0.0)

    eq = [1.0]
    for r in port_ret:
        eq.append(eq[-1] * (1 + r))
    eq_costed = [1.0]
    for r in port_ret_costed:
        eq_costed.append(eq_costed[-1] * (1 + r))
    switches = sum(1 for l in log if ": SWITCH" in l or ": ADD" in l)
    selection_excess = [port_ret[i] - bench_ret[i] * (n_held[i] / N_HOLDINGS) for i in range(len(port_ret))]
    avg_selection_excess = sum(selection_excess) / len(selection_excess) * 100 if selection_excess else float("nan")
    return {"equity": eq, "equity_costed": eq_costed, "returns": port_ret, "log": log, "switches": switches,
            "avg_selection_excess_pp_per_month": avg_selection_excess}


def main():
    data = json.load(open(BASE / "leaderboard_combined_dataset.json", encoding="utf-8"))
    dates = data["dates"]
    bench = next(b for b in data["benchmarks"] if b["key"] == "smallcap250")["values"]
    funds = [f for f in data["funds"] if f["category"] == "Small Cap"]
    values = {f["key"]: f["values"] for f in funds}
    names = {f["key"]: f["name"] for f in funds}

    # start the backtest at the first date where at least one Small Cap fund
    # actually has 39 weeks of prior history - not an arbitrary global index,
    # since the overall date axis (from the benchmark) starts in 2011, well
    # before any of these funds existed.
    first_eligible_idx = min(
        first_valid_idx(values[f["key"]]) + CROSSOVER_LONG + CROSSOVER_SHORT for f in funds
    )
    rebal_idx = monthly_rebalance_indices(dates)
    rebal_idx = [i for i in rebal_idx if i >= first_eligible_idx]
    if not rebal_idx:
        print("Not enough history to run a single rebalance.")
        return
    months = len(rebal_idx)

    bench_eq = [1.0]
    for k in range(months):
        i0, i1 = rebal_idx[k], (rebal_idx[k + 1] if k < months - 1 else len(dates) - 1)
        b0, b1 = bench[i0], bench[i1]
        bench_eq.append(bench_eq[-1] * ((b1 / b0) if (b0 and b1) else 1.0))

    # equal-weight across whichever funds are eligible AT EACH rebalance date
    # (the universe grows over time, same as the strategy sees it), not a
    # fixed snapshot from the first period.
    ew_eq = [1.0]
    n_eligible_over_time = []
    for k in range(months):
        i0, i1 = rebal_idx[k], (rebal_idx[k + 1] if k < months - 1 else len(dates) - 1)
        elig = [f["key"] for f in funds if eligible(values[f["key"]], bench, i0)]
        n_eligible_over_time.append(len(elig))
        rets = [values[key][i1] / values[key][i0] - 1 for key in elig
                if values[key][i0] not in (None, 0) and values[key][i1] is not None]
        ew_eq.append(ew_eq[-1] * (1 + (sum(rets) / len(rets) if rets else 0.0)))

    print(f"\nBacktest window: {dates[rebal_idx[0]]} -> {dates[-1]}  ({months} monthly rebalances)")
    print(f"Universe: Small Cap ({len(funds)} funds total; "
          f"{n_eligible_over_time[0]} eligible at the first rebalance, "
          f"{n_eligible_over_time[-1]} eligible at the last)")

    results = {}
    for mode in ("strict", "entry_only"):
        results[mode] = run_strategy(mode, funds, values, bench, dates, rebal_idx, names)

    import statistics
    print(f"\n{'=' * 90}\nRESULTS\n{'=' * 90}")
    for mode, label in [("strict", "Strategy A: crossover must stay fresh (<=4w) to keep holding"),
                         ("entry_only", "Strategy B: crossover only required to enter, not to stay")]:
        r = results[mode]
        vol = statistics.pstdev(r["returns"]) * (12 ** 0.5) * 100 if len(r["returns"]) > 1 else float("nan")
        print(f"{label}")
        print(f"  total {(r['equity'][-1]-1)*100:+7.1f}%   CAGR {cagr(r['equity'], months):+6.1f}%   "
              f"MaxDD {max_dd(r['equity']):6.1f}%   ann.vol {vol:5.1f}%   "
              f"switches {r['switches']:3d}   cash months {r['cash_months']:3d}/{months}")
        print(f"    selection skill (fund return vs index, same invested fraction, avg/month): "
              f"{r['avg_selection_excess_pp_per_month']:+.2f}pp")
        print(f"    if unfilled slots parked in the index instead of cash: "
              f"total {(r['indexed_equity'][-1]-1)*100:+7.1f}%   CAGR {cagr(r['indexed_equity'], months):+6.1f}%")
    print(f"{'Nifty Smallcap 250 (buy & hold)':60s}")
    print(f"  total {(bench_eq[-1]-1)*100:+7.1f}%   CAGR {cagr(bench_eq, months):+6.1f}%   MaxDD {max_dd(bench_eq):6.1f}%")
    print(f"{'Equal-weight all eligible funds (buy & hold)':60s}")
    print(f"  total {(ew_eq[-1]-1)*100:+7.1f}%   CAGR {cagr(ew_eq, months):+6.1f}%   MaxDD {max_dd(ew_eq):6.1f}%")

    # ---- Strategy C: always invested, momentum-only, per-slot sticky ----
    # only needs 4 weeks of history (no consistency/crossover screen), so it
    # can run over a much longer window than A/B - computed on its OWN
    # window so its benchmark comparison is apples-to-apples.
    first_light_idx = min(first_valid_idx(values[f["key"]]) + LIGHT_MIN_WEEKS for f in funds)
    rebal_idx_c = [i for i in monthly_rebalance_indices(dates) if i >= first_light_idx]
    months_c = len(rebal_idx_c)

    bench_eq_c = [1.0]
    for k in range(months_c):
        i0, i1 = rebal_idx_c[k], (rebal_idx_c[k + 1] if k < months_c - 1 else len(dates) - 1)
        b0, b1 = bench[i0], bench[i1]
        bench_eq_c.append(bench_eq_c[-1] * ((b1 / b0) if (b0 and b1) else 1.0))

    print(f"\n{'=' * 90}\nSTRATEGY C: always invested, momentum-only, per-slot sticky\n{'=' * 90}")
    print(f"Window: {dates[rebal_idx_c[0]]} -> {dates[-1]}  ({months_c} monthly rebalances, "
          f"longer than A/B since this only needs {LIGHT_MIN_WEEKS} weeks of warm-up, not {CROSSOVER_LONG + CROSSOVER_SHORT})")
    print(f"  vs Nifty Smallcap 250 over the SAME window: "
          f"total {(bench_eq_c[-1]-1)*100:+7.1f}%   CAGR {cagr(bench_eq_c, months_c):+6.1f}%   MaxDD {max_dd(bench_eq_c):6.1f}%")

    results_c = {}
    for min_hold, label in [(0, "no minimum hold"), (2, "2-month minimum hold"),
                             (3, "3-month minimum hold"), (4, "4-month minimum hold")]:
        rc = run_strategy_c(funds, values, bench, dates, rebal_idx_c, names, min_hold_periods=min_hold)
        results_c[min_hold] = rc
        vol_c = statistics.pstdev(rc["returns"]) * (12 ** 0.5) * 100 if len(rc["returns"]) > 1 else float("nan")
        print(f"\n  [{label}]")
        print(f"    before costs:  total {(rc['equity'][-1]-1)*100:+7.1f}%   CAGR {cagr(rc['equity'], months_c):+6.1f}%   "
              f"MaxDD {max_dd(rc['equity']):6.1f}%   ann.vol {vol_c:5.1f}%   switches {rc['switches']:3d}")
        print(f"    selection skill (fund return vs index, same invested fraction, avg/month): "
              f"{rc['avg_selection_excess_pp_per_month']:+.2f}pp")
        print(f"    after costs ({EXIT_LOAD_PCT*100:.0f}% exit load + {STCG_RATE*100:.0f}% STCG on switched legs, approx.):"
              f"  total {(rc['equity_costed'][-1]-1)*100:+7.1f}%   CAGR {cagr(rc['equity_costed'], months_c):+6.1f}%   "
              f"MaxDD {max_dd(rc['equity_costed']):6.1f}%")

    print(f"\n{'=' * 90}\nSTRATEGY C, 3-MONTH MINIMUM HOLD - DECISION LOG (last 40 actions)\n{'=' * 90}")
    for line in results_c[3]["log"][-40:]:
        print(" ", line)

    print(f"\n{'=' * 90}\nSTRATEGY B DECISION LOG (entry-only freshness)\n{'=' * 90}")
    for line in results["entry_only"]["log"]:
        print(" ", line)

    out = {
        "dates": [dates[i] for i in rebal_idx],
        "benchmark_equity": bench_eq,
        "equal_weight_equity": ew_eq,
        "strategy_A_strict": results["strict"],
        "strategy_B_entry_only": results["entry_only"],
        "strategy_C_dates": [dates[i] for i in rebal_idx_c],
        "strategy_C_benchmark_equity": bench_eq_c,
        "strategy_C_no_min_hold": results_c[0],
        "strategy_C_2month_min_hold": results_c[2],
        "strategy_C_3month_min_hold": results_c[3],
        "strategy_C_4month_min_hold": results_c[4],
    }
    with open(BASE / "backtest_result.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nWrote backtest_result.json")


if __name__ == "__main__":
    main()
