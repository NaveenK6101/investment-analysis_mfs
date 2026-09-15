"""When did TRUSTMF Small Cap buy its pharma/healthcare positions?

Same method as the Helios and Abakkus scripts: diff consecutive disclosures on
SHARE COUNT (weight moves with price; quantity only moves when they trade), keyed
on ISIN so the Ami Organics -> Acutaas Chemicals rename doesn't read as an exit
plus a fresh buy.

This fund has the longest run of the three - launched Nov 2024, so 21 monthly
disclosures plus the 31-Aug-2026 fortnightly (the August monthly isn't out yet).
Each workbook covers every TRUSTMF scheme, so the Small Cap sheet gets picked out.
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
    "Referer": "https://www.trustmf.com/disclosures",
}

B = "https://trustmf.com"
FILES = {
    "2024-11": f"{B}/content/2024/12/TRUSTMF-Monthly-Portfolio-Report-as-on-30.11.2024.xls",
    "2024-12": f"{B}/content/2025/01/TRUSTMF-Monthly-Portfolio-Report-as-on-31.12.2024.xls",
    "2025-01": f"{B}/content/2025/02/TRUSTMF-Monthly-Portfolio-Report-as-on-31.01.2025.xls",
    "2025-02": f"{B}/content/2025/03/TRUSTMF-Monthly-Portfolio-Report-as-on-28.02.2025.xls",
    "2025-03": f"{B}/content/2025/04/TRUSTMF-Monthly-Portfolio-Report-as-on-31.03.2025.xls",
    "2025-04": f"{B}/content/2025/05/TRUSTMF-Monthly-Portfolio-Report-as-on-30.04.2025.xls",
    "2025-05": f"{B}/content/2025/06/TRUSTMF-Monthly-Portfolio-Report-as-on-31.05.2025.xls",
    "2025-06": f"{B}/content/2025/07/TRUSTMF-Monthly-Portfolio-Report-as-on-30.06.2025_R.xls",
    "2025-07": f"{B}/content/2025/07/TRUSTMF-Monthly-Portfolio-Report-as-on-31.07.2025_R.xls",
    "2025-08": f"{B}/content/2025/09/TRUSTMF-Monthly-Portfolio-Report-as-on-31.08.2025.xls",
    "2025-09": f"{B}/content/2025/10/TRUSTMF-Monthly-Portfolio-Report-as-on-30.09.2025-1.xls",
    "2025-10": f"{B}/content/2025/11/TRUSTMF-Monthly-Portfolio-Report-as-on-31.10.2025.xls",
    "2025-11": f"{B}/content/2025/12/TRUSTMF-Monthly-Portfolio-Report-as-on-30.11.2025-002.xls",
    "2025-12": f"{B}/content/2026/01/TRUSTMF-Monthly-Portfolio-Report-as-on-31.12.2025.xls",
    "2026-01": f"{B}/content/2026/02/TRUSTMF-Monthly-Portfolio-Report-as-on-31.01.2026.xls",
    "2026-02": f"{B}/Content/2026/3/TRUSTMF Mont_20260312105435.xlsx",
    "2026-03": f"{B}/Content/2026/4/TRUSTMF Mont_20260410104549.xlsx",
    "2026-04": f"{B}/Content/2026/5/Monthly Port_20260508133215.xlsx",
    "2026-05": f"{B}/Content/2026/6/Monthly Port_20260609172736.xlsx",
    "2026-06": f"{B}/Content/2026/7/Copy of Mont_20260709122827.xlsx",
    "2026-07": f"{B}/Content/2026/8/Monthly Port_20260808164739.xlsx",
    "2026-08": f"{B}/Content/2026/9/Fortnighly P_20260908165526.xlsx",   # fortnightly: Aug monthly not published yet
}

PHARMA = re.compile(r"pharmaceutical|healthcare|biotech|health services|hospital", re.I)
ISIN_RE = re.compile(r"INE[0-9A-Z]{9}")


def download(month: str, url: str) -> Path | None:
    ext = ".xlsx" if url.lower().endswith(".xlsx") else ".xls"
    dest = OUT / f"trustmf_{month}{ext}"
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    try:
        r = requests.get(url, headers=HEADERS, timeout=90)
        r.raise_for_status()
        # xlsx is a zip ("PK"); the pre-2026 files are genuine legacy OLE2 .xls
        if not (r.content.startswith(b"PK") or r.content.startswith(b"\xd0\xcf\x11\xe0")):
            print(f"  {month}: unrecognised format ({len(r.content)} bytes) - skipped")
            return None
        if r.content.startswith(b"\xd0\xcf\x11\xe0"):
            dest = dest.with_suffix(".xls")
        dest.write_bytes(r.content)
        time.sleep(0.3)
        return dest
    except Exception as e:
        print(f"  {month}: download failed - {str(e)[:70]}")
        return None


def engine_for(path: Path) -> str:
    """Pick the reader from the file's magic bytes - the extensions lie here."""
    with open(path, "rb") as fh:
        return "openpyxl" if fh.read(2) == b"PK" else "xlrd"


