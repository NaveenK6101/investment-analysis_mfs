"""Fetch Gold, Silver and Copper futures (USD, from Yahoo - GC=F/SI=F/HG=F,
all confirmed working with full multi-year history) and convert to INR via
USDINR=X, same pattern as build_crypto_dataset.py. One "Metals" category,
not three separate ones - these are the classic industrial/precious-metal
trio investors compare as a single group.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

METALS = [
    {"key": "gold", "name": "Gold (INR, per troy oz)", "ticker": "GC=F"},
    {"key": "silver", "name": "Silver (INR, per troy oz)", "ticker": "SI=F"},
    {"key": "copper", "name": "Copper (INR, per lb)", "ticker": "HG=F"},  # COMEX quotes copper per pound, not per oz
]
FX_TICKER = "USDINR=X"


def fetch_weekly(ticker: str, cache_name: str) -> pd.Series:
    cache = NAV_DIR / f"{cache_name}.csv"
    if cache.exists() and cache.stat().st_size > 500:
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date").sort_index()
        return df["close"].resample("W-FRI").last()

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
    pd.DataFrame({"date": s.index, "close": s.values}).to_csv(cache, index=False)
    return s.resample("W-FRI").last()


def main() -> None:
    fx = fetch_weekly(FX_TICKER, "fx_usdinr")

    metal_series_inr = {}
    for m in METALS:
        usd = fetch_weekly(m["ticker"], f"metal_{m['key']}_usd")
        common_idx = usd.index.intersection(fx.index)
        inr = (usd.reindex(common_idx) * fx.reindex(common_idx)).dropna()
        metal_series_inr[m["key"]] = inr
        print(f"  {m['name']:8s} {inr.first_valid_index().date()} -> {inr.last_valid_index().date()} "
              f"({inr.notna().sum()} weeks), latest INR {inr.iloc[-1]:,.2f}")

    all_dates = sorted(set().union(*[s.index for s in metal_series_inr.values()]))
    last = all_dates[-1]
    if any(last not in s.index for s in metal_series_inr.values()):
        print(f"Dropping incomplete trailing week: {last.date()}")
        all_dates = all_dates[:-1]
    date_strs = [d.strftime("%Y-%m-%d") for d in all_dates]

    def series_to_list(s: pd.Series) -> list:
        s = s.reindex(all_dates)
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    funds = [
        {"key": f"metal_{m['key']}", "name": m["name"], "category": "Metals",
         "values": series_to_list(metal_series_inr[m["key"]])}
        for m in METALS
    ]

    out = {"dates": date_strs, "funds": funds}
    out_path = BASE / "metals_dataset.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote {out_path} ({len(funds)} metals, {len(date_strs)} weeks)")


if __name__ == "__main__":
    main()
