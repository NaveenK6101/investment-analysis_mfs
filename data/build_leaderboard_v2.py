"""Build the full multi-category dataset: Small/Large/Flexi/Multi Cap + Multi
Asset (184 funds) + 4 benchmark indices. Adds a category field per fund so the
page can filter to one category or show everything.

Benchmark choice per category is a real methodological decision, not a
default to ignore:
  - Small Cap  -> Nifty Smallcap 250 (size-matched, per the earlier "which
                  benchmark" lesson)
  - Large Cap  -> Nifty 100 (the large-cap-representative index)
  - Flexi Cap  -> Nifty 500 (flexi cap funds can hold any market-cap mix, so
                  the broadest index is the fairest match)
  - Multi Cap  -> Nifty 500 (SEBI mandates a fixed 25/25/25+ split across
                  large/mid/small, so no single-segment index fits; the
                  broad index is the least-wrong choice)
  - Multi Asset -> Nifty 500, WITH A CAVEAT the UI must show: these funds
                  hold bonds/gold/etc by mandate, so under-performing a pure
                  equity index is often correct behaviour, not weakness
This only sets each category's *default* selection - the viewer can still
pick any of the 4 benchmarks manually, same as before.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

CATEGORY_DEFAULT_BENCH = {
    "Small Cap": "smallcap250",
    "Large Cap": "nifty100",
    "Flexi Cap": "nifty500",
    "Multi Cap": "nifty500",
    "Multi Asset": "nifty500",
}

BENCHMARKS = [
    {"key": "nifty50",     "name": "Nifty 50",           "ticker": "^NSEI"},
    {"key": "nifty100",    "name": "Nifty 100",          "ticker": "^CNX100"},
    {"key": "nifty500",    "name": "Nifty 500",          "ticker": "^CRSLDX"},
    {"key": "smallcap250", "name": "Nifty Smallcap 250", "ticker": "NIFTYSMLCAP250.NS"},
]


def slugify(name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:40]


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
    # ---- load the existing 36 small-cap funds (already fetched, keys match nav_all/*.csv) ----
    from all_smallcap_funds import ALL_SMALLCAP_FUNDS
    small_cap_entries = [{**f, "category": "Small Cap"} for f in ALL_SMALLCAP_FUNDS]

    # ---- load the newly verified category universe ----
    category_universe = json.load(open(BASE / "category_universe.json", encoding="utf-8"))

    all_entries = list(small_cap_entries)
    seen_keys = {e["key"] for e in all_entries}
    for category, funds in category_universe.items():
        for f in funds:
            key = slugify(f["name"])
            # avoid key collisions across categories (e.g. two AMCs both named similarly)
            base_key = key
            n = 1
            while key in seen_keys:
                n += 1
                key = f"{base_key}_{n}"
            seen_keys.add(key)
            all_entries.append({"key": key, "code": f["code"], "name": f["name"], "category": category})

    print(f"Fetching {len(all_entries)} funds total ({len(small_cap_entries)} small-cap cached + "
          f"{len(all_entries) - len(small_cap_entries)} new)...")

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
        s = load_benchmark_weekly(b["ticker"])
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
        "category_default_benchmark": CATEGORY_DEFAULT_BENCH,
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

    out_path = BASE / "leaderboard_full_dataset.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    counts = {}
    for f in out["funds"]:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    print(f"\nWrote {out_path} ({size_kb:.0f} KB, {len(date_strs)} weeks, {len(out['funds'])} funds)")
    for cat, n in counts.items():
        print(f"  {cat:14s} {n}")


if __name__ == "__main__":
    main()