def small_cap_sheet(path: Path) -> str | None:
    eng = engine_for(path)
    xl = pd.ExcelFile(path, engine=eng)
    for s in xl.sheet_names:
        if re.search(r"small|SCAP", s, re.I):
            return s
    # some workbooks name sheets by code; fall back to scanning the title cell
    for s in xl.sheet_names:
        try:
            head = pd.read_excel(path, sheet_name=s, header=None, nrows=5, engine=eng)
            if head.astype(str).apply(lambda c: c.str.contains("Small Cap", case=False, na=False)).any().any():
                return s
        except Exception:
            continue
    return None


def parse(path: Path) -> pd.DataFrame:
    sheet = small_cap_sheet(path)
    if sheet is None:
        return pd.DataFrame()
    raw = pd.read_excel(path, sheet_name=sheet, header=None, engine=engine_for(path))

    hdr = None
    for i in range(min(15, len(raw))):
        joined = " ".join(str(v).lower() for v in raw.iloc[i].tolist())
        # some months write "Name of Instrument", others "Name of the Instrument"
        if "name of the instrument" in joined or "name of instrument" in joined:
            hdr = i
            break
    if hdr is None:
        return pd.DataFrame()

    cols = {}
    for j, v in enumerate(raw.iloc[hdr].tolist()):
        lab = re.sub(r"\s+", " ", str(v)).strip().lower()
        if lab.startswith("name of the instrument") or lab.startswith("name of instrument"):
            cols["name"] = j
        elif lab == "isin":
            cols["isin"] = j
        elif "industry" in lab:                       # "Industry", "Rating/Industry", ...
            cols["industry"] = j
        elif lab.startswith("quantity"):
            cols["quantity"] = j
        elif lab.startswith("% to net") or lab.startswith("% to aum"):
            cols["pct"] = j
    if not {"name", "isin", "quantity"} <= cols.keys():
        return pd.DataFrame()

    rows = []
    for _, r in raw.iloc[hdr + 1:].iterrows():
        isin = str(r.iloc[cols["isin"]]).strip()
        if not ISIN_RE.fullmatch(isin):
            continue
        try:
            qty = float(r.iloc[cols["quantity"]])
        except (TypeError, ValueError):
            continue
        pct = None
        if "pct" in cols:
            try:
                pct = float(r.iloc[cols["pct"]])
                pct = pct * 100 if pct < 1.5 else pct
            except (TypeError, ValueError):
                pct = None
        rows.append({
            "isin": isin,
            "name": str(r.iloc[cols["name"]]).strip().rstrip("."),
            "industry": str(r.iloc[cols.get("industry", cols["name"])]).strip(),
            "quantity": qty,
            "pct_aum": pct,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = (df.groupby("isin", as_index=False)
                .agg(name=("name", "first"), industry=("industry", "first"),
                     quantity=("quantity", "sum"), pct_aum=("pct_aum", "sum")))
    return df


def main() -> int:
    print("Downloading TRUSTMF Small Cap portfolios (launched Nov 2024)...")
    frames = {}
    for month, url in FILES.items():
        f = download(month, url)
        if f is None:
            continue
        df = parse(f)
        if df.empty:
            print(f"  {month}: no Small Cap holdings parsed")
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
    print("TRUSTMF SMALL CAP - pharma/healthcare entry & activity (by share count)")
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
                if chg > 0.10:
                    adds.append(f"{m} +{chg*100:.0f}%")
                elif chg < -0.10:
                    trims.append(f"{m} {chg*100:.0f}%")
            prev = v
        still = pd.notna(s[months[-1]])
        rows.append({
            "stock": pharma[isin][:38],
            "first_seen": held.index[0],
            "months_held": int(held.notna().sum()),
            "latest_qty": int(held.iloc[-1]) if still else 0,
            "qty_change_pct": round((held.iloc[-1] / held.iloc[0] - 1) * 100, 1) if still and held.iloc[0] else None,
            "still_held": still,
            "added_in": "; ".join(adds[:4]) or "-",
            "trimmed_in": "; ".join(trims[:3]) or "-",
        })

    out = pd.DataFrame(rows).sort_values(["first_seen", "stock"])
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print(out.to_string(index=False))
    out.to_csv(OUT.parent / "trustmf_pharma_timeline.csv", index=False)
    print(f"\nfirst disclosure parsed: {months[0]}   latest: {months[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
