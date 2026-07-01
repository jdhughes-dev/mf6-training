@echo off
REM Activation hook (Windows).

REM Point SSL_CERT_DIR at the dir that actually holds the conda cert bundle.
REM conda-forge's openssl otherwise sets it to an empty certs\ subdir, which
REM makes nested `pixi` calls inside the activated env warn
REM "ignoring SSL_CERT_DIR: no certificates found".
set "SSL_CERT_DIR=%CONDA_PREFIX%\Library\ssl"

REM On first activation, provision the MODFLOW tooling this env needs: download
REM the parallel (extended) MODFLOW 6, and install mp7/gridgen/triangle via
REM flopy's get-modflow. Both checks are idempotent and never fail activation.
REM Set MF6_SKIP_AUTOINSTALL to disable (CI runs the get-mf6 / get-exes tasks
REM explicitly instead).
if defined MF6_SKIP_AUTOINSTALL goto :eof
if not exist "%CONDA_PREFIX%\bin\mf6.exe" (
  python "%PIXI_PROJECT_ROOT%\scripts\get_mf6.py" || echo [get_mf6] WARNING: MODFLOW 6 setup failed; run "pixi run get-mf6" to retry. 1>&2
)
if not exist "%CONDA_PREFIX%\Scripts\mp7.exe" (
  get-modflow --subset mp7,gridgen,triangle :python || echo [get-exes] WARNING: could not install mp7/gridgen/triangle; run "pixi run get-exes" to retry. 1>&2
)
