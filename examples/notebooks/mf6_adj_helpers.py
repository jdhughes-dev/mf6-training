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

    mf6adj writes one solution per time step. A stress period with several time
    steps therefore contributes several, and the sensitivity to a stress applied
    over the whole period is their sum.

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
            arr = hf[key][parameter][:]
            out[kper] = arr if kper not in out else out[kper] + arr
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


# ---------------------------------------------------------------------------
# Idealised confined aquifer, for verifying against the Theis solution
# ---------------------------------------------------------------------------
# The Theis solution assumes a confined aquifer that is homogeneous, isotropic,
# of uniform thickness and infinite extent, pumped by fully penetrating wells,
# with drawdown tending to zero at infinity. THEIS_* below set up a model that
# meets those assumptions, so the simulated, superposed, and analytical
# drawdowns can be compared without anything else getting in the way.

THEIS_DX = 500.0  # cell size (m)
THEIS_HALF = 15000.0  # half the domain width (m)
THEIS_THICK = 50.0  # aquifer thickness (m)
THEIS_K = 10.0  # hydraulic conductivity (m/d)
THEIS_SS = 4.0e-5  # specific storage (1/m)
THEIS_NPER = 10  # stress periods
THEIS_PERLEN = 10.0  # stress period length (d)
# Time steps are uniform. mf6adj reports one sensitivity per time step and the
# sensitivity to a rate held over a period is their sum, which holds when the
# steps are equal; with a time-step multiplier the superposition below does not
# reproduce the simulated drawdown.
THEIS_NSTP = 5

THEIS_T = THEIS_K * THEIS_THICK  # transmissivity (m2/d)
THEIS_S = THEIS_SS * THEIS_THICK  # storativity

# name -> (x, y, rate in m3/d, zero-based stress period the well starts in),
# with x and y measured in metres from the centre of the domain
THEIS_WELLS = {
    "A": (0.0, 0.0, -2000.0, 0),
    "B": (-2000.0, 2000.0, -1200.0, 3),
    "C": (3000.0, -1000.0, -1600.0, 6),
}
# An alternative pumping schedule, used to show that the sensitivities do not
# depend on the rates they were computed with: A pumps half as much again, B is
# never switched on, and C starts five periods earlier at half its rate. Each
# entry is (rate in m3/d, zero-based stress period the well starts in).
THEIS_ALT_SCHEDULE = {
    "A": (-3000.0, 0),
    "B": (0.0, 0),
    "C": (-800.0, 2),
}

# observation points, also in metres from the centre
THEIS_OBS = {
    "OBS1": (1500.0, 0.0),
    "OBS2": (-1000.0, -1500.0),
    "OBS3": (2000.0, 2000.0),
    "OBS4": (0.0, -4000.0),
}


