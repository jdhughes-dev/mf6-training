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
# mf6-adv-*) are intentionally excluded. Times below are approximate
# single-run wall times.
DEFAULT_NOTEBOOKS = (
    "examples/notebooks/flopy-intro-gwf-only-a.ipynb",  # ~6 s
    # b loads and post-processes the model a runs, so it must follow a here.
    "examples/notebooks/flopy-intro-gwf-only-b.ipynb",  # ~4 s
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
    # OLF overland flow: steady sheet flow across a plane for several Manning's n.
    "examples/notebooks/mf6-olf.ipynb",  # ~7 s
)


def widget_errors(nb) -> list[str]:
    """Errors raised inside an ipywidgets Output widget.

    The widget-driven notebooks display their figures through
    ipywidgets.interactive_output, which runs its callback inside an Output
    widget. That widget captures a traceback instead of letting the cell fail,
    so the exception never reaches ExecutePreprocessor. Read it back out of the
    stored widget state, which nbclient saves in the notebook metadata.
    """
    errors = []
    for blob in nb.get("metadata", {}).get("widgets", {}).values():
        for model in blob.get("state", {}).values():
            for output in model.get("state", {}).get("outputs", None) or []:
                if output.get("output_type") == "error":
                    errors.append(f"{output.get('ename')}: {output.get('evalue')}")
    return errors


# A cell that blocks fails on the execution timeout with nothing to say where it
# stopped, so have the kernel dump every thread's stack while it is still stuck.
# The timer runs for the whole notebook, well above the slowest one here, so it
# only fires on a hang. Interrupting the kernel on timeout would report the same
# thing, but nbclient then waits without a deadline when the interrupt does not
# take, turning a bounded failure into an unbounded one.
WATCHDOG_SECONDS = 60

# The slowest notebook here takes about thirty seconds, so a hang costs ten
# minutes of the run for nothing. Keep enough headroom for a slow runner and no
# more.
EXECUTE_TIMEOUT = 180

# The kernel replaces sys.stderr with a stream that has no file descriptor, which
# faulthandler requires, so write to the interpreter's own stderr instead. Never
# let the watchdog fail the notebook: it is only a diagnostic.
WATCHDOG_SOURCE = f"""\
import faulthandler as _fh, sys as _sys, time as _time
try:
    _fh.enable(file=_sys.__stderr__)
    _fh.dump_traceback_later(
        {WATCHDOG_SECONDS}, repeat=True, exit=False, file=_sys.__stderr__
    )
except Exception as _exc:
    print(f"stack watchdog unavailable: {{_exc!r}}")

# A stack dump says what the kernel is doing but not which cell it believes it
# is on, which is what separates a cell still running from one that finished
# without its reply reaching the client. Mark both ends of every cell: a start
# with no end is a cell still running, and a start with an end is a cell the
# kernel considers done, leaving the client waiting on a message that never
# arrived.
try:
    _marks = {{"n": 0, "t": 0.0}}

    def _cell_start(*_args):
        _marks["n"] += 1
        _marks["t"] = _time.monotonic()
        print(f"[cell] start {{_marks['n']}}", file=_sys.__stderr__, flush=True)

    def _cell_end(*_args):
        # the cell this was registered from has no start, so it has no end
        if _marks["n"]:
            _elapsed = _time.monotonic() - _marks["t"]
            print(
                f"[cell] end {{_marks['n']}} after {{_elapsed:.1f}}s",
                file=_sys.__stderr__,
                flush=True,
            )

    _events = get_ipython().events
    _events.register("pre_run_cell", _cell_start)
    _events.register("post_run_cell", _cell_end)
except Exception as _exc:
    print(f"cell markers unavailable: {{_exc!r}}")
"""


def watchdog_note(nb) -> str:
    """The watchdog's own message when it could not arm, empty otherwise."""
    for output in nb.cells[0].get("outputs", []) or []:
        text = output.get("text", "")
        if "stack watchdog unavailable" in text:
            return text.strip()
    return ""


def run_notebook(path: Path) -> None:
    nb = nbformat.read(path, as_version=4)
    # the executed copy is discarded, so the added cell never reaches the repository
    nb.cells.insert(0, nbformat.v4.new_code_cell(WATCHDOG_SOURCE))
    ep = ExecutePreprocessor(timeout=EXECUTE_TIMEOUT, kernel_name="python3")
    # resources.metadata.path sets the cwd for the kernel while executing.
    ep.preprocess(nb, {"metadata": {"path": str(path.parent)}})
    note = watchdog_note(nb)
    if note:
        print(f"[run-notebooks] {note}", flush=True)
    errors = widget_errors(nb)
    if errors:
        raise RuntimeError("error in a notebook control callback: " + "; ".join(errors))


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
