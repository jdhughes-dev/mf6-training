#!/usr/bin/env python
"""Execute one or more notebooks end-to-end and fail on any cell error.

Runs each notebook with nbconvert's ExecutePreprocessor using the notebook's own
directory as the working directory (so relative paths like ./models/... resolve
the same way they do interactively). The executed notebook is discarded - nothing
is written back - so this is purely a "does it still run?" smoke test for CI.
Requires the model executables to be on PATH (mf6 via the get-mf6 task). Run
inside the pixi env, e.g. `pixi run test-notebooks`.
"""

import sys
from pathlib import Path

import nbformat
from nbconvert.preprocessors import ExecutePreprocessor

# Notebooks executed by default when no paths are passed on the command line.
# Kept to fast (< ~30 s), self-contained notebooks so CI stays quick; slower
# notebooks (e.g. modflow-api-A/E, gwe-stallman, density-*, advanced-packages-*)
# are intentionally excluded. Times below are approximate single-run wall times.
DEFAULT_NOTEBOOKS = (
    "examples/notebooks/flopy-intro-gwf-only.ipynb",  # ~6 s
    # Exercises the modflowapi path end-to-end: libmf6 discovery, loading the
    # synthetic-valley data, and driving MODFLOW 6 through the API with a callback.
    "examples/notebooks/modflow-api-C.ipynb",  # ~11 s
    # A manual solver loop watching convergence live (modflowapi, synthetic valley).
    "examples/notebooks/modflow-api-B.ipynb",  # ~21 s
    # A head-dependent reverse drain built through the API package.
    "examples/notebooks/modflow-api-D.ipynb",  # ~5 s
    # A 1-D coupled flow-and-transport benchmark.
    "examples/notebooks/gwt1d.ipynb",  # ~12 s
    # Local grid refinement (LGR) with two coupled GWF models.
    "examples/notebooks/lgr-flopy.ipynb",  # ~5 s
    # Mf6Splitter: 5-block manual split, load-balanced (pymetis) split, HDF5 node mapping.
    "examples/notebooks/model-splitting-with-flopy.ipynb",  # ~8 s
    # XT3D on an unstructured (DISU) grid.
    "examples/notebooks/xt3d-unstructured.ipynb",  # ~7 s
    # Quadtree unstructured grid built with the Gridgen executable.
    "examples/notebooks/mesh-generation-gridgen.ipynb",  # ~7 s
    # Triangle + Voronoi unstructured grids built with the Triangle executable.
    "examples/notebooks/mesh-generation-triangle-voronoi.ipynb",  # ~6 s
)


def run_notebook(path: Path) -> None:
    nb = nbformat.read(path, as_version=4)
    ep = ExecutePreprocessor(timeout=600, kernel_name="python3")
    # resources.metadata.path sets the cwd for the kernel while executing.
    ep.preprocess(nb, {"metadata": {"path": str(path.parent)}})


def main(argv: list[str]) -> None:
    paths = [Path(p) for p in argv] or [Path(p) for p in DEFAULT_NOTEBOOKS]
    failures = []
    for path in paths:
        print(f"[run-notebooks] executing {path} ...", flush=True)
        try:
            run_notebook(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"[run-notebooks] FAILED {path}: {exc}", flush=True)
            failures.append(path)
        else:
            print(f"[run-notebooks] OK {path}", flush=True)
    if failures:
        sys.exit("[run-notebooks] failed: " + ", ".join(str(p) for p in failures))
    print("[run-notebooks] OK: all notebooks executed.")


if __name__ == "__main__":
    main(sys.argv[1:])
