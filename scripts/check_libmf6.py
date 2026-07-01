#!/usr/bin/env python
"""Smoke-test that modflowapi can load the MODFLOW 6 shared library (libmf6).

modflowapi drives a running MODFLOW 6 through ``libmf6`` (the BMI/XMI shared
library). The extended build installed by the ``get-mf6`` task / activation hook
places ``libmf6`` in the pixi environment prefix:

  * Windows : ``<prefix>/bin/libmf6.dll`` (alongside its PETSc/MPI DLLs)
  * Linux   : ``<prefix>/lib/libmf6.so``
  * macOS   : ``<prefix>/lib/libmf6.dylib``

This locates that file and loads it with ctypes, which also exercises its
runtime dependencies (PETSc/MPI). Exits non-zero if it is missing or fails to
load. Run inside the pixi env, e.g. ``pixi run python scripts/check_libmf6.py``.
"""

import ctypes
import os
import sys
from pathlib import Path

import modflowapi


def conda_prefix() -> Path:
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix:
        sys.exit(
            "CONDA_PREFIX is not set - run this inside the pixi environment "
            "(e.g. `pixi run python scripts/check_libmf6.py`)."
        )
    return Path(prefix)


def find_libmf6(prefix: Path) -> Path:
    if sys.platform.startswith("win"):
        name = "libmf6.dll"
    elif sys.platform == "darwin":
        name = "libmf6.dylib"
    else:
        name = "libmf6.so"
    # Check the usual locations first (fast path), then fall back to a recursive
    # search. meson installs the Linux .so under a multiarch subdir such as
    # lib/x86_64-linux-gnu, which a fixed-dir list would miss.
    for d in ("bin", "Library/bin", "lib"):
        candidate = prefix / d / name
        if candidate.exists():
            return candidate
    matches = sorted(prefix.rglob(name))
    if matches:
        return matches[0]
    sys.exit(
        f"[check_libmf6] {name} not found anywhere under {prefix}; "
        "run `pixi run get-mf6 --force` to (re)install MODFLOW 6."
    )


def main() -> None:
    print(f"[check_libmf6] modflowapi {modflowapi.__version__}")
    prefix = conda_prefix()
    lib = find_libmf6(prefix)
    print(f"[check_libmf6] found {lib}")

    # On Windows the dependent PETSc/MPI DLLs live next to libmf6; make sure that
    # directory is on the DLL search path before loading.
    if sys.platform.startswith("win") and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(lib.parent))

    ctypes.CDLL(str(lib))
    print(f"[check_libmf6] OK: libmf6 loaded ({lib.name}).")


if __name__ == "__main__":
    main()
