"""Export a flat CSV snapshot of sector relative strength - the kind of table
you'd paste into Google Sheets and track over time yourself (File > Import >
Upload, or File > Import > paste; a fresh export replaces the numbers, your
sheet keeps history if you paste each export into a new dated row/tab).

One row per sector composite, with returns/excess/RS-change at each of the
windows the leaderboard page supports, plus the current RRG reading
(RS-Ratio, RS-Momentum, quadrant) computed by build_rrg_series.py.
"""

from __future__ import annotations

import csv
import json
import datetime as dt
from pathlib import Path

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
WINDOWS_MONTHS = [1, 3, 6, 12]


def quadrant_of(ratio: float, momentum: float) -> str:
    if ratio >= 100 and momentum >= 100:
        return "Leading"
    if ratio >= 100 and momentum < 100:
        return "Weakening"
    if ratio < 100 and momentum < 100:
        return "Lagging"
    return "Improving"


def window_return(dates: list[str], values: list, months: int) -> float | None:
    end_date = dt.date.fromisoformat(dates[-1])
    y, m = end_date.year, end_date.month - months
    while m <= 0:
        m += 12
        y -= 1
    target = end_date.replace(year=y, month=m)
    target_str = target.isoformat()
    start_idx = next((i for i, d in enumerate(dates) if d >= target_str), None)
    if start_idx is None:
        return None
    end_idx = len(dates) - 1
    while end_idx > start_idx and values[end_idx] is None:
        end_idx -= 1
    if values[start_idx] is None or values[end_idx] is None:
        return None
    return round(100.0 * (values[end_idx] / values[start_idx] - 1), 2)


def main() -> None:
    rrg = json.load(open(BASE / "rrg_series.json", encoding="utf-8"))
    comp_raw = json.load(open(BASE / "sector_rrg_data.json", encoding="utf-8"))

    rows = []
    for s in comp_raw["sectors"]:
        sector = s["sector"]
        rrg_s = next(r for r in rrg["sectors"] if r["sector"] == sector)
        last_ratio = next(v for v in reversed(rrg_s["rs_ratio"]) if v is not None)
        last_mom = next(v for v in reversed(rrg_s["rs_momentum"]) if v is not None)
        quad = quadrant_of(last_ratio, last_mom)

        row = {
            "sector": sector,
            "as_of": s["dates"][-1],
            "composite_funds_used": s["n_funds_used"],
            "composite_start": s["common_start"],
            "rs_ratio": last_ratio,
            "rs_momentum": last_mom,
            "quadrant": quad,
        }
        for months in WINDOWS_MONTHS:
            row[f"sector_return_{months}m_pct"] = window_return(s["dates"], s["composite"], months)
            row[f"nifty500_return_{months}m_pct"] = window_return(s["dates"], s["benchmark_nifty500"], months)
            sr, br = row[f"sector_return_{months}m_pct"], row[f"nifty500_return_{months}m_pct"]
            row[f"excess_{months}m_pp"] = round(sr - br, 2) if sr is not None and br is not None else None
        rows.append(row)

    rows.sort(key=lambda r: r["excess_6m_pp"] if r["excess_6m_pp"] is not None else -999, reverse=True)

    fieldnames = list(rows[0].keys())
    out_path = BASE / "sector_relative_strength_snapshot.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {out_path} ({len(rows)} rows)")
    for r in rows:
        print(f"  {r['sector']:32s} 6m excess={r['excess_6m_pp']}pp  quadrant={r['quadrant']}")


if __name__ == "__main__":
    main()
