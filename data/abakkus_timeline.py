"""When did Abakkus Small Cap buy its pharma/healthcare positions?

Same method as the Helios script: diff consecutive monthly disclosures on SHARE
COUNT, not weight, and key on ISIN so renames don't look like an exit plus a
re-entry.

Abakkus publishes one workbook per month covering every scheme, so the Small Cap
sheet ("ABASC") has to be picked out of it. Files are served with a .xls
extension but are actually xlsx underneath, hence engine="openpyxl". Weights in
these files are decimals (0.0191 = 1.91%).

The fund's first-ever portfolio is March 2026, so anything present in that month
was bought at launch rather than added later.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data\portfolios")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.abakkusmf.com/statutory-disclosures.html",
}

FILES = {
    "2026-03": "https://www.abakkusmf.com/uploads/IN_MF_MONTHLY_PORTFOLIO_March_31_2026_eb4d2050b9.xls",
    "2026-04": "https://www.abakkusmf.com/uploads/IN_MF_MONTHLY_PORTFOLIO_April_30_2026_48e9b6a58c.xls",
    "2026-05": "https://www.abakkusmf.com/uploads/Abakkus_Mutual_Fund_31_05_2026_f7ac956d1d.xls",
    "2026-06": "https://www.abakkusmf.com/uploads/Monthly_Portfolio_Jun26_30_Jun_65d7e26b0a.xls",
    "2026-07": "https://www.abakkusmf.com/uploads/Final_Monthly_Portfolio_Jul_31_a313e9e6dd.xls",
    "2026-08": "https://www.abakkusmf.com/uploads/Portfolio_Aug31_Monthly_a00d994a66.xls",
}

PHARMA = re.compile(r"pharmaceutical|healthcare|biotech|health services|hospital", re.I)
ISIN_RE = re.compile(r"INE[0-9A-Z]{9}")


def download(month: str, url: str) -> Path | None:
    dest = OUT / f"abakkus_{month}.xls"
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        if not r.content.startswith(b"PK"):
            print(f"  {month}: unexpected format ({len(r.content)} bytes)")
            return None
        dest.write_bytes(r.content)
        time.sleep(0.4)
        return dest
    except Exception as e:
        print(f"  {month}: download failed - {e}")
        return None


def small_cap_sheet(path: Path) -> str | None:
    """Find the Small Cap scheme's sheet, via the Index tab where present."""
    xl = pd.ExcelFile(path, engine="openpyxl")
    try:
        idx = pd.read_excel(path, sheet_name="Index", header=None, engine="openpyxl")
        for _, r in idx.iterrows():
            vals = [str(v) for v in r.tolist()]
            if any("small cap" in v.lower() for v in vals):
                for v in vals:
                    if v.strip() in xl.sheet_names:
                        return v.strip()
    except Exception:
        pass
    for s in xl.sheet_names:                      # fallback on the naming pattern
        if re.search(r"ASC|SMALL", s, re.I):
            return s
    return None


def parse(path: Path) -> pd.DataFrame:
    sheet = small_cap_sheet(path)
    if sheet is None:
        return pd.DataFrame()
    raw = pd.read_excel(path, sheet_name=sheet, header=None, engine="openpyxl")

    # locate the header row, then the columns by their labels
    hdr = None
    for i in range(min(12, len(raw))):
        joined = " ".join(str(v).lower() for v in raw.iloc[i].tolist())
        if "name of the instrument" in joined:
            hdr = i
            break
    if hdr is None:
        return pd.DataFrame()

    cols = {}
    for j, v in enumerate(raw.iloc[hdr].tolist()):
        lab = re.sub(r"\s+", " ", str(v)).strip().lower()
        if lab.startswith("name of the instrument"):
            cols["name"] = j
        elif lab == "isin":
            cols["isin"] = j
        elif lab.startswith("industry"):
            cols["industry"] = j
        elif lab.startswith("quantity"):
            cols["quantity"] = j
        elif lab.startswith("% to net"):
            cols["pct"] = j
    if not {"name", "isin", "quantity", "pct"} <= cols.keys():
        return pd.DataFrame()

    rows = []
    for _, r in raw.iloc[hdr + 1:].iterrows():
        isin = str(r.iloc[cols["isin"]]).strip()
        if not ISIN_RE.fullmatch(isin):
            continue
        try:
            qty = float(r.iloc[cols["quantity"]])
            pct = float(r.iloc[cols["pct"]])
        except (TypeError, ValueError):
            continue
        rows.append({
            "isin": isin,
            "name": str(r.iloc[cols["name"]]).strip().rstrip("."),
            "industry": str(r.iloc[cols.get("industry", cols["name"])]).strip(),
            "quantity": qty,
            "pct_aum": pct * 100 if pct < 1.5 else pct,     # decimals -> percent
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = (df.groupby("isin", as_index=False)
                .agg(name=("name", "first"), industry=("industry", "first"),
                     quantity=("quantity", "sum"), pct_aum=("pct_aum", "sum")))
    return df


def main() -> int:
    print("Downloading Abakkus Small Cap monthly portfolios...")
    frames = {}
    for month, url in FILES.items():
        f = download(month, url)
        if f is None:
            continue
        df = parse(f)
        if df.empty:
            print(f"  {month}: parsed 0 holdings - layout may differ")
            continue
        frames[month] = df
        print(f"  {month}: {len(df):3d} holdings "
              f"({df['industry'].str.contains(PHARMA).sum()} pharma/healthcare)")

    if not frames:
        return 1

    months = sorted(frames)
    pharma = {}
    for m in months:
        d = frames[m]
        for _, r in d[d["industry"].str.contains(PHARMA)].iterrows():
            pharma[r["isin"]] = r["name"]

    qty = pd.DataFrame(index=sorted(pharma), columns=months, dtype=float)
    for m in months:
        d = frames[m].set_index("isin")
        for isin in qty.index:
            if isin in d.index:
                qty.at[isin, m] = d.at[isin, "quantity"]

    print("\n" + "=" * 78)
    print("ABAKKUS SMALL CAP - pharma/healthcare entry & activity (by share count)")
    print("=" * 78)

    rows = []
    for isin in qty.index:
        s = qty.loc[isin, months].astype(float)
        held = s.dropna()
        if held.empty:
            continue
        adds, trims, prev = [], [], None
        for m in months:
            v = s[m]
            if pd.isna(v):
                prev = None
                continue
            if prev and prev > 0:
                chg = (v - prev) / prev
                if chg > 0.05:
                    adds.append(f"{m} +{chg*100:.0f}%")
                elif chg < -0.05:
                    trims.append(f"{m} {chg*100:.0f}%")
            prev = v
        still = pd.notna(s[months[-1]])
        rows.append({
            "stock": pharma[isin],
            "first_seen": held.index[0],
            "months_held": int(held.notna().sum()),
            "initial_qty": int(held.iloc[0]),
            "latest_qty": int(held.iloc[-1]) if still else 0,
            "qty_change_pct": round((held.iloc[-1] / held.iloc[0] - 1) * 100, 1) if still and held.iloc[0] else None,
            "still_held": still,
            "added_in": "; ".join(adds) or "-",
            "trimmed_in": "; ".join(trims) or "-",
        })

    out = pd.DataFrame(rows).sort_values(["first_seen", "stock"])
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(out.to_string(index=False))
    out.to_csv(OUT.parent / "abakkus_pharma_timeline.csv", index=False)
    print(f"\nfirst disclosure: {months[0]} (fund launched Mar 2026)   latest: {months[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
