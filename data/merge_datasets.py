"""Merge the cap-category dataset, sector dataset, sector composites, and
crypto dataset into one combined dataset for the leaderboard page. Union
the dates (reindexing every fund set onto the combined weekly axis) and
union the benchmark lists (nifty50/nifty500 are shared keys, kept once).
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")


def main() -> None:
    cap = json.load(open(BASE / "leaderboard_full_dataset.json", encoding="utf-8"))
    sec = json.load(open(BASE / "sector_dataset.json", encoding="utf-8"))
    comp = json.load(open(BASE / "sector_composite_pseudo_funds.json", encoding="utf-8"))
    crypto = json.load(open(BASE / "crypto_dataset.json", encoding="utf-8"))
    metals = json.load(open(BASE / "metals_dataset.json", encoding="utf-8"))
    sif = json.load(open(BASE / "sif_dataset.json", encoding="utf-8"))
    assetcls = json.load(open(BASE / "asset_class_dataset.json", encoding="utf-8"))

    all_dates = sorted(set(cap["dates"]) | set(sec["dates"]) | set(comp["dates"]) | set(crypto["dates"])
                        | set(metals["dates"]) | set(sif["dates"]) | set(assetcls["dates"]))
    cap_idx = {d: i for i, d in enumerate(cap["dates"])}
    sec_idx = {d: i for i, d in enumerate(sec["dates"])}
    comp_idx = {d: i for i, d in enumerate(comp["dates"])}
    crypto_idx = {d: i for i, d in enumerate(crypto["dates"])}
    metals_idx = {d: i for i, d in enumerate(metals["dates"])}
    sif_idx = {d: i for i, d in enumerate(sif["dates"])}
    assetcls_idx = {d: i for i, d in enumerate(assetcls["dates"])}

    def reindex(values, idx_map):
        return [values[idx_map[d]] if d in idx_map else None for d in all_dates]

    funds = []
    for f in cap["funds"]:
        funds.append({**f, "values": reindex(f["values"], cap_idx)})
    for f in sec["funds"]:
        funds.append({**f, "values": reindex(f["values"], sec_idx)})
    for f in comp["funds"]:
        funds.append({**f, "values": reindex(f["values"], comp_idx)})
    for f in crypto["funds"]:
        funds.append({**f, "values": reindex(f["values"], crypto_idx)})
    for f in metals["funds"]:
        funds.append({**f, "values": reindex(f["values"], metals_idx)})
    for f in sif["funds"]:
        funds.append({"key": f["key"], "name": f["name"], "category": f["category"],
                       "values": reindex(f["values"], sif_idx)})
    for f in assetcls["funds"]:
        funds.append({**f, "values": reindex(f["values"], assetcls_idx)})

    bench_by_key = {}
    for b in cap["benchmarks"]:
        bench_by_key[b["key"]] = {**b, "values": reindex(b["values"], cap_idx)}
    for b in sec["benchmarks"]:
        if b["key"] in bench_by_key:
            continue  # nifty50 / nifty500 already carried from cap dataset
        bench_by_key[b["key"]] = {**b, "values": reindex(b["values"], sec_idx)}
    ab = assetcls["benchmark"]
    if ab["key"] not in bench_by_key:  # nifty50 already carried from the cap dataset
        bench_by_key[ab["key"]] = {**ab, "values": reindex(ab["values"], assetcls_idx)}

    category_default_benchmark = {
        **cap["category_default_benchmark"],
        **sec["category_default_benchmark"],
        "Sector Composites": "nifty500",
        "Crypto": "nifty500",
        "Metals": "nifty500",
        "SIF": "nifty500",
        "Asset Classes": "nifty50",
    }

    # Crypto/FX trade on weekends, so a Saturday run adds a next-week (Friday-labelled)
    # point that has data for those series only. Drop trailing weeks where fewer than half
    # the series have a value, otherwise every window would be anchored to an empty week.
    all_series = [f["values"] for f in funds] + [b["values"] for b in bench_by_key.values()]
    n = len(all_dates)
    while n > 1 and sum(1 for s in all_series if s[n - 1] is not None) / len(all_series) < 0.5:
        n -= 1
    if n < len(all_dates):
        print(f"Trimming {len(all_dates) - n} mostly-empty trailing week(s): {all_dates[n:]}")
        all_dates = all_dates[:n]
        for f in funds:
            f["values"] = f["values"][:n]
        for b in bench_by_key.values():
            b["values"] = b["values"][:n]

    as_of = all_dates[-1]

    out = {
        "as_of": as_of,
        "dates": all_dates,
        "category_default_benchmark": category_default_benchmark,
        "funds": funds,
        "benchmarks": list(bench_by_key.values()),
    }

    out_path = BASE / "leaderboard_combined_dataset.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    counts = {}
    for f in out["funds"]:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    print(f"Wrote {out_path} ({size_kb:.0f} KB, {len(all_dates)} weeks, {len(funds)} funds, "
          f"{len(out['benchmarks'])} benchmarks)")
    for cat, n in counts.items():
        print(f"  {cat:32s} {n}")


if __name__ == "__main__":
    main()
