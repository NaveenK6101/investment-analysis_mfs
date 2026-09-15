"""Build the full dataset backing the self-service Small Cap Fund Leaderboard.

v2: all 35 currently open-ended small cap category funds (see
all_smallcap_funds.py for how that list was derived and cleaned), plus four
benchmark choices. Embeds full weekly history so the published page can let
the viewer pick window length, benchmark, and which funds to show - all
recomputed client-side from data already in the page.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

from all_smallcap_funds import ALL_SMALLCAP_FUNDS

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

BENCHMARKS = [
    {"key": "nifty50",     "name": "Nifty 50",           "ticker": "^NSEI"},
    {"key": "nifty100",    "name": "Nifty 100",          "ticker": "^CNX100"},
    {"key": "nifty500",    "name": "Nifty 500",          "ticker": "^CRSLDX"},
    {"key": "smallcap250", "name": "Nifty Smallcap 250", "ticker": "NIFTYSMLCAP250.NS"},
]


def fetch_fund_nav(key: str, code: int) -> pd.Series:
    cache = NAV_DIR / f"{key}.csv"
    if cache.exists() and cache.stat().st_size > 500:
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date").sort_index()
        return df["nav"].resample("W-FRI").last()

    r = requests.get(f"https://api.mfapi.in/mf/{code}", headers=UA, timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = [{"date": pd.to_datetime(d["date"], format="%d-%m-%Y"), "nav": float(d["nav"])} for d in payload["data"]]
    df = pd.DataFrame(rows).sort_values("date")
    df.to_csv(cache, index=False)
    return df.set_index("date")["nav"].resample("W-FRI").last()


def load_benchmark_weekly(ticker: str) -> pd.Series:
    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        params={"interval": "1d", "range": "15y"}, headers=UA, timeout=30,
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
    print(f"Fetching {len(ALL_SMALLCAP_FUNDS)} funds...")
    fund_series = {}
    for f in ALL_SMALLCAP_FUNDS:
        try:
            s = fetch_fund_nav(f["key"], f["code"])
            fund_series[f["key"]] = s
            print(f"  {f['name']:32s} {s.first_valid_index().date()} -> {s.last_valid_index().date()} ({s.notna().sum()} weeks)")
        except Exception as e:
            print(f"  {f['name']:32s} FAILED: {e}")
        time.sleep(0.15)

    print("\nFetching benchmarks...")
    bench_series = {}
    for b in BENCHMARKS:
        s = load_benchmark_weekly(b["ticker"])
        bench_series[b["key"]] = s
        print(f"  {b['name']:20s} {s.first_valid_index().date()} -> {s.last_valid_index().date()} ({s.notna().sum()} weeks)")

    fund_keys_ok = list(fund_series.keys())
    all_dates = sorted(set().union(
        *[s.index for s in fund_series.values()],
        *[s.index for s in bench_series.values()],
    ))

    last = all_dates[-1]
    everything = list(fund_series.values()) + list(bench_series.values())
    if any(last not in s.index or pd.isna(s.get(last)) for s in everything):
        print(f"\nDropping incomplete trailing week: {last.date()}")
        all_dates = all_dates[:-1]

    date_strs = [d.strftime("%Y-%m-%d") for d in all_dates]

    def series_to_list(s: pd.Series) -> list:
        s = s.reindex(all_dates)
        return [None if pd.isna(v) else round(float(v), 4) for v in s]

    fund_meta = {f["key"]: f for f in ALL_SMALLCAP_FUNDS}
    out = {
        "as_of": date_strs[-1],
        "dates": date_strs,
        "funds": [
            {"key": k, "name": fund_meta[k]["name"], "category": "Small Cap", "values": series_to_list(fund_series[k])}
            for k in fund_keys_ok
        ],
        "benchmarks": [
            {"key": b["key"], "name": b["name"], "values": series_to_list(bench_series[b["key"]])}
            for b in BENCHMARKS
        ],
    }

    out_path = BASE / "leaderboard_full_dataset.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.0f} KB, {len(date_strs)} weeks, "
          f"{len(fund_keys_ok)} funds, {len(BENCHMARKS)} benchmarks)")


if __name__ == "__main__":
    main()
