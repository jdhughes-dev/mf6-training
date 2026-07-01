#!/usr/bin/env python
"""Verify the extra MODFLOW-family executables are installed on PATH.

Checks that mp7, triangle, and gridgen (installed by the get-exes task - either
via flopy's get-modflow or built from source; see scripts/get_exes.py) are found
on PATH in the active pixi environment. Prints where each resolved and exits
non-zero listing any that are missing. Run inside the pixi env, e.g.
`pixi run check-exes`.
"""

import shutil
import sys

EXES = ("mp7", "triangle", "gridgen")


def main() -> None:
    found = {exe: shutil.which(exe) for exe in EXES}
    for exe, path in found.items():
        print(f"[check-exes] {exe}: {path or 'NOT FOUND'}")
    missing = [exe for exe, path in found.items() if not path]
    if missing:
        sys.exit(
            f"[check-exes] missing executables: {', '.join(missing)}; "
            "run `pixi run get-exes` (add --force to rebuild) to install them."
        )
    print("[check-exes] OK: all executables found.")


if __name__ == "__main__":
    main()
