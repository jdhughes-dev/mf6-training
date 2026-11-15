"""Build the source-water end-member models for the synthetic valley.

Where does the water a well produces come from? Give one source a concentration
of 1 and everything else a concentration of 0, and the simulated concentration
at the well is the fraction of its water that came from that source. Three runs
cover the valley: water from the lake, water from recharge, and the water that
was already in the aquifer when pumping started.

One flow run serves all three. The lake and the unsaturated zone each carry a
concentration of 1 as an auxiliary variable, which the flow model writes to its
budget file; each transport run reads only the source it traces and treats the
other as clean water.

The model is the Voronoi-grid synthetic valley in
examples/data/synthetic-valley/synthetic-valley-vg-advanced-annual: a steady
period with the wells off, then 20 years of pumping from the two multi-aquifer
wells. The steady period is shortened to one day, so the water in the aquifer at
the start of the transport run is the water there when pumping starts.
"""

import pathlib as pl

import flopy
import numpy as np
import pandas as pd

VG_WS = pl.Path("../data/synthetic-valley/synthetic-valley-vg-advanced-annual")
FLOW_NAME = "sv"
GWT_NAME = "trans"

SPINUP = 1.0  # d, the steady period with the wells off

POROSITY = 0.25  # the specific yield of layers 2, 4, and 5
ALH = 75.0  # m, dispersivity along the flow direction
ATH1 = 7.5  # m, dispersivity across it

# the two pumping wells, by the boundnames of the multi-aquifer well package
WELL_NAMES = ("reilly", "vc")

# name -> (flow packages whose water is labeled, initial concentration)
END_MEMBERS = {
    "lake": (("lak-1",), 0.0),
    "recharge": (("uzf-1",), 0.0),
    "initial": ((), 1.0),
}


def build_flow(ws, exe_name):
    """Write and return the flow simulation shared by the three end members."""
    sim = flopy.mf6.MFSimulation.load(
        sim_name=FLOW_NAME,
        sim_ws=str(VG_WS),
        exe_name=str(exe_name),
        write_headers=False,
        verbosity_level=0,
    )
    sim.set_sim_path(str(ws))
    gwf = sim.get_model(FLOW_NAME)

    # a steady state does not depend on the period length, so shorten the first
    # period to a day and move the infiltration and evapotranspiration of the
    # pumping years back by the same amount
    perioddata = sim.tdis.perioddata.array.copy()
    shift = perioddata["perlen"][0] - SPINUP
    perioddata["perlen"][0] = SPINUP
    sim.tdis.perioddata = perioddata
    uzf = gwf.get_package("uzf-1")
    series = uzf.ts.timeseries.get_data().copy()
    later = series["ts_time"] > 0.0
    series["ts_time"][later] -= shift
    uzf.ts.timeseries.set_data(series)

    # label the lake water and the water that infiltrates the unsaturated zone
    # with a concentration of 1
    lak = gwf.get_package("lak-1")
    lakes = lak.packagedata.get_data()
    lak.auxiliary = ["concentration"]
    lak.packagedata = [
        (row["ifno"], row["strt"], row["nlakeconn"], 1.0, row["boundname"])
        for row in lakes
    ]
    stored = uzf.perioddata.get_data()
    uzf.auxiliary = ["concentration"]
    uzf.perioddata = {
        kper: [tuple(row) + (1.0,) for row in rows] for kper, rows in stored.items()
    }

    # transport needs how full each cell is, and the water each well pumps
    gwf.npf.save_saturation = True
    gwf.get_package("pwell").budget_filerecord = f"{FLOW_NAME}.maw.cbc"

    sim.write_simulation(silent=True)
    return sim


