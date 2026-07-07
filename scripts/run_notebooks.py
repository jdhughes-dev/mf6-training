#!/usr/bin/env python
"""Execute one or more notebooks end-to-end and fail on any cell error.

Runs each notebook with nbconvert's ExecutePreprocessor using the notebook's own
directory as the working directory (so relative paths like ./models/... resolve
the same way they do interactively). The executed notebook is discarded - nothing
is written back - so this is purely a "does it still run?" smoke test for CI.
Requires the model executables to be on PATH (mf6 via the get-mf6 task). Run
inside the pixi env, e.g. `pixi run test-notebooks`.
"""

import os
import sys
import time
from pathlib import Path

import nbformat
from nbconvert.preprocessors import ExecutePreprocessor

# Notebooks executed by default when no paths are passed on the command line.
# Kept to fast (< ~30 s), self-contained notebooks so CI stays quick; slower
# notebooks (e.g. mf6-api-a/e, mf6-gwe-stallman, mf6-density-henry-hilleke (~8 min),
# mf6-advanced-packages-*) are intentionally excluded. Times below are approximate
# single-run wall times.
DEFAULT_NOTEBOOKS = (
    "examples/notebooks/flopy-intro-gwf-only.ipynb",  # ~6 s
    # Exercises the modflowapi path end-to-end: libmf6 discovery, loading the
    # synthetic-valley data, and driving MODFLOW 6 through the API with a callback.
    "examples/notebooks/mf6-api-c.ipynb",  # ~11 s
    # A manual solver loop watching convergence live (modflowapi, synthetic valley).
    "examples/notebooks/mf6-api-b.ipynb",  # ~21 s
    # A head-dependent reverse drain built through the API package.
    "examples/notebooks/mf6-api-d.ipynb",  # ~5 s
    # A 1-D coupled flow-and-transport benchmark.
    "examples/notebooks/mf6-gwt1d.ipynb",  # ~12 s
    # Variable-density flow: a dense saltwater bubble sinking (coupled GWF-GWT + BUY).
    "examples/notebooks/mf6-density-bubble.ipynb",  # ~15 s
    # Local grid refinement (LGR) with two coupled GWF models.
    "examples/notebooks/mf6-lgr-flopy.ipynb",  # ~5 s
    # Mf6Splitter: 5-block manual split, load-balanced (pymetis) split, HDF5 node mapping.
    "examples/notebooks/mf6-model-splitting-with-flopy.ipynb",  # ~8 s
    # XT3D on an unstructured (DISV) grid with a quadtree-refined interior.
    "examples/notebooks/mf6-xt3d-unstructured.ipynb",  # ~7 s
    # Quadtree unstructured grid built with the Gridgen executable.
    "examples/notebooks/mf6-mesh-generation-gridgen.ipynb",  # ~7 s
    # Triangle + Voronoi unstructured grids built with the Triangle executable.
    "examples/notebooks/mf6-mesh-generation-triangle-voronoi.ipynb",  # ~6 s
    # CSUB land subsidence: no-delay vs delay interbeds (two short runs).
    "examples/notebooks/mf6-csub.ipynb",  # ~19 s
)


def run_notebook(path: Path) -> None:
    nb = nbformat.read(path, as_version=4)
    ep = ExecutePreprocessor(timeout=600, kernel_name="python3")
    # resources.metadata.path sets the cwd for the kernel while executing.
    ep.preprocess(nb, {"metadata": {"path": str(path.parent)}})


def main(argv: list[str]) -> None:
    paths = [Path(p) for p in argv] or [Path(p) for p in DEFAULT_NOTEBOOKS]
    n = len(paths)
    in_gha = os.environ.get("GITHUB_ACTIONS") == "true"

    # list every notebook up front so the CI log shows the full set being tested
    print(f"[run-notebooks] executing {n} notebook{'s' if n != 1 else ''}:", flush=True)
    for i, path in enumerate(paths, start=1):
        print(f"[run-notebooks]   {i:2d}/{n}  {path}", flush=True)

    failures = []
    for i, path in enumerate(paths, start=1):
        print(f"\n[run-notebooks] === ({i}/{n}) executing {path} ===", flush=True)
        start = time.perf_counter()
        try:
            run_notebook(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            elapsed = time.perf_counter() - start
            print(
                f"[run-notebooks] FAILED ({i}/{n}) {path} after {elapsed:.1f} s",
                flush=True,
            )
            if in_gha:
                # single-line GitHub Actions error annotation (surfaces in the UI)
                msg = str(exc).replace("\n", " ")[:500]
                print(f"::error file={path}::notebook failed - {msg}", flush=True)
            print(exc, flush=True)  # full traceback for the CI log
            failures.append(path)
        else:
            elapsed = time.perf_counter() - start
            print(f"[run-notebooks] OK ({i}/{n}) {path} in {elapsed:.1f} s", flush=True)

    print("", flush=True)
    if failures:
        sys.exit(
            f"[run-notebooks] {len(failures)} of {n} notebook(s) failed: "
            + ", ".join(str(p) for p in failures)
        )
    print(f"[run-notebooks] OK: all {n} notebooks executed successfully.", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
