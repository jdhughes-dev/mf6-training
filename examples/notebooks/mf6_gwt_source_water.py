"""Build the source-water end-member models for the synthetic valley.

Where does the water a well produces come from? Give one source a concentration
of 1 and everything else a concentration of 0, and the simulated concentration
at the well is the fraction of its water that came from that source. Three runs
cover the valley: water from the lake, water from recharge, and the water that
was already in the aquifer when the simulation started.

Each end member needs its own flow run as well as its own transport run. The
source concentrations reach transport as auxiliary variables on the flow
packages, carried in the budget file that the Flow Model Interface reads, so a
flow run belongs to the end member it was built for.

The model is the Voronoi-grid synthetic valley in
examples/data/synthetic-valley/synthetic-valley-vg, which is the MODFLOW 6
example ex-gwt-synthetic-valley. Its 121 monthly stress periods are replaced
here by a steady period with the wells off and 30 years of pumping, which is
long enough for the fractions to develop and short enough to run three times.
"""

import pathlib as pl

import flopy
import numpy as np
import pandas as pd

VG_WS = pl.Path("../data/synthetic-valley/synthetic-valley-vg")

SPINUP = 1.0  # d, a steady period with the wells off, to start the heads from
PERLEN = 10957.5  # d, 30 years of pumping
# the Flow Model Interface reads one flow budget record per transport time step,
# so both models step through the pumping period the same way: once a year. Ten
# steps of three years each does not converge - the Newton solve needs the
# smaller steps to follow the water table down around the wells.
NSTP = 30

POROSITY = 0.2
ALH = 75.0  # m, dispersivity along the flow direction
ATH1 = 7.5  # m, dispersivity across it

# the three pumping wells, by the boundnames the shipped model gives them
WELL_NAMES = ("P1", "P2", "P3")

# name -> (lake concentration, recharge concentration, initial concentration)
END_MEMBERS = {
    "lake": (1.0, 0.0, 0.0),
    "recharge": (0.0, 1.0, 0.0),
    "initial": (0.0, 0.0, 1.0),
}

GWT_NAME = "trans"


def _first_period(package, attribute="stress_period_data"):
    """The earliest stress period stored in a package, as a record array."""
    data = getattr(package, attribute).get_data()
    return data[min(data)]


def build_flow(ws, exe_name, end_member="lake", name="flow"):
    """Write and return the flow simulation for one end member."""
    lake_concentration, recharge_concentration, _ = END_MEMBERS[end_member]

    sim = flopy.mf6.MFSimulation.load(
        sim_name=name, sim_ws=str(VG_WS), exe_name=str(exe_name), verbosity_level=0
    )
    sim.set_sim_path(str(ws))
    gwf = sim.get_model()

    # a steady period with the wells off, which is where the heads settle from
    # the starting value, then 30 transient years of pumping. Pumping this
    # valley to a steady state does not converge, and a transient run is the
    # truer picture anyway.
    sim.tdis.nper = 2
    sim.tdis.perioddata = [(SPINUP, 1, 1.0), (PERLEN, NSTP, 1.0)]
    gwf.sto.steady_state.set_data({0: True, 1: False})
    gwf.sto.transient.set_data({0: False, 1: True})

    wells = gwf.get_package("well-1")
    wells.stress_period_data.set_data({1: _first_period(wells)})

    # The stream and the lake carry a value per period; keep the first of each,
    # and give the lake the concentration this end member traces. Both periods
    # are written, because setting only the first leaves whatever the shipped
    # model had in the second - which for the lake is a concentration of 1000.
    for pname in ("sfr-1", "lak-1"):
        package = gwf.get_package(pname)
        stored = package.perioddata.get_data()
        first = [tuple(record) for record in stored[min(stored)]]
        if pname == "lak-1":
            first.append((0, "AUXILIARY", "CONCENTRATION", lake_concentration))
        package.perioddata.set_data({0: first, 1: first})

    # evapotranspiration is read as arrays, one set per period
    evt = gwf.get_package("evta_0")
    for array_name in ("surface", "rate", "depth"):
        stored = getattr(evt, array_name).get_data()
        first = stored[min(stored)]
        getattr(evt, array_name).set_data({0: first, 1: first})

    # recharge carries only iflowface in the shipped model, so rebuild it with
    # the concentration the transport model reads
    rch = gwf.get_package("rch-1")
    stored = rch.recharge.get_data()
    recharge = stored[min(stored)]
    gwf.remove_package("rch-1")
    flopy.mf6.ModflowGwfrcha(
        gwf,
        pname="rch-1",
        readasarrays=True,
        auxiliary=["concentration"],
        recharge={0: recharge, 1: recharge},
        aux={0: recharge_concentration, 1: recharge_concentration},
    )

    # every step, because the transport model reads one budget record per step
    gwf.oc.saverecord.set_data({0: [("HEAD", "ALL"), ("BUDGET", "ALL")]})
    sim.write_simulation(silent=True)
    return sim


