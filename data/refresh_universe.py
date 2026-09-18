"""Re-verify the fund universe: catches new NFOs, funds that got merged/
wound up since last time, and re-applies the (now-fixed) classification and
dedup rules from enumerate_categories.py / enumerate_sectors.py.

Safe to run unattended now that those two scripts' actual bugs - the
Bank of India AMC-name false positive, the Motilal Oswal segregated-
portfolio duplicate - are fixed in the classify()/dedup code itself, not
just patched by hand in the output. Re-running the same verified logic
won't reintroduce them. What it can't catch is a genuinely new kind of
edge case never seen before - same residual risk any automated pipeline
carries - so this script always prints a plain diff of what changed
(added/dropped funds) instead of changing things silently, so a quick
skim always catches anything that looks wrong.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import requests

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
UA = {"User-Agent": "Mozilla/5.0"}


def refetch_all_schemes() -> None:
    print("Refetching all_schemes.json from mfapi.in...")
    r = requests.get("https://api.mfapi.in/mf", headers=UA, timeout=60)
    r.raise_for_status()
    schemes = r.json()
    with open(BASE / "all_schemes.json", "w", encoding="utf-8") as fh:
        json.dump(schemes, fh)
    print(f"  {len(schemes)} schemes total")


def snapshot(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.load(open(path, encoding="utf-8"))


def diff_universe(label: str, old: dict | None, new: dict) -> None:
    print(f"\n{'=' * 70}\n{label} - what changed\n{'=' * 70}")
    if old is None:
        print("  (no previous snapshot - first run)")
        return

    def flatten(u: dict) -> dict[int, str]:
        out = {}
        for bucket, funds in u.items():
            for f in funds:
                out[f["code"]] = f"{f['name']}  [{bucket}]"
        return out

    old_flat, new_flat = flatten(old), flatten(new)
    added = set(new_flat) - set(old_flat)
    removed = set(old_flat) - set(new_flat)

    if not added and not removed:
        print("  no change")
        return
    for code in sorted(added):
        print(f"  + ADDED   {code:>7}  {new_flat[code]}")
    for code in sorted(removed):
        print(f"  - REMOVED {code:>7}  {old_flat[code]}  (delisted, merged, or now fails a check)")


def main() -> None:
    refetch_all_schemes()

    old_categories = snapshot(BASE / "category_universe.json")
    old_sectors = snapshot(BASE / "sector_universe.json")

    print("\nRe-running category enumeration (Large/Flexi/Multi Cap, Multi Asset)...")
    import enumerate_categories
    enumerate_categories.main()

    print("\nRe-running sector enumeration...")
    import enumerate_sectors
    enumerate_sectors.main()

    new_categories = json.load(open(BASE / "category_universe.json", encoding="utf-8"))
    new_sectors = json.load(open(BASE / "sector_universe.json", encoding="utf-8"))

    diff_universe("Cap categories", old_categories, new_categories)
    diff_universe("Sectors", old_sectors, new_sectors)


if __name__ == "__main__":
    main()
