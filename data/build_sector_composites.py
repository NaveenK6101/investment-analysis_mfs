"""Build one composite 'index' per sector bucket, answering a different
question than the fund leaderboard: not "which fund in Pharma is best" but
"is Pharma as a whole beating the market."

Methodology: within each sector, take its 3 longest-tenured funds (or all of
them if fewer than 3) as a representative basket - using every fund would tie
each sector's history to its newest NFO (Manufacturing's median fund is a
2024 launch), which would leave almost no history to compute anything on.
Requiring only 3 established funds keeps each composite's start date honest
and as early as the sector allows. Composite[t] = equal-weighted mean of
each included fund's NAV rebased to 100 at the sector's common start date.
Nifty 500 is rebased the same way over the same window, so relative strength
= 100 * composite / benchmark is directly comparable across sectors even
though their start dates differ.

Output: one JSON with a 'sectors' list (composite + rebased benchmark series
per sector, common_start, n_funds_used, fund names used) for the RRG page,
AND a set of pseudo-fund entries in the same shape as the existing
leaderboard datasets so they can be merged in as a 14th "Sector Composites"
category and reuse the exact same leaderboard UI/table/chart.
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
MIN_FUNDS = 3


def main() -> None:
    sec = json.load(open(BASE / "sector_dataset.json", encoding="utf-8"))
    dates = sec["dates"]
    nifty500 = next(b for b in sec["benchmarks"] if b["key"] == "nifty500")

    by_sector: dict[str, list] = {}
    for f in sec["funds"]:
        by_sector.setdefault(f["category"], []).append(f)

    def first_valid_idx(values):
        for i, v in enumerate(values):
            if v is not None:
                return i
        return None

    sectors_out = []
    pseudo_funds = []

    for sector, funds in by_sector.items():
        tenured = sorted(funds, key=lambda f: first_valid_idx(f["values"]))
        k = min(MIN_FUNDS, len(tenured))
        included = tenured[:k]
        start_idx = max(first_valid_idx(f["values"]) for f in included)

        rebased_funds = []
        for f in included:
            base = f["values"][start_idx]
            rebased = [None if v is None else 100.0 * v / base for v in f["values"][start_idx:]]
            rebased_funds.append(rebased)

        n = len(rebased_funds[0])
        composite = []
        for i in range(n):
            vals = [r[i] for r in rebased_funds if r[i] is not None]
            composite.append(round(sum(vals) / len(vals), 4) if vals else None)

        bench_base = nifty500["values"][start_idx]
        bench_rebased = [None if v is None else round(100.0 * v / bench_base, 4)
                          for v in nifty500["values"][start_idx:]]

        comp_dates = dates[start_idx:]
        sectors_out.append({
            "sector": sector,
            "common_start": comp_dates[0],
            "dates": comp_dates,
            "composite": composite,
            "benchmark_nifty500": bench_rebased,
            "n_funds_used": k,
            "funds_used": [f["name"] for f in included],
        })

        # pad composite back to the FULL dataset date range (None before
        # common_start) so it can merge into the existing leaderboard dataset
        pad = [None] * start_idx
        full_values = pad + [round(v, 4) if v is not None else None for v in composite]
        pseudo_funds.append({
            "key": f"sector_composite_{sector.lower().replace(' ', '_').replace('&', 'and').replace('/', '')}",
            "name": f"{sector} (sector composite, {k} funds)",
            "category": "Sector Composites",
            "values": full_values,
        })

    out = {"dates": dates, "sectors": sectors_out}
    with open(BASE / "sector_rrg_data.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"Wrote sector_rrg_data.json - {len(sectors_out)} sector composites")
    for s in sectors_out:
        print(f"  {s['sector']:32s} start={s['common_start']}  n_funds={s['n_funds_used']}  "
              f"weeks={len(s['dates'])}")

    with open(BASE / "sector_composite_pseudo_funds.json", "w", encoding="utf-8") as fh:
        json.dump({"dates": dates, "funds": pseudo_funds}, fh, separators=(",", ":"))
    print(f"\nWrote sector_composite_pseudo_funds.json - {len(pseudo_funds)} pseudo-funds "
          f"(for merging into the leaderboard dataset)")


if __name__ == "__main__":
    main()
