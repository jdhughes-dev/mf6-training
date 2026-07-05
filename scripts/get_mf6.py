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

# After installing mf6, flopy's MODFLOW 6 input classes are regenerated from the
# modflow6 definition (DFN) files so they match the mf6 that will consume them.
# We prefer the DFNs in the local modflow6 clone (an exact match to the build);
# MF6_DFN_SUBPATH is where they live inside the clone. If no clone is present we
# fall back to fetching MF6_DFN_REF ("develop") from GitHub. Both the extended
# nightly and the from-source build track modflow6 develop.
MF6_DFN_SUBPATH = Path("doc") / "mf6io" / "mf6ivar" / "dfn"
MF6_DFN_REF = "develop"


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


def clone_mf6_source(root: Path, shallow: bool = False) -> Path:
    """Clone the modflow6 repo (once) so its DFN files are available locally.

    Returns the clone directory. On Unix this is the same tree the extended
    build compiles from; on Windows it is cloned only for its DFN files, so a
    shallow clone is enough there.
    """
    src = root / "modflow6"
    if not src.exists():
        cmd = ["git", "clone"]
        if shallow:
            cmd += ["--depth", "1"]
        cmd += [MF6_REPO, str(src)]
        print(f"[get_mf6] cloning {MF6_REPO}{' (shallow)' if shallow else ''}")
        subprocess.check_call(cmd)
    return src


def install_unix(prefix: Path, root: Path) -> None:
    src = clone_mf6_source(root)

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


def update_flopy_classes(dfnpath: Path) -> None:
    """Regenerate flopy's MODFLOW 6 input classes from the matching mf6 DFNs.

    Run after mf6 is (re)installed so flopy's ``ModflowGwf...``/``ModflowPrt...``
    classes match the mf6 that will actually consume their input. Prefers the
    DFNs in the local modflow6 clone (``dfnpath``) for an exact match; if that
    path is missing, falls back to fetching ``MF6_DFN_REF`` from GitHub.
    Requires ``modflow-devtools[dfn]`` (declared in pixi.toml). Best-effort: a
    failure here (e.g. no network) warns but does not fail the mf6 install, so
    it is safe to call from the activation hook.
    """
    if dfnpath.is_dir():
        source = ["--dfnpath", str(dfnpath)]
        print(f"[get_mf6] syncing flopy MODFLOW 6 classes from {dfnpath}")
    else:
        source = ["--ref", MF6_DFN_REF]
        print(
            f"[get_mf6] {dfnpath} not found; syncing flopy MODFLOW 6 classes "
            f"from modflow6 '{MF6_DFN_REF}' DFNs"
        )
    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "flopy.mf6.utils.generate_classes",
                *source,
                "--no-backup",
                "--no-verbose",
            ]
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        print(
            f"[get_mf6] WARNING: could not update flopy classes ({exc}). "
            "Run `pixi run python -m flopy.mf6.utils.generate_classes "
            f"--dfnpath {dfnpath}` manually once network/deps are available."
        )


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
        # Windows uses a prebuilt binary, so clone modflow6 only for its DFNs.
        src = clone_mf6_source(root, shallow=True)
    else:
        install_unix(prefix, root)
        src = root / "modflow6"

    print("[get_mf6] parallel (extended) MODFLOW 6 installed.")

    # keep flopy's MODFLOW 6 input classes in sync with the mf6 just installed
    update_flopy_classes(src / MF6_DFN_SUBPATH)


if __name__ == "__main__":
    main()
