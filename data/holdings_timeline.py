"""When did Helios Small Cap actually buy its pharma/healthcare positions?

Downloads every monthly portfolio disclosure the AMC publishes and diffs them.
Two things matter and they are not the same:

  * "% to AUM" moves on its own as prices move, so a rising weight does NOT
    mean the manager bought anything.
  * QUANTITY (share count) only changes when they actually trade.

So the timeline below is built off quantity, and weight is carried along only for
context. Positions are keyed by ISIN rather than name, because two of these
companies were renamed (Ami Organics -> Acutaas Chemicals, Glenmark Life
Sciences -> Alivus Life Sciences) and name-matching would show a phantom exit
followed by a phantom new buy.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://www.heliosmf.in"
OUT = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data\portfolios")
OUT.mkdir(parents=True, exist_ok=True)

# the AMC's WAF returns 406 without a browser UA + referer
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": f"{BASE}/portfolio-disclosure/",
}

FILES = {
    "2025-11": "/wp-content/uploads/2025/12/Helios-Small-Cap-Fund-Monthly-Portfolio-as-on-30th-November-2025.xlsx",
    "2025-12": "/wp-content/uploads/2026/01/Helios-Small-Cap-Fund-Monthly-Portfolio-as-on-31st-December-2025.xlsx",
    "2026-01": "/wp-content/uploads/2026/02/Helios-Small-Cap-Fund-Monthly-Portfolio-as-on-31st-January-2026.xlsx",
    "2026-02": "/wp-content/uploads/2026/03/Helios-Small-Cap-Fund-28th-February-2026.xlsx",
    "2026-03": "/wp-content/uploads/2026/04/Helios-Small-Cap-Fund-Monthly-Portfolio-as-on-31st-March-2026.xlsx",
    "2026-04": "/wp-content/uploads/2026/05/Helios-Small-Cap-Fund-Monthly-Portfolio-as-on-30th-April-2026.xlsx",
    "2026-05": "/wp-content/uploads/2026/06/Helios-Small-Cap-Fund-Monthly-Portfolio-as-on-31st-May-2026.xlsx",
    "2026-06": "/wp-content/uploads/2026/07/Helios-Small-Cap-Fund-Monthly-Portfolio-as-on-30th-June-2026.xlsx",
    "2026-07": "/wp-content/uploads/2026/08/helios-small-cap-fund-monthly-portfolio-as-on-31st-july-2026.xlsx",
    "2026-08": "/wp-content/uploads/2026/09/helios-small-cap-fund-monthly-portfolio-as-on-31st-august-2026.xlsx",
}

PHARMA = re.compile(r"pharmaceutical|healthcare|biotech|health services|hospital", re.I)


def download(month: str, path: str) -> Path | None:
    dest = OUT / f"helios_{month}.xlsx"
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    url = path if path.startswith("http") else BASE + path
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        if not r.content.startswith(b"PK"):          # xlsx is a zip
            print(f"  {month}: not an xlsx (got {len(r.content)} bytes)")
            return None
        dest.write_bytes(r.content)
        time.sleep(0.4)
        return dest
    except Exception as e:
        print(f"  {month}: download failed - {e}")
        return None


def parse(path: Path) -> pd.DataFrame:
    """-> DataFrame[isin, name, industry, quantity, pct_aum] for equity holdings."""
    raw = pd.read_excel(path, sheet_name=0, header=None)

    rows = []
    for _, r in raw.iterrows():
        isin = str(r.iloc[3]).strip()
        if not re.fullmatch(r"INE[0-9A-Z]{9}", isin):   # equity ISINs only
            continue
        try:
            qty = float(r.iloc[5])
            pct = float(r.iloc[7])
        except (TypeError, ValueError):
            continue
        rows.append({
            "isin": isin,
            "name": str(r.iloc[2]).strip().rstrip("."),
            "industry": str(r.iloc[4]).strip(),
            "quantity": qty,
            "pct_aum": pct,
        })

    df = pd.DataFrame(rows)
    # a scheme can list the same ISIN twice (different lots); collapse them
    if not df.empty:
        df = (df.groupby("isin", as_index=False)
                .agg(name=("name", "first"), industry=("industry", "first"),
                     quantity=("quantity", "sum"), pct_aum=("pct_aum", "sum")))
    return df


def main() -> int:
    print("Downloading Helios Small Cap monthly portfolios...")
    frames = {}
    for month, path in FILES.items():
        f = download(month, path)
        if f is None:
            continue
        df = parse(f)
        if df.empty:
            print(f"  {month}: parsed 0 holdings - check layout")
            continue
        frames[month] = df
        n_ph = df["industry"].str.contains(PHARMA).sum()
        print(f"  {month}: {len(df):3d} holdings ({n_ph} pharma/healthcare)")

    if not frames:
        print("no portfolios parsed")
        return 1

    months = sorted(frames)

    # every ISIN that was ever in a pharma/healthcare industry bucket
    pharma_isins = {}
    for m in months:
        d = frames[m]
        for _, r in d[d["industry"].str.contains(PHARMA)].iterrows():
            pharma_isins[r["isin"]] = r["name"]

    qty = pd.DataFrame(index=sorted(pharma_isins), columns=months, dtype=float)
    pct = qty.copy()
    for m in months:
        d = frames[m].set_index("isin")
        for isin in qty.index:
            if isin in d.index:
                qty.at[isin, m] = d.at[isin, "quantity"]
                pct.at[isin, m] = d.at[isin, "pct_aum"]

    qty.insert(0, "stock", [pharma_isins[i] for i in qty.index])
    pct.insert(0, "stock", [pharma_isins[i] for i in pct.index])

    qty.to_csv(OUT.parent / "helios_pharma_quantity.csv")
    pct.to_csv(OUT.parent / "helios_pharma_weight.csv")

    # ---- narrative timeline -------------------------------------------------
    print("\n" + "=" * 78)
    print("HELIOS SMALL CAP - pharma/healthcare entry & activity (by share count)")
    print("=" * 78)

    summary = []
    for isin in qty.index:
        series = qty.loc[isin, months].astype(float)
        held = series.dropna()
        if held.empty:
            continue
        first_month = held.index[0]
        first_qty = held.iloc[0]
        last_qty = held.iloc[-1]
        still_held = pd.notna(series[months[-1]])

        adds, trims = [], []
        prev = None
        for m in months:
            v = series[m]
            if pd.isna(v):
                prev = None if pd.isna(v) else prev
                continue
            if prev is not None and prev > 0:
                chg = (v - prev) / prev
                if chg > 0.05:
                    adds.append(f"{m} +{chg*100:.0f}%")
                elif chg < -0.05:
                    trims.append(f"{m} {chg*100:.0f}%")
            prev = v

        summary.append({
            "stock": pharma_isins[isin],
            "first_seen": first_month,
            "months_held": int(held.notna().sum()),
            "initial_qty": int(first_qty),
            "latest_qty": int(last_qty) if still_held else 0,
            "qty_change_since_entry_pct": round((last_qty / first_qty - 1) * 100, 1) if still_held and first_qty else None,
            "still_held": still_held,
            "added_in": "; ".join(adds) if adds else "-",
            "trimmed_in": "; ".join(trims) if trims else "-",
        })

    out = pd.DataFrame(summary).sort_values(["first_seen", "stock"])
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(out.to_string(index=False))
    out.to_csv(OUT.parent / "helios_pharma_timeline.csv", index=False)

    print(f"\nfirst disclosure: {months[0]}   latest: {months[-1]}")
    print("NOTE: the fund's first-ever portfolio is", months[0],
          "- anything 'first seen' there was bought at launch, not added later.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
