"""Enumerate + verify funds for Large Cap, Flexi Cap, Multi Cap, Multi Asset.

Same two-stage approach that worked for small cap: name-match against the bulk
scheme list to narrow the field (the bulk list carries no category field), then
probe each candidate's own endpoint for its real scheme_category and NAV
freshness. Name matching alone is unreliable - it pulled an ING Gilt Fund into
an "auto" search earlier - so the category field is the actual authority.

Rejects:
  - wrong/missing category (name says one thing, AMFI says another)
  - closed-end / interval schemes
  - stale NAV (no update in the last ~3 weeks => wound up, merged, or renamed
    under a new scheme code)
  - index funds, ETFs, FoFs (we want actively-managed schemes here)
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

import requests

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
UA = {"User-Agent": "Mozilla/5.0"}
FRESH_CUTOFF = dt.date(2026, 8, 25)   # ~3 weeks before the 2026-09-16 data edge

# name pattern -> the scheme_category substrings AMFI actually uses for it
CATEGORIES = {
    "Large Cap": {
        "name_pat": r"large\s*cap",
        "cat_pat": r"large\s*cap",
        "reject_name": r"large\s*(&|and)\s*mid|index|etf|fund of fund|fof",
    },
    "Flexi Cap": {
        "name_pat": r"flexi\s*cap",
        "cat_pat": r"flexi\s*cap",
        "reject_name": r"index|etf|fund of fund|fof",
    },
    "Multi Cap": {
        "name_pat": r"multi\s*cap",
        "cat_pat": r"multi\s*cap",
        "reject_name": r"index|etf|fund of fund|fof",
    },
    "Multi Asset": {
        "name_pat": r"multi\s*asset",
        "cat_pat": r"multi\s*asset",
        "reject_name": r"index|etf|fund of fund|fof",
    },
}


def main() -> None:
    schemes = json.load(open(BASE / "all_schemes.json", encoding="utf-8"))
    results = {}

    for label, spec in CATEGORIES.items():
        candidates = [
            s for s in schemes
            if re.search(spec["name_pat"], s["schemeName"], re.I)
            and re.search(r"direct", s["schemeName"], re.I)
            and re.search(r"growth", s["schemeName"], re.I)
            and not re.search(r"idcw|dividend|bonus", s["schemeName"], re.I)
            and not re.search(spec["reject_name"], s["schemeName"], re.I)
        ]
        print(f"\n{'='*78}\n{label}: {len(candidates)} name-candidates -> probing\n{'='*78}")

        kept, rejected = [], []
        seen_isin = {}

        for s in candidates:
            code = s["schemeCode"]
            try:
                r = requests.get(f"https://api.mfapi.in/mf/{code}", headers=UA, timeout=25).json()
            except Exception as e:
                rejected.append((code, s["schemeName"], f"fetch failed: {e}"))
                continue
            meta, data = r.get("meta", {}) or {}, r.get("data", []) or []
            cat = (meta.get("scheme_category") or "")
            stype = (meta.get("scheme_type") or "")
            isin = meta.get("isin_growth")

            if not data:
                rejected.append((code, s["schemeName"], "no NAV data"))
                continue
            d, mo, y = data[0]["date"].split("-")
            latest = dt.date(int(y), int(mo), int(d))

            if not re.search(spec["cat_pat"], cat, re.I):
                rejected.append((code, s["schemeName"], f"category mismatch: {cat!r}"))
                continue
            if re.search(r"close", stype, re.I):
                rejected.append((code, s["schemeName"], f"closed-end: {stype!r}"))
                continue
            if latest < FRESH_CUTOFF:
                rejected.append((code, s["schemeName"], f"stale, last NAV {latest}"))
                continue
            if isin and isin in seen_isin:
                rejected.append((code, s["schemeName"], f"duplicate ISIN of {seen_isin[isin]}"))
                continue
            if isin:
                seen_isin[isin] = code

            kept.append({
                "code": code, "name": s["schemeName"], "category": cat,
                "n": len(data), "first": data[-1]["date"], "latest": data[0]["date"],
            })
            time.sleep(0.1)

        kept.sort(key=lambda x: x["name"])
        print(f"\n  KEPT: {len(kept)}")
        for k in kept:
            print(f"    {k['code']:>7} {k['n']:>5} pts  {k['first']} -> {k['latest']}  {k['name'][:60]}")
        print(f"\n  REJECTED: {len(rejected)}")
        for code, name, why in rejected:
            print(f"    {code:>7}  {name[:52]:52s}  {why}")

        results[label] = kept

    with open(BASE / "category_universe.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    total = sum(len(v) for v in results.values())
    print(f"\n\nWrote category_universe.json - {total} funds across {len(results)} categories")


if __name__ == "__main__":
    main()