def theis_cell(x, y):
    """Zero-based (row, column) of the point (x, y) metres from the centre."""
    return int((THEIS_HALF - y) // THEIS_DX), int((x + THEIS_HALF) // THEIS_DX)


def theis_rates(schedule=None):
    """Each well's rate in every stress period, as a name -> array mapping.

    ``schedule`` maps a well name to ``(rate, start period)`` and defaults to
    the rates in THEIS_WELLS; pass THEIS_ALT_SCHEDULE for the alternative.
    """
    if schedule is None:
        schedule = {name: (q, start) for name, (_, _, q, start) in THEIS_WELLS.items()}
    return {
        name: np.array([(q if kper >= start else 0.0) for kper in range(THEIS_NPER)])
        for name, (q, start) in schedule.items()
    }


def theis_simulation(ws, exe_name, schedule=None):
    """Build the idealised confined aquifer.

    ``schedule`` is passed to :func:`theis_rates`, so the same aquifer can be
    rebuilt with any set of pumping rates. The workspace is emptied first, so a
    rerun does not leave stale adjoint solution files for mf6adj to warn about.
    """
    ws = pl.Path(ws)
    if ws.exists():
        shutil.rmtree(ws)
    n = int(2 * THEIS_HALF / THEIS_DX)
    sim = flopy.mf6.MFSimulation(
        sim_name="theis", sim_ws=str(ws), exe_name=str(exe_name)
    )
    flopy.mf6.ModflowTdis(
        sim,
        nper=THEIS_NPER,
        perioddata=[(THEIS_PERLEN, THEIS_NSTP, 1.0)] * THEIS_NPER,
        time_units="days",
    )
    flopy.mf6.ModflowIms(
        sim,
        complexity="simple",
        outer_dvclose=1.0e-9,
        inner_dvclose=1.0e-10,
        linear_acceleration="bicgstab",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="theis", save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=1,
        nrow=n,
        ncol=n,
        delr=THEIS_DX,
        delc=THEIS_DX,
        top=0.0,
        botm=-THEIS_THICK,
        length_units="meters",
        xorigin=-THEIS_HALF,
        yorigin=-THEIS_HALF,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=0.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=THEIS_K, save_specific_discharge=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=0, ss=THEIS_SS, sy=0.0, transient={0: True})

    rates = theis_rates(schedule)
    spd = {}
    for kper in range(THEIS_NPER):
        spd[kper] = [
            [(0, *theis_cell(x, y)), float(rates[name][kper])]
            for name, (x, y, _, _) in THEIS_WELLS.items()
        ]
    flopy.mf6.ModflowGwfwel(gwf, stress_period_data=spd, pname="wel6")

    # Theis has drawdown going to zero at infinity; a constant head far enough
    # away from the wells is the same condition, and the edge of this domain is
    # twice the radius of influence away
    edge = [
        [(0, i, j), 0.0]
        for i in range(n)
        for j in range(n)
        if i in (0, n - 1) or j in (0, n - 1)
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: edge})
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="theis.hds",
        budget_filerecord="theis.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    return sim


def theis_analytical(x, y, schedule=None):
    """Theis drawdown at (x, y) at the end of every stress period.

    Superposes the wells in space and their start times in time, which is the
    same principle the adjoint superposition uses. ``schedule`` is as in
    :func:`theis_rates`.
    """
    from scipy.special import exp1

    if schedule is None:
        schedule = {name: (q, start) for name, (_, _, q, start) in THEIS_WELLS.items()}
    tend = np.arange(1, THEIS_NPER + 1) * THEIS_PERLEN
    s = np.zeros(THEIS_NPER)
    for name, (xw, yw, _, _) in THEIS_WELLS.items():
        q, start = schedule[name]
        if q == 0.0:
            continue
        r = float(np.hypot(xw - x, yw - y))
        elapsed = tend - start * THEIS_PERLEN
        live = elapsed > 0.0
        u = r * r * THEIS_S / (4.0 * THEIS_T * elapsed[live])
        s[live] += -q / (4.0 * np.pi * THEIS_T) * exp1(u)
    return s


def theis_period_heads(ws):
    """Simulated head at the end of each stress period, as (nper, nrow, ncol)."""
    hobj = flopy.utils.HeadFile(pl.Path(ws) / "theis.hds")
    times = np.array(hobj.get_times())
    idx = [
        int(np.argmin(np.abs(times - (n + 1) * THEIS_PERLEN)))
        for n in range(THEIS_NPER)
    ]
    return hobj.get_alldata()[idx][:, 0]


def theis_boundary_share(ws):
    """Water drawn from the perimeter as a fraction of what the wells pump.

    Drawdown at the perimeter is zero by construction, since it is held at the
    starting head, so it says nothing about whether the domain is wide enough.
    What does is how much water the boundary supplies: if the wells are still
    drawing almost everything from storage, the aquifer is behaving as though it
    were infinite.
    """
    budget = flopy.utils.Mf6ListBudget(str(pl.Path(ws) / "theis.lst"))
    incremental, _ = budget.get_dataframes(start_datetime=None)
    last = incremental.iloc[-1]
    chd = sum(last[c] for c in incremental.columns if c.upper().startswith("CHD_IN"))
    wel = sum(last[c] for c in incremental.columns if c.upper().startswith("WEL_OUT"))
    return float(chd), float(wel), (float(chd) / float(wel) if wel else float("nan"))


