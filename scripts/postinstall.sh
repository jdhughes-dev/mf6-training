#!/usr/bin/env bash
# Activation hook (Unix).

# Point SSL_CERT_DIR at the dir that actually holds the conda cert bundle.
# conda-forge's openssl otherwise sets it to an empty `certs/` subdir, which
# makes nested `pixi` calls inside the activated env warn
# `ignoring SSL_CERT_DIR: no certificates found`.
export SSL_CERT_DIR="${CONDA_PREFIX}/ssl"

# On first activation, provision the MODFLOW tooling this env needs:
#   * build the parallel (extended) MODFLOW 6, and
#   * install mp7/gridgen/triangle via flopy's get-modflow.
# Both checks are idempotent (skipped once the binary is in this env) and never
# fail activation. Set MF6_SKIP_AUTOINSTALL to disable (CI does this and runs
# the `get-mf6` / `get-exes` tasks explicitly instead).
if [ -z "${MF6_SKIP_AUTOINSTALL:-}" ]; then
  if [ ! -x "${CONDA_PREFIX}/bin/mf6" ]; then
    python "${PIXI_PROJECT_ROOT}/scripts/get_mf6.py" || \
      echo "[get_mf6] WARNING: MODFLOW 6 setup failed; run 'pixi run get-mf6' to retry." >&2
  fi
  if [ ! -x "${CONDA_PREFIX}/bin/mp7" ]; then
    get-modflow --subset mp7,gridgen,triangle :python || \
      echo "[get-exes] WARNING: could not install mp7/gridgen/triangle; run 'pixi run get-exes' to retry." >&2
  fi
fi
