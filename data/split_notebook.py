"""Extract the rebuilt MF-comparison section into its own notebook.

Moves cells 110-124 out of leaveraged_inv_strategy.ipynb (which is a grab-bag of
unrelated analyses) and into a standalone mf_leveraged_strategy.ipynb, so the
mutual-fund work lives in exactly one place. Executed outputs, if present, are
carried over. The original 4-fund version stays preserved in git history / main.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import nbformat

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files")
SRC = BASE / "leaveraged_inv_strategy.ipynb"
DST = BASE / "mf_leveraged_strategy.ipynb"
START, END = 110, 129  # [START, END) - 19 cells, including the year-on-year block


def main() -> int:
    nb = nbformat.read(SRC, as_version=4)
    total = len(nb.cells)
    print(f"Source notebook: {total} cells", flush=True)

    section = nb.cells[START:END]

    # sanity check: make sure we are grabbing the right block
    head = section[0].source.lstrip()
    if not head.startswith("### Compare mutual fund returns"):
        raise SystemExit(f"Cell {START} is not the MF section header, got: {head[:80]!r}")
    if "simulate_leveraged_wealth_for_ltv" not in section[-1].source:
        raise SystemExit(f"Cell {END - 1} is not the LTV sweep cell")

    n_with_outputs = sum(1 for c in section if c.get("outputs"))
    print(f"Extracting {len(section)} cells ({n_with_outputs} carrying outputs)", flush=True)

    # ---- build the standalone notebook ----
    new_nb = nbformat.v4.new_notebook()
    new_nb.metadata = copy.deepcopy(nb.metadata)
    new_nb.cells = copy.deepcopy(section)
    nbformat.validator.normalize(new_nb)
    nbformat.write(new_nb, DST)
    print(f"Wrote {DST.name} with {len(new_nb.cells)} cells", flush=True)

    # ---- remove the section from the original ----
    nb.cells = nb.cells[:START] + nb.cells[END:]
    nbformat.validator.normalize(nb)
    nbformat.write(nb, SRC)
    print(f"Removed cells {START}..{END - 1} from {SRC.name}: {total} -> {len(nb.cells)} cells", flush=True)

    # ---- verify both files reload cleanly ----
    for path in (SRC, DST):
        reloaded = nbformat.read(path, as_version=4)
        nbformat.validate(reloaded)
        print(f"{path.name}: valid, {len(reloaded.cells)} cells", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
