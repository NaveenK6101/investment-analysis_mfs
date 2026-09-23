"""Build asset-class-level composites: Equity, Gold, Silver, Crypto - one
level up from everything else in this project, which compares WITHIN an
asset class (which small-cap fund, which sector, which metal). This answers
a different question: which asset class itself is winning right now, so you
know where to go look before picking an instrument inside it.

Same construction as build_sector_composites.py, just with different
members:
  - Equity  -> Nifty 500 itself (the broad market, not a fund composite -
               avoids re-adding survivorship bias on top of what the equity
               fund universe already carries).
  - Gold, Silver -> already-built INR metal series, unchanged.
  - Crypto  -> equal-weight of all 4 coins (unlike sectors, there's no
               "pick the 3 longest-tenured" here - only 4 coins exist
               total, so use all of them). Solana (from 2020-04) is the
               newest, and sets the common start for the whole composite.

The "benchmark" for this rotation view can't be an external index the way
Nifty 500 was for sectors - there's no such thing as "the market" one level
above equity itself. So the reference is a blended ALL-ASSETS composite:
equal-weight of Equity/Gold/Silver/Crypto, rebased from the same common
start (bounded by Crypto's 2020-04 start, the youngest member) - the same
"compare to reference" mechanics as everywhere else, just with a
purpose-built blended reference instead of a pre-existing index.
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


def rebase(values, dates, start_idx):
    base = values[start_idx]
    out_dates = dates[start_idx:]
    out_values = [None if v is None else round(100.0 * v / base, 4) for v in values[start_idx:]]
    return out_dates, out_values


def main() -> None:
    # read the same RAW, pre-merge sources merge_datasets.py itself reads - not the
    # already-merged leaderboard_combined_dataset.json, which this script's own output
    # then feeds back into (same ordering as build_sector_composites.py, which runs
    # before the merge step and produces a pseudo-funds file for it to pick up).
    cap = json.load(open(BASE / "leaderboard_full_dataset.json", encoding="utf-8"))
    crypto = json.load(open(BASE / "crypto_dataset.json", encoding="utf-8"))
    metals = json.load(open(BASE / "metals_dataset.json", encoding="utf-8"))

    dates = sorted(set(cap["dates"]) | set(crypto["dates"]) | set(metals["dates"]))

    def reindex(values, src_dates):
        idx_map = {d: i for i, d in enumerate(src_dates)}
        return [values[idx_map[d]] if d in idx_map else None for d in dates]

    nifty500 = reindex(next(b for b in cap["benchmarks"] if b["key"] == "nifty500")["values"], cap["dates"])
    coins = {f["key"]: reindex(f["values"], crypto["dates"]) for f in crypto["funds"]}

    metal_by_name = {f["name"]: f["values"] for f in metals["funds"]}
    gold_r = reindex(metal_by_name["Gold (INR, per troy oz)"], metals["dates"])
    silver_r = reindex(metal_by_name["Silver (INR, per troy oz)"], metals["dates"])

    coin_keys = ["crypto_btc", "crypto_eth", "crypto_sol", "crypto_xrp"]
    crypto_common_start = max(first_valid_idx(coins[k]) for k in coin_keys)
    print(f"Crypto composite common start: {dates[crypto_common_start]} "
          f"(set by whichever coin has the shortest history)")

    crypto_composite = []
    for i in range(len(dates)):
        if i < crypto_common_start:
            crypto_composite.append(None)
            continue
        vals = []
        for k in coin_keys:
            base = coins[k][crypto_common_start]
            v = coins[k][i]
            if v is not None and base is not None:
                vals.append(100.0 * v / base)
        crypto_composite.append(round(sum(vals) / len(vals), 4) if len(vals) == len(coin_keys) else None)

    members = {"Equity": nifty500, "Gold": gold_r, "Silver": silver_r, "Crypto": crypto_composite}

    common_start = max(first_valid_idx(v) for v in members.values())
    print(f"All-Assets blended benchmark common start: {dates[common_start]} "
          f"(set by Crypto, the youngest asset class)")

    rebased = {}
    for name, values in members.items():
        d, v = rebase(values, dates, common_start)
        rebased[name] = v
    out_dates = dates[common_start:]

    blended = []
    for i in range(len(out_dates)):
        vals = [rebased[name][i] for name in members if rebased[name][i] is not None]
        blended.append(round(sum(vals) / len(vals), 4) if len(vals) == len(members) else None)

    funds = [{"key": "assetclass_" + name.lower(), "name": f"{name} (asset class composite)",
              "category": "Asset Classes", "values": [None] * common_start + rebased[name]}
             for name in members]

    out = {
        "dates": dates, "common_start": out_dates[0],
        "funds": funds,
        "benchmark": {"key": "allassets", "name": "All Assets (blended)",
                      "values": [None] * common_start + blended},
    }
    with open(BASE / "asset_class_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    print(f"\nWrote asset_class_dataset.json ({len(funds)} asset classes, "
          f"{len(out_dates)} weeks from {out_dates[0]})")
    for name in members:
        last = next(v for v in reversed(rebased[name]) if v is not None)
        print(f"  {name:10s} latest index level (started at 100): {last:.1f}")


if __name__ == "__main__":
    main()
