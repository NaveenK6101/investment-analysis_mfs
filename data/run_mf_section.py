"""Execute ONLY the rebuilt MF-comparison section (cells 110-124) of the notebook.

The rest of the notebook is left completely alone: cells 0-109 contain other
pm.sample calls without cores=1 (which deadlock under Windows multiprocessing)
plus at least one pre-existing broken cell, so a full-notebook run is not viable.

This builds a temporary notebook holding just the section's cells, executes it
with nbclient (cwd = the notebook's own directory, so `../data/nav` resolves),
then merges the resulting outputs back into the full notebook in place.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

NB_PATH = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files\leaveraged_inv_strategy.ipynb")
START, END = 110, 125  # [START, END)


def main() -> int:
    nb = nbformat.read(NB_PATH, as_version=4)
    print(f"Loaded notebook: {len(nb.cells)} cells", flush=True)

    section = copy.deepcopy(nb)
    section.cells = section.cells[START:END]
    print(f"Executing cells {START}..{END - 1} ({len(section.cells)} cells)", flush=True)

    client = NotebookClient(
        section,
        timeout=3600,
        kernel_name="python3",
        resources={"metadata": {"path": str(NB_PATH.parent)}},
        allow_errors=True,          # keep going so we see every failure in one pass
    )
    client.execute()

    failures = []
    for offset, cell in enumerate(section.cells):
        idx = START + offset
        for out in cell.get("outputs", []):
            if out.get("output_type") == "error":
                failures.append((idx, out.get("ename"), out.get("evalue"),
                                 "\n".join(out.get("traceback", []))[-1500:]))

    # merge executed outputs back into the full notebook
    for offset, cell in enumerate(section.cells):
        target = nb.cells[START + offset]
        if cell.cell_type == "code":
            target["outputs"] = cell.get("outputs", [])
            target["execution_count"] = cell.get("execution_count")

    nbformat.validator.normalize(nb)   # adds missing cell ids
    nbformat.write(nb, NB_PATH)
    print(f"Merged outputs back into {NB_PATH.name}", flush=True)

    print("\n" + "=" * 70, flush=True)
    if failures:
        print(f"{len(failures)} CELL(S) FAILED", flush=True)
        for idx, ename, evalue, tb in failures:
            print(f"\n--- cell {idx}: {ename}: {evalue} ---", flush=True)
            print(tb, flush=True)
        return 1

    print("ALL CELLS EXECUTED CLEANLY", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
