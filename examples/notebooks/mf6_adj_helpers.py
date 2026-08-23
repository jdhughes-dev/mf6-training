"""Shared setup for the adjoint-sensitivity (mf6adj) notebooks.

Both adjoint notebooks start from a synthetic-valley model, run it, and then
drive mf6adj over the result. The workspace preparation, the adjoint input file,
and the sensitivity readers are collected here so the notebooks stay focused on
the sensitivity analysis itself.
"""

import pathlib as pl
import shutil

import flopy
import h5py
import numpy as np
import pandas as pd

# The MAW package adds an equation per well to the MODFLOW 6 solution matrix.
# mf6adj rebuilds the adjoint matrix from the groundwater-flow grid connectivity
# alone, so it cannot use that matrix; the advanced model ships the equivalent
# WEL cells, which carry the same rates split across layers 4 and 5.
MAW_PACKAGE_LINE = "maw6  sv.maw  pwell"
WEL_PACKAGE_LINE = "wel6  sv.pwell.wel  pwell"

DATA_ROOT = pl.Path("../data/synthetic-valley")
MODEL_ROOT = pl.Path("models")


def prepare_model(
    workspace,
    variant="advanced",
    sample_frequency="annual",
    prediction_rate=None,
    pumping=True,
    outer_dvclose=None,
):
    """Copy a synthetic-valley model into models/ and return its workspace.

    Parameters
    ----------
    workspace : str
        Directory name under ``models/``.
    variant : str
        ``"advanced"`` (SFR, LAK, UZF, MVR) or ``"base"`` (RIV, RCH, EVT).
    sample_frequency : str
        ``"annual"`` or ``"monthly"``.
    prediction_rate : float, optional
        Rate for the prediction well; the shipped rate is kept when None.
    pumping : bool
        When False, blank the production-well rates.
    outer_dvclose : float, optional
        Tighten the outer convergence criterion.

    Returns
    -------
    pathlib.Path
        The prepared workspace.
    """
    src = DATA_ROOT / f"synthetic-valley-{variant}-{sample_frequency}"
    ws = MODEL_ROOT / workspace
    if ws.exists():
        shutil.rmtree(ws)
    ws.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, ws)

    if variant == "advanced":
        nam = (ws / "sv.nam").read_text()
        (ws / "sv.nam").write_text(nam.replace(MAW_PACKAGE_LINE, WEL_PACKAGE_LINE))

    if prediction_rate is not None:
        _set_well_rate(ws / "sv.prediction.well", prediction_rate)
    if not pumping:
        _blank_periods(ws / "sv.pwell.wel")
        _blank_periods(ws / "sv.prediction.well")
    if outer_dvclose is not None:
        ims = (ws / "sv.ims").read_text()
        (ws / "sv.ims").write_text(
            ims.replace(
                "OUTER_DVCLOSE  1.00000000E-05",
                f"OUTER_DVCLOSE  {outer_dvclose:.8E}",
            )
        )
    return ws


def _set_well_rate(path, rate):
    """Replace every rate in a single-well WEL file."""
    lines = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0].isdigit():
            lines.append(f"  {parts[0]} {parts[1]} {parts[2]} {rate:.8E}")
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n")


def _blank_periods(path):
    """Drop every stress-period entry from a WEL file, leaving the wells idle."""
    keep, inside = [], False
    for line in path.read_text().splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("begin period"):
            inside = True
            keep.append(line)
            continue
        if stripped.startswith("end period"):
            inside = False
        if not inside:
            keep.append(line)
    path.write_text("\n".join(keep) + "\n")


def run_model(ws, mf6_exe, silent=True):
    """Run MODFLOW 6 in ``ws`` and raise if it does not converge."""
    success, buff = flopy.run_model(
        exe_name=str(mf6_exe), namefile=None, model_ws=str(ws), silent=silent
    )
    if not success:
        raise RuntimeError(f"MODFLOW 6 failed in {ws}:\n" + "\n".join(buff[-20:]))
    return success


