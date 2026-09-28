"""Build the Asset Classes rows - measured against Nifty 50, i.e. "is this
beating Indian large-cap equity?" Equity itself (Nifty 50) is the reference,
not a competitor, so it isn't a row here: a row would just be Nifty 50 against
Nifty 50 (flat, and a divide-by-zero in the RRG's z-score). If everything
below reads negative, plain Nifty 50 equity is winning.

Two different kinds of rows, both answering "where would money be better off
right now":
  - Equity market-cap segments (Nifty 100, Nifty Midcap 150, Nifty Smallcap
    250, Nifty 500, Sensex) - these are ALL equity, so this is really "large
    vs mid vs small cap rotation", not a different asset class. Included
    because the user wants to see where money is flowing WITHIN equity too,
    not just equity-vs-everything-else. Straight from the indices already
    fetched as benchmarks in build_leaderboard_v2.py - no separate fetch here.
  - Genuine alternative asset classes: Gold, Silver (already-built INR metal
    series, rebased to 100), Debt (the liquid-fund composite from
    build_debt_dataset.py), Crypto (equal-weight of all 4 coins - only 4
    exist, so no "pick the 3 longest-tenured" here; Solana, from 2020-04, is
    the newest and sets the composite's own start).

Each row keeps its own start date (Gold/Silver/Sensex go back to 2011, Nifty
Midcap 150 to 2019, Crypto to 2020) - relative strength is a ratio, so
there's no need to force a common start the way a blended benchmark would
have required.
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

    bench_by_key = {b["key"]: b for b in cap["benchmarks"]}
    nifty50 = reindex(bench_by_key["nifty50"]["values"], cap["dates"])
    # equity market-cap-segment rows: straight indices, already fetched as benchmarks - no new fetch.
    equity_segments = {
        "Nifty 100": "nifty100", "Nifty Midcap 150": "niftymidcap150",
        "Nifty Smallcap 250": "smallcap250", "Nifty 500": "nifty500", "Sensex": "sensex",
    }
    equity_segment_vals = {name: reindex(bench_by_key[key]["values"], cap["dates"])
                            for name, key in equity_segments.items()}
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
    # (display name, values, is this a synthetic composite we built vs a real single index?)
    rows = [(name, vals, True) for name, vals in
            {"Debt": debt_vals, "Gold": gold, "Silver": silver, "Crypto": crypto_composite}.items()]
    rows += [(name, vals, False) for name, vals in equity_segment_vals.items()]

    funds = []
    for name, values, is_composite in rows:
        start = first_valid_idx(values)
        base = values[start]
        rebased = [None if v is None else round(100.0 * v / base, 4) for v in values[start:]]
        label = f"{name} (asset class composite)" if is_composite else name
        funds.append({"key": "assetclass_" + name.lower().replace(" ", "_"), "name": label,
                      "category": "Asset Classes", "values": [None] * start + rebased})
        print(f"  {name:18s} from {dates[start]}  latest index level (started at 100): "
              f"{next(v for v in reversed(rebased) if v is not None):.1f}")

    out = {"dates": dates,
           "funds": funds,
           "benchmark": {"key": "nifty50", "name": "Nifty 50", "values": nifty50}}
    with open(BASE / "asset_class_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote asset_class_dataset.json ({len(funds)} rows vs Nifty 50)")


if __name__ == "__main__":
    main()
