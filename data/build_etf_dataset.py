"""Investable US-listed ETFs, in rupee terms: "ETF - Metals" and "ETF - World Markets".

Why this exists: the Metals and Global Markets categories show the underlying metal or local index,
which you cannot buy. These rows are the funds an Indian investor can actually hold through an
LRS platform (Vested, INDmoney, Stockal, Interactive Brokers) - so the gap between "the signal"
and "what the fund delivered" is visible next to each other. (Measured 2026-10: the copper futures
fund lagged copper by ~5 points a year, while the MSCI Korea/Taiwan ETFs beat the KOSPI/TAIEX
because they hold different, more concentrated baskets.)

Method: Yahoo's ADJUSTED close in USD (price plus reinvested distributions, i.e. total return)
x USDINR, weekly Friday, each fund rebased to 100 at its own first week. This differs from the
Global Markets index rows, which are price-only - the page banner says so. Expense ratios are NOT
modelled separately (they are already inside the fund's price). FX markup, TCS, tax and US estate
tax are not modelled either.

Theme ETFs: every fund in etf_theme_universe.json (written by build_etf_theme_map.py, which runs just
before this step) is added weekly as its own "ETF Theme - <theme>" category, with the theme's
equal-weight peer average as the default benchmark, so "Excess" means "vs its peers". No per-fund
price cache is committed (hundreds of daily histories would bloat the repo); a failed fetch falls
back to the values published last time, and the gate flags the fund as missing the newest week.

Added to refresh_all.py as step 8d; data/check_refresh.py's gate covers the new categories.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from data_fetch_utils import UA, fetch_yahoo_weekly

BASE = Path(__file__).resolve().parent
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)

NOTE = {
    "physical": "Holds the metal itself, so it follows the price closely apart from fees. US-listed and priced in USD; "
                "the return here includes the rupee-dollar move.",
    "futures": "Holds futures contracts, not the metal. Rolling costs can make it lag the metal (the copper fund lagged "
               "copper by roughly 5 points a year in a 2026 check). US-listed, USD; the return includes the rupee-dollar move.",
    "miners": "A basket of company shares, not the metal: it moves with the stock market as well as the metal and has fallen "
              "much harder than the metal in past downturns. US-listed, USD; the return includes the rupee-dollar move.",
    "country": "US-listed fund following an MSCI index for this country, priced in USD, so the return includes the "
               "rupee-dollar move. It holds a different, often more concentrated, basket than the local headline index.",
    "region": "US-listed broad fund priced in USD; the return includes the rupee-dollar move.",
}
METALS, WORLD = "ETF - Metals", "ETF - World Markets"
THEME_PREFIX = "ETF Theme - "
UNIVERSE = BASE / "etf_theme_universe.json"
THEME_NOTE = ("US-listed thematic ETF, priced in USD, so the return includes the rupee-dollar move. It was grouped into this "
              "theme by keywords in its name - check the factsheet for what it really holds. The benchmark is the "
              "equal-weight average of the theme's ETFs, so Excess means 'vs its peers', not vs the market.")

# (ticker, display name, category, kind)
ETFS = [
    ("GLD", "GLD - Gold (SPDR Gold Shares, physical)", METALS, "physical"),
    ("SLV", "SLV - Silver (iShares Silver Trust, physical)", METALS, "physical"),
    ("PPLT", "PPLT - Platinum (abrdn Physical Platinum, physical)", METALS, "physical"),
    ("PALL", "PALL - Palladium (abrdn Physical Palladium, physical)", METALS, "physical"),
    ("CPER", "CPER - Copper (US Copper Index Fund, futures)", METALS, "futures"),
    ("DBB", "DBB - Base metals: copper/aluminium/zinc (Invesco DB, futures)", METALS, "futures"),
    ("COPX", "COPX - Copper miners (Global X, shares)", METALS, "miners"),
    ("GDX", "GDX - Gold miners (VanEck, shares)", METALS, "miners"),
    ("SIL", "SIL - Silver miners (Global X, shares)", METALS, "miners"),
    ("REMX", "REMX - Rare earth & strategic metals miners (VanEck, shares)", METALS, "miners"),
    ("URA", "URA - Uranium miners (Global X, shares)", METALS, "miners"),
    ("LIT", "LIT - Lithium & battery tech (Global X, shares)", METALS, "miners"),
    # broad / regional
    ("VOO", "VOO - USA S&P 500 (Vanguard)", WORLD, "region"),
    ("QQQ", "QQQ - USA Nasdaq 100 (Invesco)", WORLD, "region"),
    ("VT", "VT - World, all countries (Vanguard)", WORLD, "region"),
    ("VEA", "VEA - Developed markets ex-US (Vanguard)", WORLD, "region"),
    ("VGK", "VGK - Europe (Vanguard)", WORLD, "region"),
    ("EEM", "EEM - Emerging markets (iShares)", WORLD, "region"),
    # single countries
    ("EWJ", "EWJ - Japan (iShares MSCI)", WORLD, "country"),
    ("EWG", "EWG - Germany (iShares MSCI)", WORLD, "country"),
    ("EWU", "EWU - United Kingdom (iShares MSCI)", WORLD, "country"),
    ("EWQ", "EWQ - France (iShares MSCI)", WORLD, "country"),
    ("EWL", "EWL - Switzerland (iShares MSCI)", WORLD, "country"),
    ("EWI", "EWI - Italy (iShares MSCI)", WORLD, "country"),
    ("EWP", "EWP - Spain (iShares MSCI)", WORLD, "country"),
    ("EWD", "EWD - Sweden (iShares MSCI)", WORLD, "country"),
    ("EPOL", "EPOL - Poland (iShares MSCI)", WORLD, "country"),
    ("EWC", "EWC - Canada (iShares MSCI)", WORLD, "country"),
    ("EWA", "EWA - Australia (iShares MSCI)", WORLD, "country"),
    ("EWZ", "EWZ - Brazil (iShares MSCI)", WORLD, "country"),
    ("EWW", "EWW - Mexico (iShares MSCI)", WORLD, "country"),
    ("MCHI", "MCHI - China (iShares MSCI)", WORLD, "country"),
    ("EWH", "EWH - Hong Kong (iShares MSCI)", WORLD, "country"),
    ("EWS", "EWS - Singapore (iShares MSCI)", WORLD, "country"),
    ("EIDO", "EIDO - Indonesia (iShares MSCI)", WORLD, "country"),
    ("VNM", "VNM - Vietnam (VanEck)", WORLD, "country"),
    ("THD", "THD - Thailand (iShares MSCI)", WORLD, "country"),
    ("TUR", "TUR - Turkey (iShares MSCI)", WORLD, "country"),
    ("EZA", "EZA - South Africa (iShares MSCI)", WORLD, "country"),
    ("KSA", "KSA - Saudi Arabia (iShares MSCI)", WORLD, "country"),
    ("EWT", "EWT - Taiwan (iShares MSCI)", WORLD, "country"),
    ("EWY", "EWY - South Korea (iShares MSCI)", WORLD, "country"),
    ("INDA", "INDA - India (iShares MSCI) - cross-check against the Nifty rows", WORLD, "country"),
]


def fetch_adj_weekly(ticker: str, cached: bool = True) -> pd.Series:
    """Weekly (Friday) ADJUSTED close in USD; with cached=True also kept in nav_all/ and used if the fetch fails."""
    cache = NAV_DIR / f"etf_{ticker}.csv"
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                             params={"interval": "1d", "range": "15y"}, headers=UA, timeout=30)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            adj = res["indicators"]["adjclose"][0]["adjclose"]
            s = pd.Series({pd.Timestamp.fromtimestamp(t).normalize(): c
                           for t, c in zip(res["timestamp"], adj) if c is not None}).sort_index()
            if s.empty:
                raise ValueError("empty price history")
            # Yahoo recomputes dividend-adjusted history with ~1e-7 float noise on every call, which
            # would make git rewrite every line of every cache each week. 3 decimals is far below any
            # real price move and keeps weekly diffs to the genuinely new rows.
            s = s.round(3)
            if cached:
                pd.DataFrame({"date": s.index, "adjclose": s.values}).to_csv(cache, index=False)
            return s.resample("W-FRI").last()
        except Exception as e:
            last_err = e
            time.sleep(2)
    if cached and cache.exists() and cache.stat().st_size > 500:
        print(f"    {ticker}: fetch failed ({last_err}) - using cached {cache.name}")
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date")["adjclose"].sort_index()
        return df.resample("W-FRI").last()
    raise RuntimeError(f"{ticker}: fetch failed and no cache ({last_err})")


def clean_name(raw: str) -> str:
    """Drop trailing legal words ('ETF', 'Trust', 'ETV' ...) but never the first words ('First Trust ...')."""
    parts = raw.split()
    while len(parts) > 1 and parts[-1].strip("(),.").upper() in {"ETF", "FUND", "TRUST", "ETV", "SHARES", "UNITS", "LP", "ETN"}:
        parts.pop()
    return " ".join(parts)


def theme_peer_average(members: dict, dates: list[str]) -> list:
    """Equal-weight chain-linked average of the members' weekly returns (point-in-time: needs >= 3 with data)."""
    df = pd.DataFrame(members)
    ret = df.pct_change(fill_method=None)
    avg = ret.mean(axis=1).where(ret.notna().sum(axis=1) >= 3)
    first = avg.first_valid_index()
    if first is None:
        return [None] * len(dates)
    level = (1 + avg.fillna(0)).cumprod()
    level = (level / level[first] * 100).where(level.index >= first)
    by_str = {d.strftime("%Y-%m-%d"): v for d, v in level.items()}
    return [None if pd.isna(by_str.get(d)) or by_str.get(d) is None else round(float(by_str[d]), 2) for d in dates]