def build_transport(ws, exe_name, flow_ws, end_member="lake", name=GWT_NAME):
    """Write and return the transport simulation that reads ``flow_ws``."""
    labeled, initial_concentration = END_MEMBERS[end_member]

    flow_sim = flopy.mf6.MFSimulation.load(
        sim_ws=str(flow_ws),
        verbosity_level=0,
        load_only=["tdis", "disv"],
    )
    gwf = flow_sim.get_model()

    sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=str(ws), exe_name=str(exe_name))
    flopy.mf6.ModflowTdis(
        sim,
        nper=flow_sim.tdis.nper.data,
        perioddata=flow_sim.tdis.perioddata.array,
        time_units="days",
    )
    flopy.mf6.ModflowIms(
        sim,
        complexity="simple",
        linear_acceleration="bicgstab",
        outer_dvclose=1.0e-6,
        inner_dvclose=1.0e-7,
    )
    gwt = flopy.mf6.ModflowGwt(sim, modelname=name, save_flows=True)
    disv = gwf.disv
    flopy.mf6.ModflowGwtdisv(
        gwt,
        length_units="meters",
        nlay=disv.nlay.data,
        ncpl=disv.ncpl.data,
        nvert=disv.nvert.data,
        vertices=disv.vertices.array,
        cell2d=disv.cell2d.array,
        top=disv.top.array,
        botm=disv.botm.array,
        idomain=disv.idomain.array,
    )
    flopy.mf6.ModflowGwtic(gwt, strt=initial_concentration)
    flopy.mf6.ModflowGwtmst(gwt, porosity=POROSITY)
    flopy.mf6.ModflowGwtadv(gwt, scheme="tvd")
    flopy.mf6.ModflowGwtdsp(gwt, alh=ALH, ath1=ATH1, diffc=0.0, xt3d_off=True)
    flow_dir = pl.Path("..") / flow_ws.name
    flopy.mf6.ModflowGwtfmi(
        gwt,
        packagedata=[
            ("GWFHEAD", str(flow_dir / f"{FLOW_NAME}.hds")),
            ("GWFBUDGET", str(flow_dir / f"{FLOW_NAME}.cbc")),
            ("pwell", str(flow_dir / f"{FLOW_NAME}.maw.cbc")),
        ],
    )
    # read the label of the traced source only; water from every other
    # boundary enters clean
    flopy.mf6.ModflowGwtssm(
        gwt, sources=[(pname, "AUX", "CONCENTRATION") for pname in labeled] or None
    )
    # the well bore mixes the water from both screens, so its concentration is
    # the share of the pumped water that came from the traced source
    flopy.mf6.ModflowGwtmwt(
        gwt,
        flow_package_name="pwell",
        boundnames=True,
        packagedata=[
            (i, initial_concentration, well) for i, well in enumerate(WELL_NAMES)
        ],
        observations={
            f"{name}.obs.csv": [(well, "CONCENTRATION", well) for well in WELL_NAMES]
        },
        pname="pwell",
    )
    flopy.mf6.ModflowGwtoc(
        gwt,
        concentration_filerecord=f"{name}.ucn",
        budget_filerecord=f"{name}.cbc",
        budgetcsv_filerecord=f"{name}-budget.csv",
        saverecord=[("CONCENTRATION", "LAST"), ("BUDGET", "LAST")],
    )
    sim.write_simulation(silent=True)
    return sim


def _run(sim, workspace):
    """Run a simulation and raise with the end of its output if it fails."""
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError(f"{workspace} failed:\n" + "\n".join(buff[-20:]))


def read_observations(path):
    """Read an observation file, including numbers Fortran wrote without an E.

    A concentration below about 1e-100 comes out as "0.2843341398-102", which
    has no exponent letter and is not a number to pandas, so put the E back.
    """
    observations = pd.read_csv(path, dtype=str)
    fortran = observations.replace(r"^\s*([\d.]+)([+-]\d+)\s*$", r"\1E\2", regex=True)
    frame = fortran.apply(pd.to_numeric, errors="coerce")
    return frame.rename(columns=str.lower)


def source_fractions(root, exe_name):
    """Run the flow model and the three end members; return the well fractions.

    Each end member's dataframe is the concentration of the water each well
    pumps through time, which is that source's share of it.
    """
    root = pl.Path(root)
    flow_ws = root / "flow"
    _run(build_flow(flow_ws, exe_name), flow_ws)

    fractions = {}
    for end_member in END_MEMBERS:
        transport_ws = root / f"{end_member}-transport"
        _run(
            build_transport(transport_ws, exe_name, flow_ws, end_member),
            transport_ws,
        )
        fractions[end_member] = read_observations(transport_ws / f"{GWT_NAME}.obs.csv")
    return fractions


def fraction_closure(fractions):
    """How far the three end members depart from summing to 1 at the wells.

    The three sources are the only water the wells can draw, so their fractions
    have to add to 1 wherever they are read. The largest departure is the check
    that the end members are complete.
    """
    total = sum(frame[list(WELL_NAMES)].to_numpy() for frame in fractions.values())
    return float(np.abs(total - 1.0).max())


def final_fractions(fractions):
    """The three fractions at each well at the end of the run, as a dataframe."""
    return pd.DataFrame(
        {
            end_member: frame[list(WELL_NAMES)].iloc[-1]
            for end_member, frame in fractions.items()
        }
    )
