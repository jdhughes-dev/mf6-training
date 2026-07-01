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

## 4. Contributing (pre-commit hook)

This repo uses a [pre-commit](https://pre-commit.com) hook that, on every
commit, **clears notebook outputs** (nbstripout) and applies **ruff** lint fixes
and formatting to Python files *and* notebooks. Install it once per clone:

```bash
pixi run pre-commit-install
```

The tools run from the pixi environment, so their versions match `pixi.lock`.
To run the hooks against every file (not just staged changes):

```bash
pixi run pre-commit-run
```

CI runs the same hooks on every push and pull request, so committing with the
hook installed keeps notebooks clean and code consistently formatted.

## Supported platforms

| Platform | pixi target |
|---|---|
| Windows 64-bit | `win-64` |
| Linux 64-bit | `linux-64` |
| macOS Apple Silicon | `osx-arm64` |
| macOS Intel | `osx-64` |

CI (GitHub Actions) installs the environment and verifies MODFLOW 6 (including
that modflowapi can load `libmf6`) and the Python packages on all four platforms
on every push and pull request, plus a nightly run.

## Notes

- The Windows MODFLOW 6 download is pinned to a specific
  [nightly build](https://github.com/MODFLOW-USGS/modflow6-nightly-build/releases)
  tag. Nightly releases are eventually deleted upstream; if `pixi run get-mf6`
  fails to download on Windows, update `NIGHTLY` in `scripts/get_mf6.py` to a
  current tag. (The nightly CI run flags this automatically.)
- If you see `WARN ignoring SSL_CERT_DIR: no certificates found` while running
  pixi, it is harmless and comes from another conda/pixi environment already
  being active in your shell. It does not appear in a fresh terminal.
