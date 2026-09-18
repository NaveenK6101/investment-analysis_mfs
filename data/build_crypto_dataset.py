"""Fetch crypto prices (USD, from Yahoo, confirmed working in
probe_asset_universe.ps1: BTC-USD/ETH-USD/SOL-USD/XRP-USD all return full
multi-year history) and convert to INR via USDINR=X, so they sit on the
same footing as the rest of this project's INR-denominated fund NAVs.

Crypto trades 24/7; everything else in this project is a Friday NAV/close.
Resampling crypto to W-FRI too keeps the comparison apples-to-apples on the
SAME weekly grid as the MF data, at the cost of ignoring intraweek moves -
the same trade-off already made for every other benchmark in this project.
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

COINS = [
    {"key": "btc", "name": "Bitcoin", "ticker": "BTC-USD"},
    {"key": "eth", "name": "Ethereum", "ticker": "ETH-USD"},
    {"key": "sol", "name": "Solana", "ticker": "SOL-USD"},
    {"key": "xrp", "name": "XRP", "ticker": "XRP-USD"},
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
    print(f"USDINR: {fx.first_valid_index().date()} -> {fx.last_valid_index().date()} "
          f"({fx.notna().sum()} weeks), latest rate {fx.dropna().iloc[-1]:.2f}")

    coin_series_inr = {}
    for c in COINS:
        usd = fetch_weekly(c["ticker"], f"crypto_{c['key']}_usd")
        common_idx = usd.index.intersection(fx.index)
        inr = (usd.reindex(common_idx) * fx.reindex(common_idx)).dropna()
        coin_series_inr[c["key"]] = inr
        print(f"  {c['name']:10s} {inr.first_valid_index().date()} -> {inr.last_valid_index().date()} "
              f"({inr.notna().sum()} weeks), latest INR {inr.iloc[-1]:,.0f}")

    all_dates = sorted(set().union(*[s.index for s in coin_series_inr.values()]))
    last = all_dates[-1]
    if any(last not in s.index for s in coin_series_inr.values()):
        print(f"Dropping incomplete trailing week: {last.date()}")
        all_dates = all_dates[:-1]
    date_strs = [d.strftime("%Y-%m-%d") for d in all_dates]

    def series_to_list(s: pd.Series) -> list:
        s = s.reindex(all_dates)
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    funds = [
        {"key": f"crypto_{c['key']}", "name": c["name"] + " (INR)", "category": "Crypto",
         "values": series_to_list(coin_series_inr[c["key"]])}
        for c in COINS
    ]

    out = {"dates": date_strs, "funds": funds}
    out_path = BASE / "crypto_dataset.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote {out_path} ({len(funds)} coins, {len(date_strs)} weeks)")


if __name__ == "__main__":
    main()