def write_adj_file(ws, filename, measures):
    """Write an mf6adj performance-measure file.

    Parameters
    ----------
    ws : path-like
        Model workspace.
    filename : str
        Name of the adjoint file to write in ``ws``.
    measures : dict
        Measure name mapped to a list of ``(kper, kstp, k, i, j, pm_type)``
        tuples, all zero-based except the package name.

    Returns
    -------
    pathlib.Path
        The file that was written.
    """
    path = pl.Path(ws) / filename
    with open(path, "w") as f:
        for name, entries in measures.items():
            f.write(f"begin performance_measure {name}\n")
            for kper, kstp, k, i, j, pm_type in entries:
                # the adjoint file is one-based
                f.write(
                    f"{kper + 1} {kstp + 1} {k + 1} {i + 1} {j + 1} "
                    f"{pm_type} direct 1.0 -1.0e+30\n"
                )
            f.write("end performance_measure\n\n")
    return path


def package_cells(gwf, package):
    """Return the zero-based (layer, row, column) cells a package occupies."""
    pkg = gwf.get_package(package)
    if package.lower().startswith("lak"):
        records = pkg.connectiondata.array
    elif package.lower().startswith("sfr"):
        records = pkg.packagedata.array
    else:
        # a list package can start in any stress period, so take the first
        # period that has entries
        records = None
        for period in sorted(pkg.stress_period_data.get_data()):
            records = pkg.stress_period_data.get_data(period)
            if records is not None and len(records):
                break
    cells = pd.DataFrame.from_records(records).cellid.values
    return [tuple(cellid) for cellid in cells]


def period_sensitivity(ws, measure, parameter):
    """Return per-stress-period sensitivity arrays for one measure.

    Returns
    -------
    dict
        Zero-based stress period mapped to the sensitivity array.
    """
    path = pl.Path(ws) / f"adjoint_solution_{measure}.hd5"
    out = {}
    with h5py.File(path, "r") as hf:
        for key in hf:
            if not key.startswith("solution_"):
                continue
            kper = int(key.split("kper:")[1].split("_")[0])
            out[kper] = hf[key][parameter][:]
    return out


def composite_sensitivity(ws, measure, parameter):
    """Return the composite (all-times) sensitivity array for one measure."""
    path = pl.Path(ws) / f"adjoint_solution_{measure}.hd5"
    with h5py.File(path, "r") as hf:
        return hf["composite"][parameter][:]


def total_sensitivity(ws, measure, parameter, cell=None, periods=None):
    """Return the sensitivity summed over stress periods.

    Summing the per-period arrays gives the response to a parameter held at that
    value over those periods, which is what a constant pumping rate is. Limit
    ``periods`` to the periods a well is actually pumping.
    """
    per_period = period_sensitivity(ws, measure, parameter)
    total = np.zeros_like(next(iter(per_period.values())))
    for kper, arr in per_period.items():
        if periods is None or kper in periods:
            total += arr
    return total if cell is None else total[cell]


def budget_net(ws, term):
    """Return the net (in minus out) budget term per stress period."""
    df = pd.read_csv(pl.Path(ws) / "sv-budget.csv")
    return (df[f"{term}_IN"] - df[f"{term}_OUT"]).values


def well_rates(gwf, nper, packages=("pwell", "prediction")):
    """Return each well cell's rate for every stress period.

    MODFLOW 6 carries a stress period's well list forward until it is replaced,
    so a period with no entry repeats the previous rate.
    """
    rates = {}
    for name in packages:
        pkg = gwf.get_package(name)
        if pkg is None:
            continue
        for kper, records in pkg.stress_period_data.get_data().items():
            if records is None:
                continue
            for record in records:
                cell = tuple(record["cellid"])
                rates.setdefault(cell, np.zeros(nper))[kper] = record["q"]
    for series in rates.values():
        for kper in range(1, nper):
            if series[kper] == 0.0 and series[kper - 1] != 0.0:
                series[kper] = series[kper - 1]
    return rates
