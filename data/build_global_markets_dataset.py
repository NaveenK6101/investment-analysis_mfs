"""Global Markets: major foreign equity indices, converted to INR terms and
compared against Nifty 50 - "which country's stock market is winning, for
an Indian investor" as a DIFFERENT question from Asset Classes (which asks
equity-vs-gold-vs-debt-vs-crypto within India). Kept as its own category
rather than folded into Asset Classes for that reason.

The one thing that makes this honest rather than a repeat of the viral
"if you'd invested Rs1 crore in X market" social posts: those compare raw
LOCAL-CURRENCY index returns, which is not what an Indian investor actually
realizes - you convert INR -> foreign currency -> buy the index -> convert
back. So each index here is built as (local price) * (INR per unit of that
currency), same construction as build_metals_dataset.py already uses for
gold/silver in USD -> INR. All five foreign-currency pairs (USD/EUR/JPY/
TWD/KRW -> INR) were confirmed directly available on Yahoo, no cross-rate
needed (2026-09-30).

A second honesty check this project hasn't needed before: a market winning
this table does NOT mean an Indian retail investor can actually put money
there. Real access is only through overseas mutual fund FoFs, and SEBI has
repeatedly paused fresh inflows into several of these because of an RBI-wide
cap on how much the whole Indian MF industry can send overseas. Taiwan and
South Korea in particular have little to no retail-accessible route from
India. Each fund below carries a static "access_note" saying so - this is
NOT fetched data, just a fact worth stating plainly next to the return.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from data_fetch_utils import fetch_yahoo_weekly

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)

MARKETS = [
    {"key": "sp500", "name": "S&P 500 (USA)", "index_ticker": "^GSPC", "fx_ticker": "USDINR=X",
     "access_note": "Accessible via several Indian FoFs (e.g. Nasdaq 100/S&P 500 feeder funds), "
                     "though SEBI has periodically capped fresh inflows into these on RBI's overseas-investment limit."},
    {"key": "dax", "name": "DAX (Germany)", "index_ticker": "^GDAXI", "fx_ticker": "EURINR=X",
     "access_note": "Very limited retail-accessible route from India - a rare Europe-focused FoF at best, "
                     "subject to the same overseas-investment cap."},
    {"key": "nikkei225", "name": "Nikkei 225 (Japan)", "index_ticker": "^N225", "fx_ticker": "JPYINR=X",
     "access_note": "A small number of Japan-focused FoFs exist (e.g. Nippon India Japan Equity), "
                     "subject to the same overseas-investment cap."},
    {"key": "taiex", "name": "TAIEX (Taiwan)", "index_ticker": "^TWII", "fx_ticker": "TWDINR=X",
     "access_note": "No common retail-accessible fund route from India."},
    {"key": "kospi", "name": "KOSPI (South Korea)", "index_ticker": "^KS11", "fx_ticker": "KRWINR=X",
     "access_note": "No common retail-accessible fund route from India."},
]


def fetch(ticker: str, cache_name: str) -> pd.Series:
    series, _ = fetch_yahoo_weekly(NAV_DIR / f"{cache_name}.csv", ticker)
    return series


def main() -> None:
    cap = json.load(open(BASE / "leaderboard_full_dataset.json", encoding="utf-8"))
    nifty50 = next(b for b in cap["benchmarks"] if b["key"] == "nifty50")

    funds = []
    all_dates = set(cap["dates"])
    market_series = {}
    for m in MARKETS:
        idx = fetch(m["index_ticker"], f"global_{m['key']}_local")
        fx = fetch(m["fx_ticker"], f"global_fx_{m['key']}")
        common = idx.index.intersection(fx.index)
        inr = (idx.reindex(common) * fx.reindex(common)).dropna()
        market_series[m["key"]] = inr
        all_dates |= set(inr.index.strftime("%Y-%m-%d"))
        print(f"  {m['name']:22s} {inr.index[0].date()} -> {inr.index[-1].date()} "
              f"({len(inr)} weeks) latest INR-terms level: {inr.iloc[-1]:,.0f}")

    dates = sorted(all_dates)
    date_idx = {d: i for i, d in enumerate(dates)}

    def reindex_from_series(s: pd.Series):
        by_str = {d.strftime("%Y-%m-%d"): v for d, v in s.items()}
        return [by_str.get(d) for d in dates]

    for m in MARKETS:
        values = reindex_from_series(market_series[m["key"]])
        start = next(i for i, v in enumerate(values) if v is not None)
        base = values[start]
        rebased = [None if v is None else round(100.0 * v / base, 4) for v in values[start:]]
        funds.append({
            "key": "globalmkt_" + m["key"], "name": m["name"], "category": "Global Markets",
            "values": [None] * start + rebased, "access_note": m["access_note"],
        })

    def reindex_bench(values, src_dates):
        idx_map = {d: i for i, d in enumerate(src_dates)}
        return [values[idx_map[d]] if d in idx_map else None for d in dates]

    out = {
        "dates": dates,
        "funds": funds,
        "benchmark": {"key": "nifty50", "name": "Nifty 50", "values": reindex_bench(nifty50["values"], cap["dates"])},
    }
    with open(BASE / "global_markets_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote global_markets_dataset.json ({len(funds)} markets vs Nifty 50, INR-converted)")


if __name__ == "__main__":
    main()
