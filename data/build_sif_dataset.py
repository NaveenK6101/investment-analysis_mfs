"""Build the SIF (Specialized Investment Fund) dataset.

SIF is a genuinely new SEBI category (launched 1 April 2025) that sits
between mutual funds and PMS - a pooled, NAV-per-unit vehicle like an MF,
minimum ticket ₹10 lakh. It runs on AMFI's infrastructure but as a SEPARATE
data stream from the regular mutual fund NAVAll.txt that mfapi.in scrapes
and everything else in this project is built on - confirmed by checking our
cached scheme list for real SIF entries (there were none, only name
coincidences) and by finding AMFI's actual SIF NAV endpoint directly:
https://portal.amfiindia.com/spages/SIF_NAVAll.txt (same semicolon-delimited
bulk format as the classic MF file, grouped under category/AMC header
lines and blank-line separators).

Two structural differences from every other dataset in this project:

1. NO HISTORICAL BACKFILL. AMFI's site also exposes what looks like a NAV
   history endpoint (SIF_DownloadNAVHistoryReport.aspx), but it errors out
   with "Application Error" even when hit with the exact URL AMFI's own
   frontend generates - a bug on their end, not a parameter problem on
   ours (verified by navigating there directly in a real browser). So this
   script can only capture TODAY's snapshot each time it runs, and builds
   history the same way the rest of this project would if mfapi.in had
   never existed: one point per run, accumulated in an APPEND-only cache
   (nav_all/sif_{key}.csv), not a fresh full-history fetch like every other
   build_*.py script here. Expect most rolling-window metrics (the 3M/6M
   crossover needs ~39 weeks) to show "-" for a long time - that's honest,
   not a bug.

2. SOME SIF STRATEGIES ARE INTERVAL FUNDS, not open-ended - you can only
   buy/sell during specific windows, unlike a normal MF. Flagged per-fund
   in the name rather than silently treated as freely tradable.

Filtered to Direct Plan + Growth option only, matching every other dataset
here. A few schemes (iSIF's) have no Plan/Option label in the source data
at all - skipped rather than guessed at.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

import requests

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SOURCE_URL = "https://portal.amfiindia.com/spages/SIF_NAVAll.txt"


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return "sif_" + s[:40]


SNAPSHOT_DIR = BASE / "sif_snapshots"  # daily copies pulled from the server (server/sif_snapshot.sh)


def fetch_and_parse() -> list[dict]:
    r = requests.get(SOURCE_URL, headers=UA, timeout=30)
    r.raise_for_status()
    return parse_text(r.text)


def parse_text(text: str, quiet: bool = False) -> list[dict]:
    text = text.lstrip("\ufeff")
    say = (lambda *a, **k: None) if quiet else print

    category = None
    rows = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Scheme Code"):
            continue
        if line.startswith(("Open Ended Schemes(", "Interval Fund Schemes(", "Close Ended Schemes(")):
            category = line
            continue
        if ";" not in line:
            continue  # AMC sub-header line, not needed - scheme name already carries the brand
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 8:
            continue
        code, isin1, isin2, name, plan, option, nav, date_str = parts[:8]
        if not plan or not option:
            continue  # a few iSIF rows have no Plan/Option label - can't tell Direct from Regular, skip
        if "direct" not in plan.lower():
            continue
        if "growth" not in option.lower():
            continue
        if re.search(r"[A-Z]{2}00[A-Z]{2}", isin1):
            say(f"  SKIP {name!r}: placeholder-looking ISIN {isin1!r} - likely test/dummy data in AMFI's feed")
            continue
        try:
            nav_val = float(nav)
            date = dt.datetime.strptime(date_str, "%d-%b-%Y").date()
        except ValueError:
            continue
        if nav_val > 100:
            say(f"  NOTE {name!r}: NAV={nav_val:.2f} is far outside the usual ~10-13 SIF range - "
                  f"kept, but this AMC evidently didn't use the standard Rs 10 face value, worth a manual glance")
        is_interval = category is not None and category.startswith("Interval Fund")
        strategy = re.sub(r"^(Open Ended|Interval Fund|Close Ended) Schemes\(.*?-\s*", "", category or "") \
            .rstrip(")") if category else "SIF"
        rows.append({
            "code": code, "isin": isin1, "name": name, "nav": nav_val, "date": date,
            "strategy": strategy, "interval_fund": is_interval,
        })
    return rows


def append_to_cache(key: str, date: dt.date, nav: float) -> None:
    cache = NAV_DIR / f"{key}.csv"
    existing = {}
    if cache.exists():
        with open(cache, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                existing[row["date"]] = float(row["nav"])
    existing[date.isoformat()] = nav
    with open(cache, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "nav"])
        for d in sorted(existing):
            writer.writerow([d, existing[d]])
    return len(existing)


def ingest_snapshots() -> list[dict]:
    """Fold every saved daily snapshot into the per-fund caches, keyed by the NAV date
    printed in the file (not the file's own date), so duplicates and gaps are harmless.
    Returns the newest snapshot's rows, as a fallback if the live fetch fails."""
    files = sorted(SNAPSHOT_DIR.glob("SIF_NAVAll_*.txt")) if SNAPSHOT_DIR.exists() else []
    if not files:
        return []
    points: dict[str, dict[str, float]] = {}
    latest_rows: list[dict] = []
    for f in files:
        rows = parse_text(f.read_text(encoding="utf-8", errors="replace"), quiet=True)
        latest_rows = rows
        for row in rows:
            points.setdefault(slugify(row["name"]), {})[row["date"].isoformat()] = row["nav"]
    for key, pts in points.items():
        cache = NAV_DIR / f"{key}.csv"
        existing = {}
        if cache.exists():
            with open(cache, newline="", encoding="utf-8") as fh:
                existing = {r["date"]: float(r["nav"]) for r in csv.DictReader(fh)}
        existing.update(pts)
        with open(cache, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "nav"])
            for d in sorted(existing):
                w.writerow([d, existing[d]])
    print(f"  ingested {len(files)} server snapshot file(s) -> {len(points)} funds' caches")
    return latest_rows


