"""Build the variable-density coastal synthetic valley.

The coastal valley carries a general-head boundary at sea level along its
southern row (see mf6-coastal-ghb.ipynb). Here that boundary becomes a
saltwater coast: a transport model carries salinity, the Buoyancy package turns
salinity into density, and the two are solved together so the saltwater wedge
can develop under the valley.

The shipped valley runs 21 annual stress periods, which is more transport than a
class needs. The builder below keeps the steady spin-up and five pumping years.
"""

import pathlib as pl

import flopy
import numpy as np
from mf6_notebook_helpers import coastal_ghb_data

DATA_ROOT = pl.Path("../data/synthetic-valley")


def coastal_workspace(variant="base"):
    """Shipped coastal model to build the density simulation from."""
    return DATA_ROOT / f"synthetic-valley-coastal-{variant}-annual"


# Period structure: the shipped spin-up, then five annual periods. The spin-up
# is steady state for flow while transport runs through it, which is how a
# density model is brought to a quasi-equilibrium wedge.
NPER = 6
SPINUP_NSTP = 60
ANNUAL_NSTP = 12

# Density. The Buoyancy package needs the density of fresh water and the slope
# of density against concentration, so seawater at 35 kg/m3 gives
# 1000 + 0.7 * 35 = 1024.5 kg/m3, a density ratio of 1.0245. Only that ratio
# enters the flow equations, so the concentration unit does not have to match
# the feet-and-days length and time units of the flow model.
DENSEREF = 1000.0
DRHODC = 0.7
SEAWATER = 35.0

# Transport properties. The flow model has no porosity of its own, and the
# dispersivities are the length scale over which the wedge mixes.
POROSITY = 0.2
ALH = 50.0
ATH1 = 5.0
ATV = 0.5

GWT_NAME = "sv_gwt"


def _trim_periods(package, nper):
    """Drop stress periods at or beyond ``nper`` from a period-keyed package."""
    for attribute in ("stress_period_data", "perioddata"):
        data = getattr(package, attribute, None)
        if data is None:
            continue
        stored = data.get_data()
        if stored is None:
            continue
        data.set_data({k: v for k, v in stored.items() if k < nper})
        return


