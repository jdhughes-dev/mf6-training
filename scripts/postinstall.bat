@echo off
REM Activation hook (Windows).

REM Point SSL_CERT_DIR at the dir that actually holds the conda cert bundle.
REM conda-forge's openssl otherwise sets it to an empty certs\ subdir, which
REM makes nested `pixi` calls inside the activated env warn
REM "ignoring SSL_CERT_DIR: no certificates found".
set "SSL_CERT_DIR=%CONDA_PREFIX%\Library\ssl"

REM On first activation, provision the tooling this env needs: download the
REM parallel (extended) MODFLOW 6, install mp7/gridgen/triangle via flopy's
REM get-modflow, and install the git pre-commit hook. All checks are idempotent
REM and never fail activation. Set MF6_SKIP_AUTOINSTALL to disable (CI runs the
REM get-mf6 / get-exes / pre-commit-install tasks explicitly instead).
if defined MF6_SKIP_AUTOINSTALL goto :eof
if not exist "%CONDA_PREFIX%\bin\mf6.exe" (
  python "%PIXI_PROJECT_ROOT%\scripts\get_mf6.py" || echo [get_mf6] WARNING: MODFLOW 6 setup failed; run "pixi run get-mf6" to retry. 1>&2
)
if not exist "%CONDA_PREFIX%\Scripts\mp7.exe" (
  python "%PIXI_PROJECT_ROOT%\scripts\get_exes.py" || echo [get-exes] WARNING: could not install mp7/gridgen/triangle; run "pixi run get-exes" to retry. 1>&2
)
REM Only in a git checkout, and only if the hook isn't installed yet.
if exist "%PIXI_PROJECT_ROOT%\.git\hooks\" if not exist "%PIXI_PROJECT_ROOT%\.git\hooks\pre-commit" (
  pushd "%PIXI_PROJECT_ROOT%"
  pre-commit install || echo [pre-commit] WARNING: could not install the pre-commit hook; run "pixi run pre-commit-install" to retry. 1>&2
  popd
)
