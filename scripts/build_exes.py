#!/usr/bin/env python
"""Build mp7, triangle, and gridgen from source (platforms without binaries).

USGS ships prebuilt mp7 / triangle / gridgen binaries only for win-64, linux-64,
and osx-arm64 (the MODFLOW-ORG/executables release). On the other supported
platforms - Intel macOS (osx-64) and linux-aarch64 - flopy's ``get-modflow`` has
nothing to download, so we clone each program from the MODFLOW-ORG GitHub
organization and build it with meson (every repo ships a meson.build with
``install: true``).

Like scripts/get_mf6.py does for mf6, each executable is installed into the
active pixi environment prefix - ``meson install --prefix=$CONDA_PREFIX`` places
it in ``$CONDA_PREFIX/bin`` - so it lands on PATH like any other env binary.

The MODFLOW-ORG repos build their release binaries with the GNU toolchain
(gcc/g++/gfortran), and triangle/mp7 rely on gcc-only compiler flags, so we
force CC/CXX/FC to GNU gcc and verify they are real GCC rather than an Apple
clang wrapper. (conda-forge only started shipping real GNU gcc/g++ on macOS in
Nov 2025; before that its mac `gcc` was a clang wrapper - hence the check.)

Normally invoked by scripts/get_exes.py, but can also be run directly inside the
pixi env. Idempotent: a program whose executable is already in the env is
skipped unless ``--force`` is given.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# exe name -> (git URL, branch to build). The exe name is what meson installs
# into <prefix>/bin and how we detect an existing install (matches the
# executable() name in each repo's meson.build).
PROGRAMS = {
    "mp7": ("https://github.com/MODFLOW-ORG/modpath-v7.git", "develop"),
    "triangle": ("https://github.com/MODFLOW-ORG/triangle.git", "main"),
    "gridgen": ("https://github.com/MODFLOW-ORG/gridgen.git", "main"),
}

# env var -> candidate binary names (plain name first, then versioned fallbacks).
GNU_COMPILERS = {
    "CC": ["gcc", "gcc-15", "gcc-14", "gcc-13"],
    "CXX": ["g++", "g++-15", "g++-14", "g++-13"],
    "FC": ["gfortran", "gfortran-15", "gfortran-14", "gfortran-13"],
}


def conda_prefix() -> Path:
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix:
        sys.exit(
            "CONDA_PREFIX is not set - run this inside the pixi environment "
            "(e.g. `pixi run get-exes`)."
        )
    return Path(prefix)


def project_root() -> Path:
    return Path(os.environ.get("PIXI_PROJECT_ROOT", os.getcwd()))


def repo_dir_name(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


def gnu_build_env() -> dict:
    """Return os.environ with CC/CXX/FC forced to real GNU gcc/g++/gfortran.

    Exits with a clear error if a compiler is missing or is actually Apple clang
    masquerading as gcc (the historical conda-forge macOS behavior).
    """
    env = dict(os.environ)
    for var, candidates in GNU_COMPILERS.items():
        exe = None
        for name in candidates:
            found = shutil.which(name)
            if found:
                exe = found
                break
        if not exe:
            sys.exit(
                f"[build-exes] no GNU compiler for {var} found on PATH (looked "
                f"for {candidates}). Is the pixi env active with gcc/gxx installed?"
            )
        version = subprocess.run(
            [exe, "--version"], capture_output=True, text=True
        ).stdout
        if "clang" in version.lower():
            first = version.splitlines()[0] if version else "?"
            sys.exit(
                f"[build-exes] {var}={exe} is Apple clang, not GNU gcc ({first}). "
                "Install real GNU gcc/gxx (conda-forge ships them on macOS since "
                "Nov 2025) and re-run."
            )
        env[var] = exe
    print(f"[build-exes] using CC={env['CC']} CXX={env['CXX']} FC={env['FC']}")
    return env


def build(
    exe: str, url: str, branch: str, prefix: Path, root: Path, env: dict, force: bool
) -> None:
    # Install into the env prefix; meson puts executables in <prefix>/bin.
    dst = prefix / "bin" / exe
    if not force and dst.exists():
        print(f"[build-exes] {exe} already installed in this environment; skipping.")
        return

    src = root / repo_dir_name(url)
    if not src.exists():
        print(f"[build-exes] cloning {url} ({branch})")
        subprocess.check_call(
            ["git", "clone", "--depth", "1", "--branch", branch, url, str(src)]
        )

    builddir = src / "builddir"
    if builddir.exists():
        shutil.rmtree(builddir)

    print(f"[build-exes] configuring {exe}")
    subprocess.check_call(
        ["meson", "setup", "builddir", "--buildtype=release", f"--prefix={prefix}"],
        cwd=src,
        env=env,
    )
    print(f"[build-exes] building and installing {exe}")
    subprocess.check_call(["meson", "install", "-C", "builddir"], cwd=src, env=env)
    print(f"[build-exes] installed {exe} -> {dst}")


def main() -> None:
    force = "--force" in sys.argv[1:]
    prefix = conda_prefix()
    root = project_root()
    env = gnu_build_env()
    for exe, (url, branch) in PROGRAMS.items():
        build(exe, url, branch, prefix, root, env, force)
    print("[build-exes] done.")


if __name__ == "__main__":
    main()
