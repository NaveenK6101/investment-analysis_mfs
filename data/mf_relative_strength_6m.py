"""Relative strength framework, applied to the 12 tracked mutual funds, last 6 months.

Same method used on CDMO vs Nifty Pharma:
  1. Rebase every fund's NAV to 100 at the start of the window.
  2. Rebase the benchmark the same way.
  3. relative[t] = 100 * fund_rebased[t] / benchmark_rebased[t]
  4. Rolling excess return = relative[t] / relative[t-N] - 1  (rate of change of
     the relative-strength line itself, not a simple subtraction - see the
     Sep-2024 CDMO example for why that distinction matters)

Benchmark: Nifty Smallcap 250 - 9 of the 12 funds are small-cap, so this is the
size-matched benchmark (per the earlier "which index" discussion). Quant Flexi Cap,
Invesco Mid Cap, and Quant Multi Asset aren't a clean match for it - flagged
separately rather than silently averaged in.

Frequency: weekly (Friday, or last available day that week). Daily AMFI NAV dates
and NSE trading dates don't always coincide 1:1, so weekly resampling sidesteps
fragile day-level alignment while still giving ~26 points over 6 months - plenty
of resolution for a 6-month view.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav"

FUNDS = [
    {"key": "quant_flexi",   "name": "Quant Flexi Cap",        "cap": "Flexi Cap"},
    {"key": "quant_small",   "name": "Quant Small Cap",        "cap": "Small Cap"},
    {"key": "invesco_mid",   "name": "Invesco India Mid Cap",  "cap": "Mid Cap"},
    {"key": "nippon_small",  "name": "Nippon India Small Cap", "cap": "Small Cap"},
    {"key": "quant_multi",   "name": "Quant Multi Asset",      "cap": "Multi Asset"},
    {"key": "trustmf_small", "name": "TRUSTMF Small Cap",      "cap": "Small Cap"},
    {"key": "abakkus_small", "name": "Abakkus Small Cap",      "cap": "Small Cap"},
    {"key": "helios_small",  "name": "Helios Small Cap",       "cap": "Small Cap"},
    {"key": "invesco_small", "name": "Invesco India Small Cap","cap": "Small Cap"},
    {"key": "bandhan_small", "name": "Bandhan Small Cap",      "cap": "Small Cap"},
    {"key": "boi_small",     "name": "Bank of India Small Cap","cap": "Small Cap"},
    {"key": "iti_small",     "name": "ITI Small Cap",          "cap": "Small Cap"},
]

WINDOW_MONTHS = 6
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def load_fund_weekly(key: str) -> pd.Series:
    df = pd.read_csv(NAV_DIR / f"{key}.csv", parse_dates=["date"]).set_index("date").sort_index()
    return df["nav"].resample("W-FRI").last()


def load_benchmark_weekly() -> pd.Series:
    r = requests.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/NIFTYSMLCAP250.NS",
        params={"interval": "1d", "range": "1y"}, headers=UA, timeout=30,
    )
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    s = pd.Series(
        {pd.Timestamp.fromtimestamp(t).normalize(): c for t, c in zip(ts, close) if c is not None}
    ).sort_index()
    return s.resample("W-FRI").last()


def main() -> None:
    bench = load_benchmark_weekly()
    end_date = bench.index.max()
    start_date = end_date - pd.DateOffset(months=WINDOW_MONTHS)

    series = {}
    for f in FUNDS:
        s = load_fund_weekly(f["key"])
        series[f["key"]] = s

    # common window: from start_date to end_date, intersected with what every series actually has
    idx = bench.index
    idx = idx[(idx >= start_date) & (idx <= end_date)]

    table = pd.DataFrame(index=idx)
    table["Nifty Smallcap 250"] = bench.reindex(idx)
    for f in FUNDS:
        table[f["name"]] = series[f["key"]].reindex(idx)

    # drop any week where ANY series is missing - in practice this is just the
    # current in-progress week, where the benchmark already has a live price but
    # funds haven't posted this Friday's NAV yet
    complete = table.dropna(how="any")
    dropped = table.index.difference(complete.index)
    if len(dropped):
        print(f"Dropping incomplete week(s): {[d.date() for d in dropped]} (NAV not posted yet)\n")
    table = complete
    base_row = table.iloc[0]
    rebased = table.div(base_row) * 100

    relative = rebased.drop(columns=["Nifty Smallcap 250"]).div(rebased["Nifty Smallcap 250"], axis=0) * 100

    print(f"Window: {idx[0].date()} to {idx[-1].date()}  ({len(idx)} weekly points)\n")

    # ---- ranking table: total 6M return, vs benchmark, relative-strength change ----
    first, last = rebased.iloc[0], rebased.iloc[-1]
    total_return = (last / first - 1) * 100
    bench_return = total_return["Nifty Smallcap 250"]

    rel_first, rel_last = relative.iloc[0], relative.iloc[-1]
    rs_change = (rel_last / rel_first - 1) * 100   # true rate-of-change of the relative-strength line, full 6M

    # momentum: same rate-of-change formula, but over just the trailing 4 weeks -
    # is the fund accelerating or fading RIGHT NOW, not just "how did the whole
    # 6 months go" (this is the "catch it early" lens from the CDMO discussion)
    rel_4w_ago = relative.iloc[-5]  # 4 weeks back from the last complete week
    momentum_4w = (rel_last / rel_4w_ago - 1) * 100

    rank = pd.DataFrame({
        "fund_return_6m_pct": total_return.drop("Nifty Smallcap 250").round(1),
        "excess_vs_smallcap250_pp": (total_return.drop("Nifty Smallcap 250") - bench_return).round(1),
        "relative_strength_change_pct": rs_change.round(1),
        "momentum_last_4w_pct": momentum_4w.round(1),
    }).sort_values("relative_strength_change_pct", ascending=False)

    cap_map = {f["name"]: f["cap"] for f in FUNDS}
    rank.insert(0, "category", rank.index.map(cap_map))

    print(f"Nifty Smallcap 250, 6M return: {bench_return:.1f}%\n")
    print(rank.to_string())

    # ---- save everything for the chart ----
    out = {
        "start": str(idx[0].date()), "end": str(idx[-1].date()),
        "bench_return_6m": round(float(bench_return), 2),
        "dates": [d.strftime("%Y-%m-%d") for d in rebased.index],
        "rebased": {col: [None if pd.isna(v) else round(float(v), 2) for v in rebased[col]] for col in rebased.columns},
        "relative": {col: [None if pd.isna(v) else round(float(v), 2) for v in relative[col]] for col in relative.columns},
        "ranking": rank.reset_index().rename(columns={"index": "fund"}).to_dict(orient="records"),
    }
    with open(BASE / "mf_relative_strength_6m.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote {BASE / 'mf_relative_strength_6m.json'}")


if __name__ == "__main__":
    main()
