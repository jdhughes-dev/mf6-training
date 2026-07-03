"""Shared helper functions for the example notebooks.

Keeping this boilerplate in one place lets each notebook import what it needs
instead of repeating the same setup cells. Add other generic, notebook-agnostic
helpers here as more notebooks need them.
"""

import os
import pathlib as pl
import platform


def find_in_env(filename, env_path=None):
    """Return the path to ``filename`` inside the active pixi/conda environment.

    Checks the usual bin/lib locations first, then falls back to a recursive
    search (meson installs the Linux ``.so`` under a multiarch subdirectory such
    as ``lib/x86_64-linux-gnu`` that a fixed list would miss).

    Parameters
    ----------
    filename : str
        File to locate, e.g. ``"mf6"`` or ``"libmf6.dll"``.
    env_path : path-like, optional
        Environment prefix to search; defaults to ``$CONDA_PREFIX``.

    Returns
    -------
    pathlib.Path
    """
    if env_path is None:
        prefix = os.environ.get("CONDA_PREFIX", None)
        assert prefix is not None, "Notebook must be run from the pixi environment"
        env_path = pl.Path(prefix)
    env_path = pl.Path(env_path)

    # get_mf6.py installs mf6 into different subdirectories depending on platform
    # (bin on Windows; bin plus lib on Unix).
    search_dirs = ["bin", "lib", "Scripts", "Library/bin"]
    for d in search_dirs:
        candidate = env_path / d / filename
        if candidate.is_file():
            return candidate
    matches = sorted(env_path.rglob(filename))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"Could not find {filename} under {env_path} "
        f"(looked in {', '.join(search_dirs)} and recursively)"
    )


def find_mf6_libraries(env_path=None):
    """Locate the MODFLOW 6 shared library and executable in the active env.

    The API drives MODFLOW 6 through its compiled shared library (``libmf6``),
    not the ``mf6`` command-line executable, so both are returned. The file
    extensions differ by platform (``.so`` on Linux, ``.dylib`` on macOS,
    ``.dll`` on Windows).

    Returns
    -------
    (lib_name, mf6_exe) : tuple of pathlib.Path
        Paths to ``libmf6`` and ``mf6``.
    """
    system = platform.platform().lower()
    if "linux" in system:
        lib_ext, exe_ext = ".so", ""
    elif "darwin" in system or "macos" in system:
        lib_ext, exe_ext = ".dylib", ""
    else:
        lib_ext, exe_ext = ".dll", ".exe"

    lib_name = find_in_env(f"libmf6{lib_ext}", env_path=env_path)
    mf6_exe = find_in_env(f"mf6{exe_ext}", env_path=env_path)
    return lib_name, mf6_exe
