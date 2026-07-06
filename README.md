# MODFLOW 6 training

[![CI](https://github.com/jdhughes-dev/mf6-training/actions/workflows/ci.yml/badge.svg)](https://github.com/jdhughes-dev/mf6-training/actions/workflows/ci.yml)

Training materials (notebooks and scripts) for MODFLOW 6 classes, with a
reproducible [pixi](https://pixi.sh) environment. It provides the scientific
Python stack (flopy, modflowapi, pandas, numpy, scipy, matplotlib, …) for
building, running, and analyzing MODFLOW 6 models in notebooks or scripts, plus
a **parallel (extended) build of MODFLOW 6** (including the `libmf6` shared
library that modflowapi drives) across Windows, Linux, and macOS (Apple Silicon
and Intel).

## 1. Install pixi

You only need to do this once per machine.

> **Requires pixi ≥ 0.71.2.** This repo uses the newer manifest syntax
> (per-platform virtual packages) and lockfile format (v7); older pixi versions
> cannot read them.

**Already have pixi?** Check your version and update if it is older than 0.71.2:

```bash
pixi --version
pixi self-update          # if installed via the official installer
```

If you installed pixi through a package manager, update it the same way:
`winget upgrade prefix-dev.pixi` (Windows) or `brew upgrade pixi` (macOS).
If you don't have pixi yet, install it below.

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -c "irm -useb https://pixi.sh/install.ps1 | iex"
```

Or with a package manager:

```powershell
winget install prefix-dev.pixi
```

### macOS

```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

Or with Homebrew:

```bash
brew install pixi
```

### Linux

```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

After installing, **open a new terminal** so that `pixi` is on your `PATH`.
Verify with (should report 0.71.2 or newer):

```bash
pixi --version
```

## 2. Install the environment

Clone the repository and install the locked environment from `pixi.lock`:

```bash
git clone https://github.com/jdhughes-dev/mf6-training.git
cd mf6-training
pixi install
```

`pixi install` creates a self-contained environment under `.pixi/` using the
exact versions pinned in `pixi.lock`. Nothing is installed globally and your
system Python is untouched.

### Parallel MODFLOW 6

A parallel (extended) MODFLOW 6 is **installed automatically the first time you
activate the environment** (the first `pixi run …` or `pixi shell`):

- **Windows** — the prebuilt extended nightly is downloaded and copied into the
  environment.
- **Linux / macOS** — MODFLOW 6 is built from source with PETSc/MPI (this first
  build takes a few minutes; later activations are instant).

You can also trigger it explicitly (idempotent; `--force` rebuilds):

```bash
pixi run get-mf6
```

## 3. Use the environment

Launch JupyterLab:

```bash
pixi run jupyter
```

### The training notebooks

The hands-on material lives in
[`examples/notebooks/`](examples/notebooks/). See its
[**README**](examples/notebooks/README.md) for an introduction, how to run the
notebooks, and a table of every notebook with a short description of the MODFLOW 6
capability it demonstrates — building models with FloPy, driving MODFLOW 6 through
its API, the advanced packages (UZF, MAW, SFR, LAK, MVR), solute and heat
transport, variable-density flow, particle tracking, XT3D, unstructured-grid
generation, local grid refinement, and parallel runs.

Open the project in VS Code:

```bash
pixi run vscode
```

Drop into a shell with the environment activated (so `python`, `mf6`,
`mp7`, etc. are all on `PATH`):

```bash
pixi shell
```

Run a one-off command in the environment without activating a shell:

```bash
pixi run python -c "import flopy, modflowapi; print(flopy.__version__)"
pixi run mf6 -v
```

## 4. Contributing

If you plan to commit changes, install the pre-commit hook that clears notebook
outputs (nbstripout), fixes spelling (codespell), and applies ruff lint fixes
and formatting. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Supported platforms

| Platform | pixi target |
|---|---|
| Windows 64-bit | `win-64` |
| Linux 64-bit | `linux-64` |
| Linux ARM64 | `linux-aarch64` |
| macOS Apple Silicon | `osx-arm64` |
| macOS Intel | `osx-64` |

CI (GitHub Actions) installs the environment and verifies MODFLOW 6 (including
that modflowapi can load `libmf6`) and the Python packages on all five platforms
on every push and pull request, plus a nightly run. (linux-aarch64 uses the free
arm64 hosted runners available for public repositories.)

## Notes

- The Windows MODFLOW 6 download is pinned to a specific
  [nightly build](https://github.com/MODFLOW-USGS/modflow6-nightly-build/releases)
  tag. Nightly releases are eventually deleted upstream; if `pixi run get-mf6`
  fails to download on Windows, update `NIGHTLY` in `scripts/get_mf6.py` to a
  current tag. (The nightly CI run flags this automatically.)
- On the platforms USGS ships no prebuilt binaries for - **Intel macs (osx-64)**
  and **linux-aarch64** - the mp7 / triangle / gridgen executables are built from
  source (cloned from the [MODFLOW-ORG](https://github.com/MODFLOW-ORG) GitHub
  org and compiled with meson); every other platform gets prebuilt binaries via
  flopy's `get-modflow`. Either way it is automatic (`pixi run get-exes`) and the
  executables install into the environment like mf6.
- All from-source builds (mf6, and the executables above where applicable) use a
  single GNU toolchain (gcc/g++/gfortran), matching how MODFLOW-ORG builds its
  release binaries. Note that conda-forge only began shipping real GNU gcc/g++ on
  macOS in Nov 2025 (its mac `gcc` was previously a clang wrapper), currently
  gcc 15 only, so the gcc version may differ across platforms.
- If you see `WARN ignoring SSL_CERT_DIR: no certificates found` while running
  pixi, it is harmless and comes from another conda/pixi environment already
  being active in your shell. It does not appear in a fresh terminal.
