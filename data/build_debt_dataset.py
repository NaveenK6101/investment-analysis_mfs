"""Debt / Parking category: a curated set of large-AMC Direct-Growth debt funds
for parking cash short term, plus a liquid-fund composite that serves as both the
category benchmark and the "Debt" asset-class series.

Universe (picked once from mfapi.in by name + scheme_category, all with >=6y of
history, live NAVs, Direct+Growth; the biggest AMCs per type so the list stays
small and stable - re-pick by editing FUNDS below):
  Overnight (1 day) . Liquid (up to 91d) . Money Market (up to 1y)
  Ultra Short (3-6m) . Short Duration (1-3y; NOT for <1 month parking -
  these can and do lose money when yields rise).
Benchmark = equal-weight of the 6 Liquid funds, rebased to 100, so "excess"
means "beats plain liquid cash".
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from data_fetch_utils import fetch_mfapi_weekly

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)

FUNDS = [  # (scheme_code, type)
    (119110, "Overnight"), (119833, "Overnight"), (145536, "Overnight"), (146141, "Overnight"),
    (119091, "Liquid"), (119800, "Liquid"), (120197, "Liquid"), (119766, "Liquid"),
    (119568, "Liquid"), (120389, "Liquid"),
    (119092, "Money Market"), (120211, "Money Market"), (119746, "Money Market"),
    (119821, "Money Market"), (119511, "Money Market"),
    (118942, "Ultra Short"), (120676, "Ultra Short"), (119750, "Ultra Short"),
    (119501, "Ultra Short"), (119828, "Ultra Short"),
    (119016, "Short Duration"), (120754, "Short Duration"), (119816, "Short Duration"),
]


def splice_unit_changes(s: pd.Series) -> pd.Series:
    """mfapi history has a few face-value rebases (e.g. 10 -> 1000 Rs/unit) that show up as a
    ~10x/100x one-week jump. A debt fund never moves >3x in a week, so treat any such jump as
    a unit change and scale everything before it, keeping the return path continuous."""
    s = s.copy()
    v = s.dropna()
    for i in range(len(v) - 1, 0, -1):
        r = v.iloc[i] / v.iloc[i - 1]
        if r > 3 or r < 1 / 3:
            s.loc[s.index <= v.index[i - 1]] *= r
            print(f"    unit change at {v.index[i].date()} (x{r:.1f}) - earlier history rescaled")
            v = s.dropna()
    return s


def main() -> None:
    import time
    schemes = {s["schemeCode"]: s["schemeName"] for s in json.load(open(BASE / "all_schemes.json", encoding="utf-8"))}
    series, NAMES = {}, {}
    for code, typ in FUNDS:
        for attempt in range(4):  # mfapi.in is sometimes slow; the cache fallback only exists after the first success
            try:
                s, _ = fetch_mfapi_weekly(NAV_DIR / f"debt_{code}.csv", code)
                break
            except Exception as e:
                print(f"    {code} attempt {attempt + 1} failed: {type(e).__name__}")
                time.sleep(3)
        else:
            raise RuntimeError(f"could not fetch {code}")
        s = splice_unit_changes(s)
        NAMES[code] = schemes[code]
        series[code] = s
        print(f"  {code} {typ:14s} {s.first_valid_index().date()} -> {s.last_valid_index().date()}  {NAMES[code][:55]}", flush=True)

    all_dates = sorted(set().union(*[s.index for s in series.values()]))
    idx = pd.DatetimeIndex(all_dates)
    df = pd.DataFrame({c: s.reindex(idx) for c, s in series.items()})

    # composite benchmark: equal-weight of liquid funds, each rebased to 100 at the common start
    liquid_codes = [c for c, t in FUNDS if t == "Liquid"]
    liq = df[liquid_codes].ffill(limit=2)
    start = liq.dropna().index[0]
    liq = liq.loc[start:]
    comp = (100 * liq / liq.iloc[0]).mean(axis=1, skipna=False)
    bench_vals = [None] * (len(idx) - len(comp)) + [None if pd.isna(v) else round(float(v), 4) for v in comp]

    dates = [d.strftime("%Y-%m-%d") for d in idx]
    funds = []
    for code, typ in FUNDS:
        vals = [None if pd.isna(v) else round(float(v), 4) for v in df[code]]
        funds.append({"key": f"debt_{code}", "name": NAMES[code], "category": "Debt / Parking", "values": vals})

    out = {"dates": dates, "funds": funds,
           "benchmark": {"key": "liquid", "name": "Liquid funds (composite)", "values": bench_vals}}
    with open(BASE / "debt_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote debt_dataset.json ({len(funds)} funds, benchmark starts {start.date()}, latest level {bench_vals[-1]})")


if __name__ == "__main__":
    main()
