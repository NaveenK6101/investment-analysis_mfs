"""Compute RS-Ratio / RS-Momentum time series per asset class for the Asset
Rotation Map - the exact same open RRG approximation as build_rrg_series.py
(10-week rolling z-score, twice), just applied one level up: asset classes
against the blended All-Assets benchmark instead of sectors against Nifty 500.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
WINDOW = 10


def rs_ratio_momentum(rs: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    sma = rs.rolling(window).mean()
    std = rs.rolling(window).std()
    rs_ratio = 100 + (rs - sma) / std
    sma2 = rs_ratio.rolling(window).mean()
    std2 = rs_ratio.rolling(window).std()
    rs_momentum = 100 + (rs_ratio - sma2) / std2
    return rs_ratio, rs_momentum


def main() -> None:
    data = json.load(open(BASE / "asset_class_dataset.json", encoding="utf-8"))
    dates = data["dates"]
    bench_values = data["benchmark"]["values"]

    out_classes = []
    for f in data["funds"]:
        name = f["name"].replace(" (asset class composite)", "")
        start = next(i for i, v in enumerate(f["values"]) if v is not None)
        composite = pd.Series(f["values"][start:])
        benchmark = pd.Series(bench_values[start:])
        rs = 100 * composite / benchmark
        rs_ratio, rs_momentum = rs_ratio_momentum(rs, WINDOW)

        first_valid = int((2 * WINDOW) - 1)
        out_dates = dates[start:][first_valid:]
        rs_ratio_l = [None if pd.isna(v) else round(float(v), 3) for v in rs_ratio.iloc[first_valid:]]
        rs_momentum_l = [None if pd.isna(v) else round(float(v), 3) for v in rs_momentum.iloc[first_valid:]]

        out_classes.append({
            "asset_class": name, "dates": out_dates,
            "rs_ratio": rs_ratio_l, "rs_momentum": rs_momentum_l,
        })

    out = {"window": WINDOW, "asset_classes": out_classes}
    out_path = BASE / "asset_class_rrg_series.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    print(f"Wrote {out_path}")
    for c in out_classes:
        last_ratio = next((v for v in reversed(c["rs_ratio"]) if v is not None), None)
        last_mom = next((v for v in reversed(c["rs_momentum"]) if v is not None), None)
        print(f"  {c['asset_class']:10s} n_points={len(c['dates']):4d}  "
              f"latest RS-Ratio={last_ratio}  RS-Momentum={last_mom}")


if __name__ == "__main__":
    main()