# ---------------------------------------------------------------------------
# Water-table model: an unconfined layer over a confined aquifer
# ---------------------------------------------------------------------------
# The same three-layer system as flopy-intro-gwf-only-a - a water-table layer,
# a thin confining unit, and a confined aquifer - refined and run transiently
# with two wells pumping the lower aquifer. Layer 1 is convertible, so its
# transmissivity follows the water table and the model is not linear in the
# pumping rates; that is the point of the notebook that uses it.

WT_REFINE = 2  # cells per cell of the flopy-intro grid
WT_NROW, WT_NCOL = 21 * WT_REFINE, 20 * WT_REFINE
WT_DELR = 10000.0 / WT_NCOL  # ft
WT_DELC = 10500.0 / WT_NROW  # ft
WT_TOP = 400.0  # land surface (ft)
WT_BOTM = [220.0, 200.0, 0.0]  # layer bottoms (ft)
WT_K = [50.0, 0.01, 200.0]  # horizontal conductivity (ft/d)
WT_K33 = [10.0, 0.01, 20.0]  # vertical conductivity (ft/d)
WT_ICELLTYPE = [1, 0, 0]  # layer 1 is convertible: a water table
WT_SY = 0.20  # specific yield of the water-table layer
WT_SS = 1.0e-5  # specific storage (1/ft)
WT_STRT = 320.0  # starting head (ft)
WT_RECHARGE = 0.005  # ft/d
WT_RIV_STAGE, WT_RIV_BOT = 320.0, 318.0
WT_RIV_COND = 1.0e5 / WT_REFINE  # per cell, so the total matches the coarse grid
WT_NPER, WT_PERLEN, WT_NSTP = 9, 365.0, 3  # steady spin-up, then eight years

# name -> (layer, row, column, rate in ft3/d, zero-based period the well starts)
WT_WELLS = {
    "shallow": (0, 5 * WT_REFINE, 6 * WT_REFINE, -2.0e4, 1),
    "deep": (2, 15 * WT_REFINE, 12 * WT_REFINE, -6.0e4, 4),
}
# Observation wells, placed to suit the cone each aquifer makes. The water table
# has the lower transmissivity, so its cone is steep and an observation well has
# to be near the pumping to see it - this one is 500 ft away. The confined
# aquifer's cone is broad and flat, so a well 2,000 ft out still sees most of the
# drawdown. Each is read in both layers, so the confining unit's effect shows.
# WT_REFINE cells is 500 ft whatever the refinement.
WT_OBS = {
    "500 ft from the shallow well": (5 * WT_REFINE, 7 * WT_REFINE),
    "midway between the wells": (10 * WT_REFINE, 9 * WT_REFINE),
    "2,000 ft from the deep well": (15 * WT_REFINE, 16 * WT_REFINE),
}


def wt_rates(multipliers=None):
    """Each well's rate in every stress period, scaled by an optional multiplier.

    A multiplier for a well that does not exist is an error rather than a
    silently ignored key, since that would otherwise leave the well pumping at
    its full rate.
    """
    multipliers = multipliers or {}
    unknown = set(multipliers) - set(WT_WELLS)
    if unknown:
        raise KeyError(
            f"no such well: {', '.join(sorted(unknown))}; "
            f"the wells are {', '.join(WT_WELLS)}"
        )
    return {
        name: np.array([(q if kper >= start else 0.0) for kper in range(WT_NPER)])
        * float(multipliers.get(name, 1.0))
        for name, (_, _, _, q, start) in WT_WELLS.items()
    }