def load_theme_etfs() -> list[dict]:
    if not UNIVERSE.exists():
        print("  no etf_theme_universe.json - skipping theme ETFs")
        return []
    return json.loads(UNIVERSE.read_text(encoding="utf-8"))["etfs"]


def main() -> None:
    cap = json.load(open(BASE / "leaderboard_full_dataset.json", encoding="utf-8"))
    nifty50 = next(b for b in cap["benchmarks"] if b["key"] == "nifty50")
    fx, _ = fetch_yahoo_weekly(NAV_DIR / "etf_fx_usdinr.csv", "USDINR=X")

    inr_series = {}
    for ticker, name, cat, kind in ETFS:
        usd = fetch_adj_weekly(ticker)
        common = usd.index.intersection(fx.index)
        inr = (usd.reindex(common) * fx.reindex(common)).dropna()
        inr_series[ticker] = inr
        print(f"  {ticker:5s} {inr.index[0].date()} -> {inr.index[-1].date()} ({len(inr)} wks)  {name[:56]}", flush=True)
        time.sleep(0.2)

    # ---- theme ETFs: weekly INR series for every universe member, fetched in parallel, nothing cached
    theme_etfs = load_theme_etfs()
    previous = {}
    prev_path = BASE / "etf_dataset.json"
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        for f in prev["funds"]:
            if f["key"].startswith("etft_"):
                previous[f["key"]] = pd.Series({pd.Timestamp(d): v for d, v in zip(prev["dates"], f["values"]) if v is not None})

    def get_theme(e: dict):
        try:
            return e["symbol"], fetch_adj_weekly(e["symbol"], cached=False)
        except Exception as err:  # noqa: BLE001
            return e["symbol"], err

    theme_inr: dict[str, pd.Series] = {}
    stale: list[str] = []
    if theme_etfs:
        print(f"  fetching {len(theme_etfs)} theme ETFs ...", flush=True)
        with ThreadPoolExecutor(max_workers=5) as ex:
            for sym, res in ex.map(get_theme, theme_etfs):
                if isinstance(res, Exception):
                    old = previous.get(f"etft_{sym.lower()}")
                    if old is not None and len(old):
                        theme_inr[sym] = old
                        stale.append(sym)
                    continue
                common = res.index.intersection(fx.index)
                theme_inr[sym] = (res.reindex(common) * fx.reindex(common)).dropna()
        if stale:
            print(f"  WARNING: fetch failed for {len(stale)} theme ETFs, kept last published values: {stale[:12]}")
        print(f"  theme ETFs priced: {len(theme_inr)}/{len(theme_etfs)}")

    all_dates = set(cap["dates"])
    for s in inr_series.values():
        all_dates |= set(s.index.strftime("%Y-%m-%d"))
    for s in theme_inr.values():
        all_dates |= set(s.index.strftime("%Y-%m-%d"))
    dates = sorted(all_dates)

    funds = []
    for ticker, name, cat, kind in ETFS:
        by_str = {d.strftime("%Y-%m-%d"): v for d, v in inr_series[ticker].items()}
        values = [by_str.get(d) for d in dates]
        start = next(i for i, v in enumerate(values) if v is not None)
        base = values[start]
        rebased = [None if v is None else round(100.0 * v / base, 4) for v in values[start:]]
        note = NOTE[kind] + (" Tracks MSCI India, so it should roughly follow the Nifty rows." if ticker == "INDA" else "")
        funds.append({"key": f"etf_{ticker.lower()}", "name": name, "category": cat,
                      "values": [None] * start + rebased, "access_note": note})

    # ---- theme categories + their peer-average benchmarks
    peer_benchmarks, default_bench = [], {}
    by_theme: dict[str, list[dict]] = {}
    for e in theme_etfs:
        if e["symbol"] in theme_inr:
            by_theme.setdefault(e["theme"], []).append(e)
    for theme, members in sorted(by_theme.items()):
        if len(members) < 3:
            continue
        cat = THEME_PREFIX + theme
        key = "themepeer_" + re.sub(r"[^a-z0-9]+", "_", theme.lower()).strip("_")
        peer_benchmarks.append({"key": key, "name": f"{theme} - peer average (ETFs)",
                                "values": theme_peer_average({m["symbol"]: theme_inr[m["symbol"]] for m in members}, dates)})
        default_bench[cat] = key
        for m in sorted(members, key=lambda x: -x["dollar_vol_m"]):
            by_str = {d.strftime("%Y-%m-%d"): v for d, v in theme_inr[m["symbol"]].items()}
            values = [by_str.get(d) for d in dates]
            start = next((i for i, v in enumerate(values) if v is not None), None)
            if start is None:
                continue
            base = values[start]
            rebased = [None if v is None else round(100.0 * v / base, 2) for v in values[start:]]
            funds.append({"key": f"etft_{m['symbol'].lower()}", "name": f"{m['symbol']} - {clean_name(m['name'])}",
                          "category": cat, "values": [None] * start + rebased, "access_note": THEME_NOTE})

    idx_map = {d: i for i, d in enumerate(cap["dates"])}
    bench_vals = [nifty50["values"][idx_map[d]] if d in idx_map else None for d in dates]
    out = {"dates": dates, "funds": funds, "benchmark": {"key": "nifty50", "name": "Nifty 50", "values": bench_vals},
           "benchmarks": peer_benchmarks, "category_default_benchmark": default_bench}
    with open(BASE / "etf_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    n_theme = sum(f["category"].startswith(THEME_PREFIX) for f in funds)
    print(f"\nWrote etf_dataset.json ({len(funds)} ETFs: {sum(f['category'] == METALS for f in funds)} metals, "
          f"{sum(f['category'] == WORLD for f in funds)} world, {n_theme} theme ETFs in {len(default_bench)} themes)")


if __name__ == "__main__":
    main()
