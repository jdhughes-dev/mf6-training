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
DEFAULT_NOTEBOOKS = (
    "examples/notebooks/flopy-intro-gwf-only.ipynb",
    # Exercises the modflowapi path end-to-end: libmf6 discovery, loading the
    # synthetic-valley data, and driving MODFLOW 6 through the API with a callback.
    "examples/notebooks/modflow-api-C.ipynb",
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
