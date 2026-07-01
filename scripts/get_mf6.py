#!/usr/bin/env python
"""Install the parallel (extended) MODFLOW 6 into the active pixi environment.

conda-forge does not ship a parallel-enabled mf6, so we provide it ourselves:

  * Windows : download the prebuilt extended nightly (win64ext.zip) and copy
              the binaries into the environment.
  * Unix    : build from source with PETSc/MPI via Meson (-Dextended=true).

The script is idempotent: if an ``mf6`` executable is already on PATH it does
nothing. Pass ``--force`` to rebuild/reinstall anyway.

It is meant to be run inside the pixi environment (so CONDA_PREFIX, the compilers
and meson are available), either via ``pixi run get-mf6`` or automatically from
the activation hook in pixi.toml.
"""

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlretrieve

# Nightly tag that ships the win64ext.zip (extended) asset. Update from
# https://github.com/MODFLOW-USGS/modflow6-nightly-build/releases as needed.
NIGHTLY = "20260625"
MF6_REPO = "https://github.com/MODFLOW-USGS/modflow6.git"


def conda_prefix() -> Path:
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix:
        sys.exit(
            "CONDA_PREFIX is not set - run this inside the pixi environment "
            "(e.g. `pixi run get-mf6`)."
        )
    return Path(prefix)


def project_root() -> Path:
    return Path(os.environ.get("PIXI_PROJECT_ROOT", os.getcwd()))


def mf6_in_env(prefix: Path) -> bool:
    """True if mf6 is installed in THIS env (not merely somewhere on PATH)."""
    exe = "mf6.exe" if sys.platform.startswith("win") else "mf6"
    return any((prefix / d / exe).exists() for d in ("bin", "Library/bin"))


def install_windows(prefix: Path, root: Path) -> None:
    url = (
        f"https://github.com/MODFLOW-USGS/modflow6-nightly-build/releases/"
        f"download/{NIGHTLY}/win64ext.zip"
    )
    zip_path = root / "win64ext.zip"
    extract_dir = root / "win64ext"
    print(f"[get_mf6] downloading {url}")
    urlretrieve(url, zip_path)
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    shutil.unpack_archive(str(zip_path), str(extract_dir))
    bins = glob.glob(str(extract_dir / "**" / "bin"), recursive=True)
    src = bins[0] if bins else str(extract_dir)
    dst = prefix / "bin"  # on PATH inside the pixi env on Windows
    print(f"[get_mf6] copying {src} -> {dst}")
    shutil.copytree(src, dst, dirs_exist_ok=True)
    # tidy up the (large) download artifacts
    zip_path.unlink(missing_ok=True)
    shutil.rmtree(extract_dir, ignore_errors=True)


def install_unix(prefix: Path, root: Path) -> None:
    src = root / "modflow6"
    if not src.exists():
        print(f"[get_mf6] cloning {MF6_REPO}")
        subprocess.check_call(["git", "clone", MF6_REPO, str(src)])

    env = dict(os.environ)
    env["PKG_CONFIG_PATH"] = str(prefix / "lib" / "pkgconfig")

    # Some conda-forge netcdf-fortran builds ship an empty `fmoddir=` in their
    # pkg-config file; populate it (via nf-config) so meson can find the Fortran
    # modules. Idempotent: a no-op if it is already set.
    pc_fix = Path(__file__).resolve().parent / "update_pc_files.py"
    print("[get_mf6] checking netcdf-fortran pkg-config (fmoddir)")
    subprocess.check_call([sys.executable, str(pc_fix)], env=env)

    builddir = src / "builddir"
    if builddir.exists():
        shutil.rmtree(builddir)

    print("[get_mf6] configuring MODFLOW 6 (extended build)")
    subprocess.check_call(
        [
            "meson",
            "setup",
            "builddir",
            "-Ddebug=false",
            "-Dextended=true",
            f"--prefix={prefix}",
        ],
        cwd=src,
        env=env,
    )
    print("[get_mf6] building and installing MODFLOW 6")
    subprocess.check_call(["meson", "install", "-C", "builddir"], cwd=src, env=env)


def main() -> None:
    force = "--force" in sys.argv[1:]
    prefix = conda_prefix()
    root = project_root()

    if not force and mf6_in_env(prefix):
        print(
            "[get_mf6] mf6 already installed in this environment; nothing to do "
            "(use --force to reinstall)."
        )
        return

    os.chdir(root)

    if sys.platform.startswith("win"):
        install_windows(prefix, root)
    else:
        install_unix(prefix, root)

    print("[get_mf6] parallel (extended) MODFLOW 6 installed.")


if __name__ == "__main__":
    main()