def main() -> None:
    snapshot_rows = ingest_snapshots()
    print(f"Fetching {SOURCE_URL} ...")
    try:
        rows = fetch_and_parse()
    except Exception as e:
        if not snapshot_rows:
            raise
        print(f"  live fetch failed ({type(e).__name__}) - using newest server snapshot instead")
        rows = snapshot_rows
    print(f"  {len(rows)} Direct+Growth SIF schemes found")

    funds = []
    for row in rows:
        key = slugify(row["name"])
        n_points = append_to_cache(key, row["date"], row["nav"])
        label = row["name"] + (" [Interval Fund - restricted liquidity]" if row["interval_fund"] else "")
        funds.append({"key": key, "name": label, "category": "SIF", "strategy": row["strategy"],
                       "code": row["code"], "isin": row["isin"]})
        print(f"  {row['name']:55s} {row['strategy']:35s} NAV={row['nav']:.4f}  "
              f"({n_points} point{'s' if n_points != 1 else ''} accumulated so far)")

    # rebuild the dataset JSON from ALL accumulated cache points (not just today's) -
    # every run adds one more point to each fund's own history. SIF NAVs are daily
    # (like everything AMFI publishes) but every other series in this project is
    # resampled to weekly-Friday, and the page's rolling-window math (4-week
    # momentum, 13/26-week crossover) assumes one step = one week - so resample
    # here too, taking the latest value in each Mon-Fri week, same as build_leaderboard_v2.py
    # does for fund NAVs.
    import pandas as pd

    series = {}
    for f in funds:
        cache = NAV_DIR / f"{f['key']}.csv"
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date").sort_index()
        series[f["key"]] = df["nav"].resample("W-FRI").last()

    all_dates_idx = sorted(set().union(*[s.dropna().index for s in series.values()]))
    all_dates = [d.strftime("%Y-%m-%d") for d in all_dates_idx]

    out_funds = []
    for f in funds:
        s = series[f["key"]].reindex(all_dates_idx)
        values = [None if pd.isna(v) else round(float(v), 4) for v in s]
        out_funds.append({**f, "values": values})

    out = {"dates": all_dates, "funds": out_funds}
    with open(BASE / "sif_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote sif_dataset.json - {len(out_funds)} funds, {len(all_dates)} date(s) accumulated so far")
    if len(all_dates) < 5:
        print("  (this will only get useful once refresh_all.bat has been run weekly for a couple of months -"
              " there's no historical backfill available for SIF, see the module docstring)")


if __name__ == "__main__":
    main()