def wt_simulation(ws, exe_name, rates=None):
    """Build the water-table simulation. ``rates`` defaults to wt_rates()."""
    ws = pl.Path(ws)
    if ws.exists():
        shutil.rmtree(ws)
    sim = flopy.mf6.MFSimulation(sim_name="wt", sim_ws=str(ws), exe_name=str(exe_name))
    perioddata = [(1.0, 1, 1.0)] + [(WT_PERLEN, WT_NSTP, 1.0)] * (WT_NPER - 1)
    flopy.mf6.ModflowTdis(sim, nper=WT_NPER, perioddata=perioddata, time_units="days")
    flopy.mf6.ModflowIms(
        sim,
        complexity="moderate",
        outer_maximum=200,
        inner_maximum=200,
        outer_dvclose=1.0e-8,
        inner_dvclose=1.0e-9,
        linear_acceleration="bicgstab",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="wt", save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=3,
        nrow=WT_NROW,
        ncol=WT_NCOL,
        delr=WT_DELR,
        delc=WT_DELC,
        top=WT_TOP,
        botm=WT_BOTM,
        length_units="feet",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=WT_STRT)
    flopy.mf6.ModflowGwfnpf(
        gwf,
        k=WT_K,
        k33=WT_K33,
        icelltype=WT_ICELLTYPE,
        save_specific_discharge=True,
    )
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=WT_ICELLTYPE,
        ss=WT_SS,
        sy=WT_SY,
        steady_state={0: True},
        transient={kper: True for kper in range(1, WT_NPER)},
    )
    flopy.mf6.ModflowGwfrcha(gwf, recharge=WT_RECHARGE)
    riv = [
        [(0, i, WT_NCOL - 1), WT_RIV_STAGE, WT_RIV_COND, WT_RIV_BOT]
        for i in range(WT_NROW)
    ]
    flopy.mf6.ModflowGwfriv(gwf, stress_period_data={0: riv})

    if rates is None:
        rates = wt_rates()
    spd = {
        kper: [
            [(k, i, j), float(rates[name][kper])]
            for name, (k, i, j, _, _) in WT_WELLS.items()
        ]
        for kper in range(WT_NPER)
    }
    flopy.mf6.ModflowGwfwel(gwf, stress_period_data=spd, pname="wel6")
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="wt.hds",
        budget_filerecord="wt.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    return sim


def wt_period_heads(ws):
    """Head at the end of each stress period, as (nper, nlay, nrow, ncol)."""
    hobj = flopy.utils.HeadFile(pl.Path(ws) / "wt.hds")
    ends = [0] + [1 + WT_NSTP * kper - 1 for kper in range(1, WT_NPER)]
    return hobj.get_alldata()[ends]


def wt_kernels(ws):
    """Per-period sensitivity of each well's head, for every well and period.

    Keyed by ``(well, measure period)``. Reading one of these at a cell gives
    that cell's drawdown response to the well, by reciprocity.
    """
    return {
        (name, kper): period_sensitivity(ws, f"{name}{kper:02d}", "wel6_q")
        for name in WT_WELLS
        for kper in range(WT_NPER)
    }


def wt_superpose(kernels, rates, cells):
    """Predicted drawdown history at ``cells``, a name -> (lay, row, col) map."""
    out = {name: np.zeros(WT_NPER) for name in cells}
    for well in WT_WELLS:
        for target in range(WT_NPER):
            for kper, sens in kernels[(well, target)].items():
                for name, cell in cells.items():
                    out[name][target] += -sens[cell] * rates[well][kper]
    return out


def wt_drawdown_map(kernels, rates, layer, kper=None):
    """Predicted drawdown over the whole grid for one layer and period."""
    if kper is None:
        kper = WT_NPER - 1
    total = np.zeros((3, WT_NROW, WT_NCOL))
    for well in WT_WELLS:
        for period, sens in kernels[(well, kper)].items():
            total += -sens.reshape(total.shape) * rates[well][period]
    return total[layer]
