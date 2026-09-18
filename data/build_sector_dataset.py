"""Build the sector-fund dataset: 122 sectoral/thematic funds across 8
verified sector buckets + benchmark indices.

Benchmark choice per sector, like the cap-category dataset, is a real call:
  - Banking & Financial Services -> Nifty Bank (^NSEBANK) - confirmed working
    on Yahoo (full 10y+ history), a true size/sector match.
  - Technology / IT              -> Nifty IT (^CNXIT) - confirmed working.
  - Pharma & Healthcare          -> Nifty Pharma (^CNXPHARMA) - confirmed working.
  - Consumption/FMCG, Infrastructure, PSU, Energy & Power, Manufacturing ->
    Nifty 500 (broad market), because their matching Nifty sector indices
    (^CNXFMCG, ^CNXINFRA, ^CNXPSUBANK, ^CNXENERGY, no manufacturing index)
    return only ~1 month of history via Yahoo's chart API (confirmed broken
    in probe_asset_universe.ps1) - unusable for a multi-year relative
    strength comparison. Nifty 500 is the least-wrong broad fallback; viewer
    can still switch benchmarks manually in the UI.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from data_fetch_utils import fetch_mfapi_weekly, fetch_yahoo_weekly

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)

SECTOR_DEFAULT_BENCH = {
    "Banking & Financial Services": "niftybank",
    "Technology / IT": "niftyit",
    "Pharma & Healthcare": "niftypharma",
    "Consumption / FMCG": "nifty500",
    "Infrastructure": "nifty500",
    "PSU": "nifty500",
    "Energy & Power": "nifty500",
    "Manufacturing": "nifty500",
}

BENCHMARKS = [
    {"key": "nifty50",     "name": "Nifty 50",           "ticker": "^NSEI"},
    {"key": "nifty500",    "name": "Nifty 500",          "ticker": "^CRSLDX"},
    {"key": "niftybank",   "name": "Nifty Bank",         "ticker": "^NSEBANK"},
    {"key": "niftyit",     "name": "Nifty IT",           "ticker": "^CNXIT"},
    {"key": "niftypharma", "name": "Nifty Pharma",       "ticker": "^CNXPHARMA"},
]


def slugify(name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:40]


def fetch_fund_nav(key: str, code: int) -> pd.Series:
    series, _ = fetch_mfapi_weekly(NAV_DIR / f"{key}.csv", code)
    return series


def load_benchmark_weekly(key: str, ticker: str) -> pd.Series:
    series, _ = fetch_yahoo_weekly(NAV_DIR / f"bench_{key}.csv", ticker)
    return series


def main() -> None:
    sector_universe = json.load(open(BASE / "sector_universe.json", encoding="utf-8"))

    all_entries = []
    seen_keys = set()
    for sector, funds in sector_universe.items():
        for f in funds:
            key = slugify(f["name"])
            base_key = key
            n = 1
            while key in seen_keys:
                n += 1
                key = f"{base_key}_{n}"
            seen_keys.add(key)
            all_entries.append({"key": key, "code": f["code"], "name": f["name"], "category": sector})

    print(f"Fetching {len(all_entries)} sector funds...")

    fund_series = {}
    fund_meta = {}
    failed = []
    for i, f in enumerate(all_entries):
        try:
            s = fetch_fund_nav(f["key"], f["code"])
            fund_series[f["key"]] = s
            fund_meta[f["key"]] = f
            if (i + 1) % 20 == 0:
                print(f"  ...{i+1}/{len(all_entries)}")
        except Exception as e:
            failed.append((f["name"], str(e)))
        time.sleep(0.08)

    if failed:
        print(f"\n{len(failed)} funds FAILED to fetch:")
        for name, err in failed:
            print(f"  {name}: {err}")

    print(f"\nFetching benchmarks...")
    bench_series = {}
    for b in BENCHMARKS:
        s = load_benchmark_weekly(b["key"], b["ticker"])
        bench_series[b["key"]] = s
        print(f"  {b['name']:20s} {s.first_valid_index().date()} -> {s.last_valid_index().date()} ({s.notna().sum()} weeks)")

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

    out = {
        "as_of": date_strs[-1],
        "dates": date_strs,
        "category_default_benchmark": SECTOR_DEFAULT_BENCH,
        "funds": [
            {"key": k, "name": fund_meta[k]["name"], "category": fund_meta[k]["category"],
             "values": series_to_list(fund_series[k])}
            for k in fund_series
        ],
        "benchmarks": [
            {"key": b["key"], "name": b["name"], "values": series_to_list(bench_series[b["key"]])}
            for b in BENCHMARKS
        ],
    }

    out_path = BASE / "sector_dataset.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    counts = {}
    for f in out["funds"]:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    print(f"\nWrote {out_path} ({size_kb:.0f} KB, {len(date_strs)} weeks, {len(out['funds'])} funds)")
    for cat, n in counts.items():
        print(f"  {cat:32s} {n}")


if __name__ == "__main__":
    main()