def build_simulation(
    ws,
    exe_name,
    variant="base",
    buoyancy=True,
    equivalent_freshwater=False,
    prediction_rate=-3.0e5,
    nper=NPER,
):
    """Return the coupled flow and transport simulation, written to ``ws``.

    ``variant`` is "base" (RIV, RCH, EVT) or "advanced" (SFR, LAK, UZF, MAW,
    MVR). ``buoyancy`` False leaves the Buoyancy package out, which gives the
    same model at a constant fluid density - the comparison that isolates what
    density does. ``equivalent_freshwater`` rebuilds the coastal boundary with
    heads that rise with depth, which is how a constant-density model carries
    the weight of the sea; it belongs with ``buoyancy=False``, or the density is
    counted twice. ``prediction_rate`` is the rate of the prediction well, which
    pumps through every transient period.
    """
    sim = flopy.mf6.MFSimulation.load(
        sim_name="sv",
        sim_ws=str(coastal_workspace(variant)),
        exe_name=str(exe_name),
        verbosity_level=0,
    )
    sim.set_sim_path(str(ws))
    gwf = sim.get_model()

    perioddata = [(16071.0, SPINUP_NSTP, 1.0)]
    for _ in range(nper - 1):
        perioddata.append((365.0, ANNUAL_NSTP, 1.0))
    sim.tdis.nper = nper
    sim.tdis.perioddata = perioddata

    period_packages = {
        "base": ("rch_0", "evt_0", "pwell"),
        "advanced": ("uzf-1", "lak-1", "pwell"),
    }[variant]
    for name in period_packages:
        _trim_periods(gwf.get_package(name), nper)

    # the prediction well is idle until period 12 of the shipped valley, which
    # the shortened run never reaches, so pump it through the transient periods
    prediction = gwf.get_package("prediction")
    cellid = prediction.stress_period_data.get_data(11)["cellid"][0]
    prediction.stress_period_data.set_data(
        {kper: [(cellid, prediction_rate)] for kper in range(1, nper)}
    )

    if equivalent_freshwater:
        ghb = gwf.get_package("ghb-1")
        spd, _ = coastal_ghb_data(gwf, equivalent_freshwater=True)
        ghb.stress_period_data.set_data({0: spd})

    # one head and budget per stress period, keyed by period as OC expects
    gwf.oc.saverecord.set_data({0: [("HEAD", "LAST"), ("BUDGET", "LAST")]})

    if buoyancy:
        flopy.mf6.ModflowGwfbuy(
            gwf,
            denseref=DENSEREF,
            # (species, drhodc, reference concentration, model, auxiliary name)
            packagedata=[(0, DRHODC, 0.0, GWT_NAME, "CONCENTRATION")],
        )

    gwt = flopy.mf6.ModflowGwt(sim, modelname=GWT_NAME, save_flows=True)
    dis = gwf.dis
    flopy.mf6.ModflowGwtdis(
        gwt,
        nlay=dis.nlay.data,
        nrow=dis.nrow.data,
        ncol=dis.ncol.data,
        delr=dis.delr.array,
        delc=dis.delc.array,
        top=dis.top.array,
        botm=dis.botm.array,
        idomain=dis.idomain.array,
        length_units="feet",
    )
    flopy.mf6.ModflowGwtic(gwt, strt=0.0)
    flopy.mf6.ModflowGwtmst(gwt, porosity=POROSITY)
    flopy.mf6.ModflowGwtadv(gwt, scheme="upstream")
    flopy.mf6.ModflowGwtdsp(gwt, alh=ALH, ath1=ATH1, atv=ATV, diffc=0.0, xt3d_off=True)
    # the coast is the only source of salt; every other boundary takes water out
    # at the concentration of the cell it sits in, which is the default
    flopy.mf6.ModflowGwtssm(gwt, sources=[("ghb-1", "AUX", "CONCENTRATION")])
    if gwf.get_package("mvr") is not None:
        # the mover routes water between the advanced packages, and MODFLOW 6
        # stops unless transport knows about it. An MVT package with no options
        # satisfies that: the mover carries water but no solute, which is exact
        # here because everything it routes is fresh.
        flopy.mf6.ModflowGwtmvt(gwt)
    flopy.mf6.ModflowGwtoc(
        gwt,
        concentration_filerecord=f"{GWT_NAME}.ucn",
        budget_filerecord=f"{GWT_NAME}.cbc",
        budgetcsv_filerecord=f"{GWT_NAME}-budget.csv",
        saverecord=[("CONCENTRATION", "LAST"), ("BUDGET", "LAST")],
    )

    ims_gwt = flopy.mf6.ModflowIms(
        sim,
        filename=f"{GWT_NAME}.ims",
        complexity="moderate",
        linear_acceleration="bicgstab",
        outer_dvclose=1.0e-6,
        inner_dvclose=1.0e-7,
    )
    sim.register_ims_package(ims_gwt, [gwt.name])
    flopy.mf6.ModflowGwfgwt(
        sim, exgtype="GWF6-GWT6", exgmnamea=gwf.name, exgmnameb=gwt.name
    )

    sim.write_simulation(silent=True)
    return sim


def concentration(ws, totim=None):
    """Simulated salinity, as (ntimes, nlay, nrow, ncol) or one time.

    Inactive cells - the lake footprint in the advanced valley - come back as
    MODFLOW's 1e30 placeholder and are returned as NaN.
    """
    ucn = flopy.utils.HeadFile(pl.Path(ws) / f"{GWT_NAME}.ucn", text="CONCENTRATION")
    conc = ucn.get_alldata() if totim is None else ucn.get_data(totim=totim)
    conc = np.asarray(conc, dtype=float)
    conc[conc >= 1.0e30] = np.nan
    return conc


def wedge_toe(conc, column, layer, delc, fraction=0.5):
    """How far inland the wedge reaches along ``column``, in feet.

    The coast is the southern row, so the wedge moves north up a column. The toe
    is the last cell whose salinity is at least ``fraction`` of seawater; a wedge
    that has not formed returns 0.
    """
    salty = np.flatnonzero(conc[layer, :, column] >= fraction * SEAWATER)
    if salty.size == 0:
        return 0.0
    nrow = conc.shape[1]
    return float((nrow - salty.min()) * delc)
