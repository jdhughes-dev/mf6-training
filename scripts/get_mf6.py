#!/usr/bin/env python
"""Install the parallel (extended) MODFLOW 6 into the active pixi environment.

conda-forge does not ship a parallel-enabled mf6, so we provide it ourselves:

  * Windows : download the prebuilt extended nightly (win64ext.zip) and copy
              the binaries into the environment.
  * Unix    : build from source with PETSc/MPI via Meson (-Dextended=true).

The script is idempotent: an ``mf6`` already installed in the environment is
left alone, and flopy's MODFLOW 6 input classes are regenerated only when they
no longer match it. Pass ``--force`` to rebuild/reinstall and resync anyway, and
``--quiet`` (used by the activation hook) to say nothing when there is nothing
to do.

It is meant to be run inside the pixi environment (so CONDA_PREFIX, the compilers
and meson are available), either via ``pixi run get-mf6`` or automatically from
the activation hook in pixi.toml.
"""

import glob
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlretrieve

# Source of the win64ext.zip (extended) asset. The newest nightly is resolved at
# download time through the /releases/latest redirect, which needs no API call
# and so is not subject to the GitHub API rate limit. NIGHTLY is only a fallback
# for when that request fails; upstream deletes nightly releases after about a
# month, so a pinned tag goes stale on its own.
NIGHTLY_REPO = "https://github.com/MODFLOW-ORG/modflow6-nightly-build"
NIGHTLY = "20260730"
MF6_REPO = "https://github.com/MODFLOW-ORG/modflow6.git"

# flopy's MODFLOW 6 input classes are generated from the modflow6 definition
# (DFN) files of the commit the installed mf6 was built from, so they match the
# mf6 that will consume them. `mf6 -v` reports that commit as `<version>+<sha>`
# for both the extended nightly and the from-source build. The local clone
# supplies the DFNs while it sits on that commit (exact, and no network);
# otherwise they are fetched from GitHub at that commit. MF6_DFN_REF is the
# fallback for a build that reports no commit.
MF6_DFN_SUBPATH = Path("doc") / "mf6io" / "mf6ivar" / "dfn"
MF6_DFN_REF = "develop"

# Records the modflow6 commit flopy's classes were generated from. It lives in
# the flopy package so that reinstalling flopy - which puts back the classes
# flopy ships, which lack the packages the installed mf6 supports - takes the
# stamp with it and the next run regenerates.
STAMP_NAME = ".mf6-dfn-sync"


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


def mf6_path(prefix: Path) -> Path | None:
    """Path to the mf6 installed in THIS env (not merely somewhere on PATH)."""
    exe = "mf6.exe" if sys.platform.startswith("win") else "mf6"
    for d in ("bin", "Library/bin"):
        path = prefix / d / exe
        if path.exists():
            return path
    return None


def mf6_commit(exe: Path) -> str | None:
    """The modflow6 commit the installed mf6 was built from, from ``mf6 -v``."""
    try:
        out = subprocess.check_output([str(exe), "-v"], text=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    # a development build reports `mf6: <version>+<sha>`; a release build has no sha
    _, _, sha = out.strip().partition("+")
    return sha or None


def clone_commit(clone: Path) -> str:
    """HEAD of the modflow6 clone, or an empty string if there is no clone."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(clone), "rev-parse", "HEAD"], text=True
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    return out.strip()


def stamp_path() -> Path:
    """The DFN sync stamp inside the installed flopy package."""
    return Path(sysconfig.get_paths()["purelib"]) / "flopy" / STAMP_NAME


def download_win64ext(dest: Path) -> None:
    """Download the extended nightly zip: newest release, then the pinned tag."""
    urls = (
        f"{NIGHTLY_REPO}/releases/latest/download/win64ext.zip",
        f"{NIGHTLY_REPO}/releases/download/{NIGHTLY}/win64ext.zip",
    )
    for url in urls:
        print(f"[get_mf6] downloading {url}")
        try:
            urlretrieve(url, dest)
            return
        except URLError as err:
            print(f"[get_mf6] download failed: {err}")
    sys.exit(
        f"[get_mf6] could not download win64ext.zip from the newest nightly or "
        f"the pinned tag {NIGHTLY} - update NIGHTLY in scripts/get_mf6.py."
    )


def install_windows(prefix: Path, root: Path) -> None:
    zip_path = root / "win64ext.zip"
    extract_dir = root / "win64ext"
    download_win64ext(zip_path)
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


def clone_mf6_source(root: Path) -> Path:
    """Clone the modflow6 repo (once); the extended build compiles from it."""
    src = root / "modflow6"
    if not src.exists():
        print(f"[get_mf6] cloning {MF6_REPO}")
        subprocess.check_call(["git", "clone", MF6_REPO, str(src)])
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


def update_flopy_classes(
    root: Path, commit: str | None, force: bool = False, quiet: bool = False
) -> None:
    """Regenerate flopy's MODFLOW 6 input classes from the DFNs of the installed mf6.

    ``commit`` is the modflow6 commit ``mf6 -v`` reports. Returns early when the
    classes already record it. Requires ``modflow-devtools[dfn]`` (declared in
    pixi.toml). A failure here is fatal: flopy would keep the classes it shipped
    with, which silently lack the packages the installed mf6 supports.
    """
    stamp = stamp_path()
    want = commit or MF6_DFN_REF
    if not force and stamp.is_file() and stamp.read_text().strip() == want:
        if not quiet:
            print(f"[get_mf6] flopy MODFLOW 6 classes already match modflow6 {want}")
        return

    clone = root / "modflow6"
    dfnpath = clone / MF6_DFN_SUBPATH
    # the clone is an exact DFN source (and needs no network) only while it sits
    # on the commit the installed mf6 was built from
    if dfnpath.is_dir() and (commit is None or clone_commit(clone).startswith(commit)):
        source = ["--dfnpath", str(dfnpath)]
        print(f"[get_mf6] syncing flopy MODFLOW 6 classes from {dfnpath}")
    else:
        source = ["--ref", want]
        print(f"[get_mf6] syncing flopy MODFLOW 6 classes from modflow6 {want}")
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
        sys.exit(
            f"[get_mf6] could not update flopy classes ({exc}). flopy would keep "
            "the classes it shipped with, which silently lack the packages the "
            "installed mf6 supports. Retry with `pixi run get-mf6` once the "
            "network and dependencies are available."
        )
    stamp.write_text(f"{want}\n")


def main() -> None:
    args = sys.argv[1:]
    force = "--force" in args
    quiet = "--quiet" in args
    prefix = conda_prefix()
    root = project_root()
    os.chdir(root)

    if force or mf6_path(prefix) is None:
        if sys.platform.startswith("win"):
            install_windows(prefix, root)
        else:
            install_unix(prefix, root)
        print("[get_mf6] parallel (extended) MODFLOW 6 installed.")
    elif not quiet:
        print(
            "[get_mf6] mf6 already installed in this environment "
            "(use --force to reinstall)."
        )

    exe = mf6_path(prefix)
    if exe is None:
        sys.exit("[get_mf6] mf6 was not installed into the environment.")

    # keep flopy's MODFLOW 6 input classes in sync with the installed mf6
    update_flopy_classes(root, mf6_commit(exe), force=force, quiet=quiet)


if __name__ == "__main__":
    main()
