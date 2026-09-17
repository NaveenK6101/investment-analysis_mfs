"""Compute RS-Ratio / RS-Momentum time series per sector for the Relative
Rotation Graph, from the sector composites built by build_sector_composites.py.

This is an open, transparently-documented approximation of the JdK RRG
methodology (the exact StockCharts/Bloomberg formula is proprietary), widely
used in open-source RRG implementations:

  RS            = 100 * composite / benchmark             (raw relative strength)
  RS-Ratio[t]   = 100 + (RS[t] - SMA(RS, w)[t]) / STD(RS, w)[t]      (how far
                  above/below its own w-period trend, z-score style, centered
                  on 100 so >100 = outperforming its own recent trend)
  RS-Momentum[t]= 100 + (RS-Ratio[t] - SMA(RS-Ratio, w)[t]) / STD(RS-Ratio, w)[t]
                  (rate of change of that outperformance - is the lead
                  accelerating or fading)

w = 10 weeks (~2.5 months), the common default for a weekly RRG.
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
    data = json.load(open(BASE / "sector_rrg_data.json", encoding="utf-8"))

    out_sectors = []
    for s in data["sectors"]:
        composite = pd.Series(s["composite"])
        benchmark = pd.Series(s["benchmark_nifty500"])
        rs = 100 * composite / benchmark
        rs_ratio, rs_momentum = rs_ratio_momentum(rs, WINDOW)

        # drop the first `window` points where rolling stats are NaN
        first_valid = int((2 * WINDOW) - 1)  # two chained rolling windows
        dates = s["dates"][first_valid:]
        rs_ratio_l = [None if pd.isna(v) else round(float(v), 3) for v in rs_ratio.iloc[first_valid:]]
        rs_momentum_l = [None if pd.isna(v) else round(float(v), 3) for v in rs_momentum.iloc[first_valid:]]

        out_sectors.append({
            "sector": s["sector"],
            "dates": dates,
            "rs_ratio": rs_ratio_l,
            "rs_momentum": rs_momentum_l,
            "n_funds_used": s["n_funds_used"],
            "funds_used": s["funds_used"],
            "common_start": s["common_start"],
        })

    out = {"window": WINDOW, "sectors": out_sectors}
    out_path = BASE / "rrg_series.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    print(f"Wrote {out_path}")
    for s in out_sectors:
        last_ratio = next((v for v in reversed(s["rs_ratio"]) if v is not None), None)
        last_mom = next((v for v in reversed(s["rs_momentum"]) if v is not None), None)
        print(f"  {s['sector']:32s} n_points={len(s['dates']):4d}  "
              f"latest RS-Ratio={last_ratio}  RS-Momentum={last_mom}")


if __name__ == "__main__":
    main()
