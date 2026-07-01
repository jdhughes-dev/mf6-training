#!/usr/bin/env bash
# Activation hook (Unix).

# Point SSL_CERT_DIR at the dir that actually holds the conda cert bundle.
# conda-forge's openssl otherwise sets it to an empty `certs/` subdir, which
# makes nested `pixi` calls inside the activated env warn
# `ignoring SSL_CERT_DIR: no certificates found`.
export SSL_CERT_DIR="${CONDA_PREFIX}/ssl"

# conda-forge's GNU gcc/g++ on macOS need the macOS SDK to find system headers.
# Point SDKROOT at the active SDK if the env hasn't set it already.
if [ "$(uname)" = "Darwin" ] && [ -z "${SDKROOT:-}" ]; then
  SDKROOT="$(xcrun --show-sdk-path 2>/dev/null)" && export SDKROOT
fi

# On first activation, provision the tooling this env needs:
#   * build the parallel (extended) MODFLOW 6,
#   * install mp7/gridgen/triangle via flopy's get-modflow, and
#   * install the git pre-commit hook.
# All checks are idempotent (skipped once already done) and never fail
# activation. Set MF6_SKIP_AUTOINSTALL to disable (CI does this and runs the
# `get-mf6` / `get-exes` / `pre-commit-install` tasks explicitly instead).
if [ -z "${MF6_SKIP_AUTOINSTALL:-}" ]; then
  if [ ! -x "${CONDA_PREFIX}/bin/mf6" ]; then
    python "${PIXI_PROJECT_ROOT}/scripts/get_mf6.py" || \
      echo "[get_mf6] WARNING: MODFLOW 6 setup failed; run 'pixi run get-mf6' to retry." >&2
  fi
  if [ ! -x "${CONDA_PREFIX}/bin/mp7" ]; then
    python "${PIXI_PROJECT_ROOT}/scripts/get_exes.py" || \
      echo "[get-exes] WARNING: could not install mp7/gridgen/triangle; run 'pixi run get-exes' to retry." >&2
  fi
  # Only in a git checkout, and only if the hook isn't installed yet.
  if [ -d "${PIXI_PROJECT_ROOT}/.git/hooks" ] && [ ! -f "${PIXI_PROJECT_ROOT}/.git/hooks/pre-commit" ]; then
    ( cd "${PIXI_PROJECT_ROOT}" && pre-commit install ) || \
      echo "[pre-commit] WARNING: could not install the pre-commit hook; run 'pixi run pre-commit-install' to retry." >&2
  fi
fi
