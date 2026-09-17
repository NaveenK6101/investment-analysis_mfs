"""Enumerate + verify sectoral/thematic funds, then classify into actual
sector buckets by name (AMFI doesn't sub-categorize "Sectoral/Thematic" by
which sector - Banking and ESG sit in the same bucket).

Same verification rigor as the cap categories: probe each candidate's own
endpoint for real scheme_category (must contain Sectoral/Thematic), reject
closed-end/stale/duplicate. Then keyword-classify into sector buckets and
report counts, so we can decide which buckets are thick enough to be worth
a leaderboard before fetching anything.
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
FRESH_CUTOFF = dt.date(2026, 8, 25)

# ordered: first matching bucket wins, so put more specific patterns first.
# NOTE: "bank" alone was dropped from the banking pattern - it false-matched
# AMC house-name prefixes like "Bank of India Manufacturing & Infrastructure
# Fund" (the AMC is Bank of India MF; the fund itself is a manufacturing/
# infra theme). Genuine banking-sector funds are always named "...Banking
# [and/&] Financial Services Fund", never bare "Bank X Fund", so requiring
# "banking" (not "bank") is a safe, general fix - not a special case.
SECTOR_BUCKETS = [
    ("Banking & Financial Services", r"banking|financial services|bfsi"),
    ("Pharma & Healthcare",          r"pharma|healthcare|health\s*care"),
    ("Technology / IT",              r"\btech|digital india|information technology|\bit\b"),
    ("Consumption / FMCG",           r"consumption|consumer|fmcg"),
    ("Infrastructure",               r"infra"),
    ("PSU",                          r"\bpsu\b|public sector"),
    ("Energy & Power",               r"energy|power\b|natural resources"),
    ("Manufacturing",                r"manufactur|make in india"),
    ("Auto",                         r"\bauto"),
    ("Realty / Real Estate",         r"realty|real estate"),
    ("Commodities / Metals",         r"commodit|metal|mining"),
    ("MNC",                          r"\bmnc\b"),
    ("PSE / Disinvestment",          r"\bcpse\b|disinvest"),
]
OTHER_THEMATIC_HINT = r"esg|value\b|dividend yield|business cycle|focused|contra|special situations|international|overseas|global|emerging|rural|digital\b|innovation|quant\b"

# Scope decision (confirmed with user): only these 8 buckets are thick/clean
# enough for a leaderboard. Auto (1 fund) and Commodities/Metals (2 funds)
# are too thin; MNC is an ownership-structure filter that cuts across every
# sector, not a rotation "sector" in the same sense as the others.
KEPT_BUCKETS = [
    "Banking & Financial Services", "Pharma & Healthcare", "Technology / IT",
    "Consumption / FMCG", "Infrastructure", "PSU", "Energy & Power", "Manufacturing",
]


def classify(name: str) -> str:
    for label, pat in SECTOR_BUCKETS:
        if re.search(pat, name, re.I):
            return label
    if re.search(OTHER_THEMATIC_HINT, name, re.I):
        return "Other thematic (not a sector)"
    return "Unclassified"


def main() -> None:
    schemes = json.load(open(BASE / "all_schemes.json", encoding="utf-8"))

    candidates = [
        s for s in schemes
        if re.search(r"direct", s["schemeName"], re.I)
        and re.search(r"growth", s["schemeName"], re.I)
        and not re.search(r"idcw|dividend|bonus", s["schemeName"], re.I)
    ]
    print(f"{len(candidates)} direct+growth candidates total, probing scheme_category "
          f"for 'Sectoral' or 'Thematic'...")

    kept, rejected = [], []
    seen_isin = {}
    seen_name = {}
    checked = 0

    for s in candidates:
        # quick pre-filter on name to avoid probing all ~15000 direct+growth schemes -
        # sectoral/thematic fund names virtually always contain a sector/theme word or
        # "fund" combined with one of these; cheap enough to just probe anything that
        # could plausibly be one based on common AMC naming, but 15000 probes is too
        # many, so restrict to names NOT already claimed by the cap-category patterns
        # we already handled, then probe category for the rest in two passes below.
        pass

    # cheaper approach: only probe schemes whose name matches at least one sector/
    # thematic keyword OR the generic word "fund" isn't useful alone, so build a
    # broad name filter first, then verify category server-side.
    name_pat = "|".join(pat for _, pat in SECTOR_BUCKETS) + "|" + OTHER_THEMATIC_HINT + r"|opportunit|thematic|sector"
    prefiltered = [s for s in candidates if re.search(name_pat, s["schemeName"], re.I)]
    print(f"{len(prefiltered)} name-prefiltered, probing each...")

    for i, s in enumerate(prefiltered):
        code = s["schemeCode"]
        try:
            r = requests.get(f"https://api.mfapi.in/mf/{code}", headers=UA, timeout=25).json()
        except Exception as e:
            rejected.append((code, s["schemeName"], f"fetch failed: {e}"))
            continue
        meta, data = r.get("meta", {}) or {}, r.get("data", []) or []
        cat = meta.get("scheme_category") or ""
        stype = meta.get("scheme_type") or ""
        isin = meta.get("isin_growth")

        if not data:
            rejected.append((code, s["schemeName"], "no NAV data"))
            continue
        d, mo, y = data[0]["date"].split("-")
        latest = dt.date(int(y), int(mo), int(d))

        if not re.search(r"sectoral|thematic", cat, re.I):
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
        # same displayed name, different ISIN => segregated-portfolio split
        # of the same fund (e.g. Motilal Oswal Digital India 152964/152965),
        # not a genuinely distinct scheme - redundant for a leaderboard.
        norm_name = re.sub(r"\s+", " ", s["schemeName"].strip().lower())
        if norm_name in seen_name:
            rejected.append((code, s["schemeName"], f"duplicate name of {seen_name[norm_name]}"))
            continue
        seen_name[norm_name] = code
        if isin:
            seen_isin[isin] = code

        kept.append({
            "code": code, "name": s["schemeName"], "category": cat,
            "sector": classify(s["schemeName"]),
            "n": len(data), "first": data[-1]["date"], "latest": data[0]["date"],
        })
        if (i + 1) % 30 == 0:
            print(f"  ...{i+1}/{len(prefiltered)}")
        time.sleep(0.08)

    print(f"\nKEPT: {len(kept)}   REJECTED: {len(rejected)}")

    by_sector_all: dict[str, list] = {}
    for k in kept:
        by_sector_all.setdefault(k["sector"], []).append(k)

    order = [b[0] for b in SECTOR_BUCKETS] + ["Other thematic (not a sector)", "Unclassified"]
    print(f"\n{'='*78}\nBY SECTOR BUCKET (all, before scope filter)\n{'='*78}")
    for sector in order:
        funds = by_sector_all.get(sector, [])
        if not funds:
            continue
        print(f"\n--- {sector}: {len(funds)} funds ---")
        for f in sorted(funds, key=lambda x: x["name"]):
            print(f"    {f['code']:>7} {f['n']:>5} pts  {f['first']} -> {f['latest']}  {f['name'][:62]}")

    # scope filter: only the 8 confirmed sector buckets go into the dataset
    by_sector = {k: v for k, v in by_sector_all.items() if k in KEPT_BUCKETS}

    with open(BASE / "sector_universe.json", "w", encoding="utf-8") as fh:
        json.dump(by_sector, fh, indent=1)

    print(f"\n\nWrote sector_universe.json ({sum(len(v) for v in by_sector.values())} funds, "
          f"{len(by_sector)} buckets)")
    print("\nSummary counts (in scope):")
    for sector in KEPT_BUCKETS:
        n = len(by_sector.get(sector, []))
        print(f"  {sector:32s} {n}")
    print("\nDropped from scope:")
    for sector in order:
        if sector in KEPT_BUCKETS:
            continue
        n = len(by_sector_all.get(sector, []))
        if n:
            print(f"  {sector:32s} {n}")


if __name__ == "__main__":
    main()
