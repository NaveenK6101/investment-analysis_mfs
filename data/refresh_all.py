"""One command to bring everything current: universe check -> price refresh
-> rebuild every dataset -> re-embed fresh JSON into both HTML pages ->
regenerate the Sheets CSV -> git commit + push.

Usage:
    python refresh_all.py                 # full run: universe check + prices
    python refresh_all.py --prices-only    # skip the universe check (faster;
                                            # use for a quick weekly price-only
                                            # refresh between the occasional
                                            # full runs)
    python refresh_all.py --no-git         # build everything but don't commit/push

Steps 1-9 are plain re-fetches and rebuilds of files already in this repo;
nothing here overwrites your working tree outside data/. Step 10 runs
`git add -A && git commit && git push` on this repo - skip it with --no-git
if you'd rather review the diff yourself first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
REPO = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment")
PY = sys.executable  # the interpreter running this script - reuse it for every step


def run_step(label: str, script: str) -> bool:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}", flush=True)
    result = subprocess.run([PY, str(BASE / script)], cwd=str(BASE))
    if result.returncode != 0:
        print(f"\n!! {script} exited with code {result.returncode} - stopping here.")
        return False
    return True


def inject_json(html_path: Path, json_path: Path, marker_prefix: str) -> None:
    """Replace the embedded `const X = {...};` line in an HTML page with the
    freshly-built JSON. Same line-splice approach used by hand all session -
    finds the line starting with marker_prefix and swaps its payload."""
    lines = html_path.read_text(encoding="utf-8").splitlines(keepends=True)
    idx = next((i for i, line in enumerate(lines) if line.startswith(marker_prefix)), None)
    if idx is None:
        raise RuntimeError(f"could not find a line starting with {marker_prefix!r} in {html_path.name}")
    data_json = json_path.read_text(encoding="utf-8")
    lines[idx] = marker_prefix + data_json + ";\n"
    html_path.write_text("".join(lines), encoding="utf-8")
    print(f"  injected {json_path.name} -> {html_path.name} ({len(data_json) / 1024:.0f} KB)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices-only", action="store_true",
                         help="skip the universe re-verification step (funds added/removed)")
    parser.add_argument("--no-git", action="store_true", help="build everything but don't commit/push")
    args = parser.parse_args()

    started = dt.datetime.now()

    if not args.prices_only:
        if not run_step("1. Universe check (new NFOs, merged/delisted funds)", "refresh_universe.py"):
            sys.exit(1)
    else:
        print("\nSkipping universe check (--prices-only). Fund list unchanged from last run.")

    steps = [
        ("2. Cap-category prices + dataset (Small/Large/Flexi/Multi Cap, Multi Asset)", "build_leaderboard_v2.py"),
        ("3. Sector prices + dataset", "build_sector_dataset.py"),
        ("4. Sector composites (rebuilt from the sector dataset, no fetch)", "build_sector_composites.py"),
        ("5. RRG series (rebuilt from sector composites, no fetch)", "build_rrg_series.py"),
        ("6. Crypto prices + dataset", "build_crypto_dataset.py"),
        ("7. Metals prices + dataset", "build_metals_dataset.py"),
        ("8. SIF snapshot (appends one more point to accumulated history, no backfill)", "build_sif_dataset.py"),
        ("9. Asset class composites (Equity/Gold/Silver/Crypto blended, no fetch)", "build_asset_class_composites.py"),
        ("10. Asset class RRG series (rebuilt from the composites, no fetch)", "build_asset_class_rrg_series.py"),
        ("11. Merge everything into the combined leaderboard dataset", "merge_datasets.py"),
        ("12. Rebuild the Google Sheets CSV snapshot", "build_sheets_export.py"),
    ]
    for label, script in steps:
        if not run_step(label, script):
            sys.exit(1)

    print(f"\n{'=' * 70}\n13. Re-embedding fresh data into the HTML pages\n{'=' * 70}")
    inject_json(BASE / "mf_relative_strength_6m.html", BASE / "leaderboard_combined_dataset.json", "  const DATA = ")
    inject_json(BASE / "sector_rotation_map.html", BASE / "rrg_series.json", "  const RRG = ")
    inject_json(BASE / "asset_rotation_map.html", BASE / "asset_class_rrg_series.json", "  const RRG = ")

    elapsed = (dt.datetime.now() - started).total_seconds()
    print(f"\nDone in {elapsed / 60:.1f} min.")

    if args.no_git:
        print("Skipping git commit/push (--no-git). Review the diff yourself, then commit when ready.")
        return

    print(f"\n{'=' * 70}\n14. git commit + push\n{'=' * 70}")
    status = subprocess.run(["git", "status", "--short"], cwd=str(REPO), capture_output=True, text=True)
    if not status.stdout.strip():
        print("No changes to commit (data was already current).")
        return

    today = dt.date.today().isoformat()
    subprocess.run(["git", "add", "-A"], cwd=str(REPO), check=True)
    subprocess.run(["git", "commit", "-m", f"Automated data refresh: {today}"], cwd=str(REPO), check=True)
    subprocess.run(["git", "push"], cwd=str(REPO), check=True)
    print(f"\nCommitted and pushed as of {today}.")


if __name__ == "__main__":
    main()