def build_transport(ws, exe_name, flow_ws, end_member="lake", name=GWT_NAME):
    """Write and return the transport simulation that reads ``flow_ws``."""
    _, _, initial_concentration = END_MEMBERS[end_member]

    flow_sim = flopy.mf6.MFSimulation.load(
        sim_ws=str(flow_ws), verbosity_level=0, load_only=["disv", "well-1"]
    )
    gwf = flow_sim.get_model()
    # the shipped model lists the wells in the order P3, P1, P2, so take each
    # one's name from its boundname rather than from its position
    wells = _first_period(gwf.get_package("well-1"))
    well_cells = {
        str(name).upper(): tuple(cellid)
        for name, cellid in zip(wells["boundname"], wells["cellid"])
    }

    sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=str(ws), exe_name=str(exe_name))
    flopy.mf6.ModflowTdis(
        sim,
        nper=2,
        perioddata=[(SPINUP, 1, 1.0), (PERLEN, NSTP, 1.0)],
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
    # the flow model keeps the name the shipped valley gives it, so its output
    # files are named for that model rather than for the workspace
    flopy.mf6.ModflowGwtfmi(
        gwt,
        packagedata=[
            ("GWFHEAD", str(pl.Path("..") / flow_ws.name / f"{gwf.name}.hds")),
            ("GWFBUDGET", str(pl.Path("..") / flow_ws.name / f"{gwf.name}.cbc")),
        ],
    )
    flopy.mf6.ModflowGwtssm(
        gwt,
        sources=[
            ("lak-1", "AUX", "CONCENTRATION"),
            ("rch-1", "AUX", "CONCENTRATION"),
        ],
    )
    # concentration at the pumping wells is the answer this notebook is after
    flopy.mf6.ModflowUtlobs(
        gwt,
        digits=10,
        continuous={
            f"{name}.obs.csv": [
                (well, "CONCENTRATION", well_cells[well]) for well in WELL_NAMES
            ]
        },
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


def run_end_member(root, exe_name, end_member):
    """Run the flow and transport pair for one end member and return its wells.

    Returns a dataframe of concentration at each well through time, which is
    that end member's share of the water the well produces.
    """
    root = pl.Path(root)
    flow_ws = root / f"{end_member}-flow"
    transport_ws = root / f"{end_member}-transport"

    for build, workspace in (
        (lambda: build_flow(flow_ws, exe_name, end_member), flow_ws),
        (
            lambda: build_transport(transport_ws, exe_name, flow_ws, end_member),
            transport_ws,
        ),
    ):
        sim = build()
        success, buff = sim.run_simulation(silent=True)
        if not success:
            raise RuntimeError(f"{workspace} failed:\n" + "\n".join(buff[-20:]))

    return read_observations(transport_ws / f"{GWT_NAME}.obs.csv")


def read_observations(path):
    """Read an observation file, including numbers Fortran wrote without an E.

    A concentration below about 1e-100 comes out as "0.2843341398-102", which
    has no exponent letter and is not a number to pandas, so put the E back.
    """
    observations = pd.read_csv(path, dtype=str)
    fortran = observations.replace(r"^\s*([\d.]+)([+-]\d+)\s*$", r"\1E\2", regex=True)
    return fortran.apply(pd.to_numeric, errors="coerce")


def source_fractions(root, exe_name):
    """Run all three end members and return their well fractions through time."""
    return {
        end_member: run_end_member(root, exe_name, end_member)
        for end_member in END_MEMBERS
    }


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
