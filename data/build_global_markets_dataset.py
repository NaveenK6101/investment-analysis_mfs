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
there without knowing the real route. Checked directly (web search + a live
Yahoo fetch of each ticker, 2026-09-30) rather than assumed:
  - Domestic Indian FoFs reach the US and, thinly, Japan - but SEBI has
    repeatedly paused fresh inflows into these under an RBI-wide cap on how
    much the whole Indian MF industry can send overseas.
  - The simplest route for all four foreign markets, that doesn't depend on
    that FoF cap at all: US-listed single-country ETFs (EWG/Germany,
    EWJ/Japan, EWT/Taiwan, EWY/S.Korea - all confirmed live, USD-denominated,
    trading on NYSE Arca), reachable the exact same way as the S&P 500 row -
    via any LRS-based India-to-US platform (Vested, INDmoney, Stockal) or a
    global broker, no multi-exchange access needed.
  - Interactive Brokers separately gives Indian residents (under RBI's LRS,
    $250k/person/year, cash equity only - no margin or derivatives) direct
    exchange access to the US, Xetra (Germany), Tokyo (Japan) and Taiwan's
    exchanges. Korea (KRX) is the one exception: IBKR's own 2026 launch terms
    explicitly exclude Indian residents from direct KRX access, so the
    EWY ETF route is the one that actually works for Korea from India.
Each fund below carries a static "access_note" reflecting this - this is
NOT fetched data, just facts worth stating plainly next to the return, and
not investment advice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from data_fetch_utils import fetch_yahoo_weekly

BASE = Path(__file__).resolve().parent  # the data/ folder, wherever the repo is checked out
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)

MARKETS = [
    {"key": "sp500", "name": "S&P 500 (USA)", "index_ticker": "^GSPC", "fx_ticker": "USDINR=X",
     "access_note": "Directly accessible via LRS-based India-to-US platforms (Vested, INDmoney, Stockal) or a "
                     "global broker (e.g. Interactive Brokers) - the simplest of these five. A few domestic FoFs "
                     "exist too, though SEBI has periodically paused fresh inflows into those specifically."},
    {"key": "dax", "name": "DAX (Germany)", "index_ticker": "^GDAXI", "fx_ticker": "EURINR=X",
     "access_note": "The US-listed iShares MSCI Germany ETF (EWG) trades in USD, so it's reachable via any "
                     "Vested-style LRS platform, same route as the S&P 500 row. Interactive Brokers also gives "
                     "Indian residents direct Xetra access under LRS."},
    {"key": "nikkei225", "name": "Nikkei 225 (Japan)", "index_ticker": "^N225", "fx_ticker": "JPYINR=X",
     "access_note": "The US-listed iShares MSCI Japan ETF (EWJ) trades in USD, reachable via any Vested-style "
                     "LRS platform. Interactive Brokers also gives Indian residents direct Tokyo Stock Exchange "
                     "access under LRS, and a few domestic Japan-focused FoFs exist too."},
    {"key": "taiex", "name": "TAIEX (Taiwan)", "index_ticker": "^TWII", "fx_ticker": "TWDINR=X",
     "access_note": "The US-listed iShares MSCI Taiwan ETF (EWT) trades in USD - the simplest route, via any "
                     "Vested-style LRS platform, no multi-exchange broker needed. Direct Taiwan exchange access "
                     "via Interactive Brokers also appears open to Indian residents, though less commonly used."},
    {"key": "kospi", "name": "KOSPI (South Korea)", "index_ticker": "^KS11", "fx_ticker": "KRWINR=X",
     "access_note": "The US-listed iShares MSCI South Korea ETF (EWY) is the route that actually works from "
                     "India: Interactive Brokers' own 2026 Korea Exchange launch terms explicitly exclude Indian "
                     "residents from direct KRX access, unlike every other market on this page."},
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
