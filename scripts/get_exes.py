#!/usr/bin/env python
"""Install the extra MODFLOW-family executables: mp7, gridgen, triangle.

These are needed by the notebooks but are not provided by mf6 itself:
  * mp7      - MODPATH 7 (particle tracking)
  * triangle - triangular mesh generation (unstructured grids)
  * gridgen  - quadtree grid generation (unstructured grids)

USGS ships prebuilt binaries only for win-64, linux-64, and osx-arm64 (the
MODFLOW-ORG/executables release), installed here via flopy's ``get-modflow``. On
the other supported platforms - Intel macOS (osx-64) and linux-aarch64 - there
are no prebuilt binaries, so they are built from source instead (this script
delegates to scripts/build_exes.py).

This is the "main" executables task run inside the pixi env via
``pixi run get-exes`` (and from the activation hook). Pass ``--force`` to rebuild
the source-built executables.
"""

import platform
import subprocess
import sys
from pathlib import Path


def needs_source_build() -> bool:
    """True on supported platforms USGS ships no prebuilt binaries for."""
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in ("x86_64", "amd64"):
        return True  # Intel macOS (osx-64)
    if sys.platform.startswith("linux") and machine in ("aarch64", "arm64"):
        return True  # linux-aarch64
    return False


def main() -> None:
    args = sys.argv[1:]
    if needs_source_build():
        # No prebuilt binaries for this platform; build from the MODFLOW-ORG
        # repos. --force (if given) is forwarded to rebuild even when present.
        script = Path(__file__).resolve().parent / "build_exes.py"
        subprocess.check_call([sys.executable, str(script), *args])
    else:
        subprocess.check_call(
            ["get-modflow", "--subset", "mp7,gridgen,triangle", ":python"]
        )


if __name__ == "__main__":
    main()
