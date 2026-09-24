"""Build asset-class composites: Gold, Silver, Crypto and Debt (liquid funds) - measured against
Nifty 50, i.e. "is this asset class beating Indian equity?" Equity itself is
the reference, not a competitor, so it isn't a row here: a row would just be
Nifty 50 against Nifty 50 (flat, and a divide-by-zero in the RRG's z-score).
If all three read below Nifty 50, equity is the winning asset class.

Same construction as build_sector_composites.py:
  - Gold, Silver -> the already-built INR metal series, rebased to 100.
  - Debt         -> the liquid-fund composite from build_debt_dataset.py.
  - Crypto       -> equal-weight of all 4 coins (only 4 exist, so no "pick the
                    3 longest-tenured" here). Solana (from 2020-04) is the
                    newest and sets the composite's own start.
Each asset class keeps its own start date (Gold/Silver go back to 2011, Crypto
to 2020) - relative strength is a ratio, so there's no need to force a common
start the way a blended benchmark would have required.
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")


def first_valid_idx(values):
    for i, v in enumerate(values):
        if v is not None:
            return i
    return None


def main() -> None:
    # read the same RAW, pre-merge sources merge_datasets.py itself reads - not the
    # already-merged file, which this script's own output feeds back into.
    cap = json.load(open(BASE / "leaderboard_full_dataset.json", encoding="utf-8"))
    crypto = json.load(open(BASE / "crypto_dataset.json", encoding="utf-8"))
    metals = json.load(open(BASE / "metals_dataset.json", encoding="utf-8"))
    debt = json.load(open(BASE / "debt_dataset.json", encoding="utf-8"))

    dates = sorted(set(cap["dates"]) | set(crypto["dates"]) | set(metals["dates"]) | set(debt["dates"]))

    def reindex(values, src_dates):
        idx_map = {d: i for i, d in enumerate(src_dates)}
        return [values[idx_map[d]] if d in idx_map else None for d in dates]

    nifty50 = reindex(next(b for b in cap["benchmarks"] if b["key"] == "nifty50")["values"], cap["dates"])
    coins = {f["key"]: reindex(f["values"], crypto["dates"]) for f in crypto["funds"]}
    metal_by_name = {f["name"]: f["values"] for f in metals["funds"]}
    gold = reindex(metal_by_name["Gold (INR, per troy oz)"], metals["dates"])
    silver = reindex(metal_by_name["Silver (INR, per troy oz)"], metals["dates"])

    coin_keys = ["crypto_btc", "crypto_eth", "crypto_sol", "crypto_xrp"]
    crypto_start = max(first_valid_idx(coins[k]) for k in coin_keys)
    print(f"Crypto composite start: {dates[crypto_start]} (set by whichever coin has the shortest history)")
    crypto_composite = []
    for i in range(len(dates)):
        vals = []
        if i >= crypto_start:
            for k in coin_keys:
                v, base = coins[k][i], coins[k][crypto_start]
                if v is not None and base is not None:
                    vals.append(100.0 * v / base)
        crypto_composite.append(round(sum(vals) / len(vals), 4) if len(vals) == len(coin_keys) else None)

    debt_vals = reindex(debt["benchmark"]["values"], debt["dates"])
    members = {"Debt": debt_vals, "Gold": gold, "Silver": silver, "Crypto": crypto_composite}
    funds = []
    for name, values in members.items():
        start = first_valid_idx(values)
        base = values[start]
        rebased = [None if v is None else round(100.0 * v / base, 4) for v in values[start:]]
        funds.append({"key": "assetclass_" + name.lower(), "name": f"{name} (asset class composite)",
                      "category": "Asset Classes", "values": [None] * start + rebased})
        print(f"  {name:8s} from {dates[start]}  latest index level (started at 100): "
              f"{next(v for v in reversed(rebased) if v is not None):.1f}")

    out = {"dates": dates,
           "funds": funds,
           "benchmark": {"key": "nifty50", "name": "Nifty 50", "values": nifty50}}
    with open(BASE / "asset_class_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote asset_class_dataset.json ({len(funds)} asset classes vs Nifty 50)")


if __name__ == "__main__":
    main()
