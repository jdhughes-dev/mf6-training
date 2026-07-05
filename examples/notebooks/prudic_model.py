"""Base flow-and-transport model for the denitrification API notebook (part F).

This is the MODFLOW 6 example ``ex-gwt-prudic2004t2`` (Prudic and others, 2004):
a steady groundwater-flow (GWF) model coupled to one groundwater-transport (GWT)
model per nitrogen species, with SFR (streams), LAK (a lake), and MVR (a mover)
plus advanced-package transport (SFT/LKT/MVT).

None of this construction is the API lesson - it is just the working model the
reaction callback acts on - so it lives here and the notebook imports
``build_prudic_simulation`` (and a few geometry/mass helpers) instead of showing
~150 lines of plumbing. All parameters below are taken from the base example and
are held fixed; the notebook supplies only the reaction configuration.

The data files (grid, boundaries, stream geometry) live in ``../data/<base>``
relative to the notebook, so import and call these from that working directory.
"""

import pathlib as pl

import flopy
import numpy as np

# base example name and its data directory (relative to the notebook)
base_example = "ex-gwt-prudic2004t2"
data_path = pl.Path("../data") / base_example

# --- grid / flow / transport parameters (from ex-gwt-prudic2004t2) ---
length_units = "feet"
time_units = "days"

hk = 250.0
vk = 125.0
porosity = 0.30
recharge = 4.79e-3
lakebed_leakance = 1.0
streambed_k = 100.0
streambed_thick = 1.0
stream_width = 5.0
manning = 0.03
alpha_l = 20.0
alpha_th = 2.0
alpha_tv = 0.2

nlay = 8
nrow = 36
ncol = 23
delr = 405.665
delc = 403.717
delv = 15.0
top = 100.0


# ---------------------------------------------------------------------------
# Read the base-model data files
# ---------------------------------------------------------------------------
def retrieve(fname):
    """Return the path to a base-model data file in the local data directory."""
    dest = data_path / fname
    if not dest.is_file():
        raise FileNotFoundError(
            f"{dest} not found - expected the {base_example} data alongside "
            "the notebook (see ../data)."
        )
    return dest


def load_grid_data():
    """Return ``(botm, idomain, lakibd)`` read from the base-model data files."""
    bot0 = np.loadtxt(retrieve("bot1.dat"))
    botm = [bot0] + [bot0 - (delv * k) for k in range(1, nlay)]
    idomain0 = np.loadtxt(retrieve("idomain1.dat"), dtype=int)
    idomain = nlay * [idomain0]
    lakibd = np.loadtxt(retrieve("lakibd.dat"), dtype=int)
    return botm, idomain, lakibd


def get_stream_data():
    """Return ``(packagedata, connectiondata)`` for the SFR stream network."""
    fpath = retrieve("stream.csv")
    dt = 5 * [int] + [float]
    streamdata = np.genfromtxt(fpath, names=True, delimiter=",", dtype=dt)
    connectiondata = [[ireach] for ireach in range(streamdata.shape[0])]
    isegold = -1
    distance_along_segment = []
    distance = 0
    for ireach, row in enumerate(streamdata):
        iseg = row["seg"] - 1
        if iseg == isegold:
            connectiondata[ireach].append(ireach - 1)
            connectiondata[ireach - 1].append(-ireach)
            distance += (
                streamdata["length"][ireach - 1] * 0.5
                + streamdata["length"][ireach] * 0.5
            )
        else:
            distance = 0.5 * streamdata["length"][ireach]
        isegold = iseg
        distance_along_segment.append(distance)

    connectiondata[17].append(-31)
    connectiondata[31].append(17)
    connectiondata[30].append(-31)
    connectiondata[31].append(30)

    segment_lengths = []
    for iseg in [1, 2, 3, 4]:
        idx = np.where(streamdata["seg"] == iseg)
        segment_lengths.append(streamdata["length"][idx].sum())

    emaxmin = [(49, 45), (44.5, 34), (41.5, 34.0), (34.0, 27.2)]
    segment_gradients = [
        (emax - emin) / segment_lengths[iseg]
        for iseg, (emax, emin) in enumerate(emaxmin)
    ]

    ustrf = 1.0
    ndv = 0
    packagedata = []
    for ireach, row in enumerate(streamdata):
        k, i, j = row["layer"] - 1, row["row"] - 1, row["col"] - 1
        length = row["length"]
        iseg = row["seg"] - 1
        rgrd = segment_gradients[iseg]
        emax, emin = emaxmin[iseg]
        rtp = distance_along_segment[ireach] / segment_lengths[iseg] * (emax - emin)
        rtp = emax - rtp
        rec = (
            ireach,
            (k, i, j),
            length,
            stream_width,
            rgrd,
            rtp,
            streambed_thick,
            streambed_k,
            manning,
            len(connectiondata[ireach]) - 1,
            ustrf,
            ndv,
            f"SEG{iseg + 1}",
        )
        packagedata.append(rec)
    return packagedata, connectiondata


# ---------------------------------------------------------------------------
# Geometry / mass helpers used by the reaction callback and result plots
# ---------------------------------------------------------------------------
def active_cellids(idomain):
    """(k, i, j) for active cells (idomain > 0) in MF6 reduced-node order."""
    return [tuple(int(v) for v in cid) for cid in np.argwhere(idomain > 0)]


def layer_thickness(botm):
    """Per-cell layer thickness (nlay, nrow, ncol) from the top and layer bottoms."""
    thickness = np.empty((nlay, nrow, ncol))
    thickness[0] = top - botm[0]
    for k in range(1, nlay):
        thickness[k] = botm[k - 1] - botm[k]
    return thickness


def saturated_pore_volume_reduced(sim):
    """Pore volume (porosity * cell volume) per active node, in MF6 reduced order.
    Saturation is applied at run time from the live NPF SAT array."""
    botm, _, _ = load_grid_data()
    idomain = sim.get_model("flow").dis.idomain.array
    vol = (delr * delc) * layer_thickness(botm)  # cell volume (ft^3)
    active = idomain.ravel() > 0
    return porosity * vol.ravel()[active]


def total_mass_in_storage(sim, species):
    """Dissolved mass (kg) of each species in the aquifer through time. Flow is
    steady, so the saturated thickness (from the water table) is constant."""
    botm, _, _ = load_grid_data()
    gwf = sim.get_model("flow")
    idomain = gwf.dis.idomain.array
    head = gwf.output.head().get_data()  # steady state
    thickness = layer_thickness(botm)
    sat_thick = thickness.astype(float).copy()
    sat_thick[0] = np.clip(head[0] - botm[0], 0.0, thickness[0])  # water table
    water_vol = porosity * (delr * delc) * sat_thick  # ft^3 of water / cell
    active = idomain > 0
    L_per_ft3 = 28.316846592
    times, mass = None, {}
    for s in species:
        cobj = sim.get_model(s).output.concentration()
        times = np.array(cobj.times) / 365.0
        calldata = cobj.get_alldata()  # (ntime, nlay, nrow, ncol)
        cmasked = np.where(active[None] & (calldata < 1.0e29), calldata, 0.0)
        # mg/L * ft^3 * (L/ft^3) = mg; / 1e6 -> kg
        mass[s] = (cmasked * water_vol[None]).sum(axis=(1, 2, 3)) * L_per_ft3 / 1.0e6
    return times, mass


# ---------------------------------------------------------------------------
# Build the coupled flow + one-GWT-per-species simulation
# ---------------------------------------------------------------------------
def build_prudic_simulation(
    workspace,
    mf6_exe,
    species,
    reaction_method="src_rhs",
    source_species="no3",
    source_time_series=None,
    slug_source_conc=50.0,
    total_time=9131.0,
    nstp=300,
):
    """Assemble one ``MFSimulation`` holding the GWF flow model and one GWT model
    per entry in ``species``, wired together with GWF-GWT exchanges and sharing a
    single transport solution.

    Parameters
    ----------
    workspace, mf6_exe : path-like
        Simulation workspace and the ``mf6`` executable.
    species : list of str
        Species model names, e.g. ``["no3", "no2", "n2"]``.
    reaction_method : {"src_rhs", "operator_split"}
        ``"src_rhs"`` adds a Mass Source Loading (SRC) package per species (one
        entry per active cell) that the callback overwrites each step;
        ``"operator_split"`` adds none.
    source_species : str
        Which species the lake supplies.
    source_time_series : list of (time, conc) or None
        Sustained lake source concentration as a time series; ``None`` releases a
        slug at ``slug_source_conc`` instead.
    slug_source_conc, total_time, nstp
        Slug source concentration, total simulation time, and number of transport
        time steps.
    """
    sustained = source_time_series is not None
    botm, idomain, lakibd = load_grid_data()

    sim = flopy.mf6.MFSimulation(
        sim_name="nitrate-nitrite", sim_ws=workspace, exe_name=str(mf6_exe)
    )
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(total_time, nstp, 1.0)],
        time_units=time_units,
    )

    gwf = _build_gwf(sim, botm, idomain, lakibd)
    gwts = [
        _build_gwt(
            sim,
            name,
            botm,
            lakibd,
            is_source=(name == source_species),
            reaction_method=reaction_method,
            sustained=sustained,
            source_time_series=source_time_series,
            slug_source_conc=slug_source_conc,
        )
        for name in species
    ]

    imsgwf = flopy.mf6.ModflowIms(
        sim,
        print_option="summary",
        outer_maximum=1000,
        inner_maximum=100,
        outer_dvclose=1.0e-3,
        inner_dvclose=1.0e-4,
        rcloserecord=[1.0e-3, "strict"],
        relaxation_factor=0.99,
        filename="flow.ims",
    )
    imsgwt = flopy.mf6.ModflowIms(
        sim,
        print_option="summary",
        outer_maximum=100,
        inner_maximum=100,
        outer_dvclose=1.0e-4,
        inner_dvclose=1.0e-5,
        rcloserecord=[1.0e-4, "strict"],
        under_relaxation="DBD",
        under_relaxation_theta=0.7,
        linear_acceleration="bicgstab",
        relaxation_factor=0.97,
        filename="trans.ims",
    )

    # register each model with its solution one at a time (a multi-model list to
    # register_ims_package silently drops all but the first model)
    sim.register_ims_package(imsgwf, gwf.name)
    for gwt in gwts:
        sim.register_ims_package(imsgwt, gwt.name)
        flopy.mf6.ModflowGwfgwt(
            sim,
            exgtype="GWF6-GWT6",
            exgmnamea=gwf.name,
            exgmnameb=gwt.name,
            filename=f"{gwf.name}_{gwt.name}.gwfgwt",
        )

    return sim


def _build_gwf(sim, botm, idomain, lakibd):
    name = "flow"
    gwf = flopy.mf6.ModflowGwf(sim, modelname=name, save_flows=True)
    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        length_units=length_units,
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=delr,
        delc=delc,
        top=top,
        botm=botm,
        idomain=idomain,
    )
    flopy.mf6.ModflowGwfnpf(
        gwf,
        save_specific_discharge=True,
        save_saturation=True,
        icelltype=[1] + 7 * [0],
        k=hk,
        k33=vk,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=50.0)
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{name}.hds",
        budget_filerecord=f"{name}.bud",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    flopy.mf6.ModflowGwfrcha(gwf, recharge={0: recharge}, pname="RCH-1")

    chdlist = []
    fpath = retrieve("chd.dat")
    for line in open(fpath).readlines():
        ll = line.strip().split()
        if len(ll) == 4:
            k, i, j, hd = ll
            chdlist.append([(int(k) - 1, int(i) - 1, int(j) - 1), float(hd)])
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chdlist, pname="CHD-1")

    idomain = dis.idomain.array
    lake_map = np.ones((nlay, nrow, ncol), dtype=np.int32) * -1
    lake_map[0, :, :] = lakibd[:, :] - 1
    idomain, lakepakdata_dict, lakeconnectiondata = flopy.mf6.utils.get_lak_connections(
        gwf.modelgrid, lake_map, idomain=idomain, bedleak=lakebed_leakance
    )
    gwf.dis.idomain.set_data(idomain[0], layer=0, multiplier=[1])
    lakpackagedata = [
        [0, 44.0, lakepakdata_dict[0], "lake1"],
        [1, 35.2, lakepakdata_dict[1], "lake2"],
    ]
    outlets = [[0, 0, -1, "MANNING", 44.5, 3.36493214532915, 0.03, 0.2187500e-02]]
    flopy.mf6.ModflowGwflak(
        gwf,
        time_conversion=86400.0,
        length_conversion=3.28081,
        print_stage=True,
        print_flows=True,
        stage_filerecord=name + ".lak.bin",
        budget_filerecord=name + ".lak.bud",
        mover=True,
        pname="LAK-1",
        boundnames=True,
        nlakes=len(lakpackagedata),
        noutlets=len(outlets),
        outlets=outlets,
        packagedata=lakpackagedata,
        connectiondata=lakeconnectiondata,
    )

    sfrpackagedata, sfrconnectiondata = get_stream_data()
    sfrperioddata = {0: [[0, "inflow", 86400], [18, "inflow", 8640.0]]}
    flopy.mf6.ModflowGwfsfr(
        gwf,
        print_stage=True,
        print_flows=True,
        stage_filerecord=name + ".sfr.bin",
        budget_filerecord=name + ".sfr.bud",
        mover=True,
        pname="SFR-1",
        time_conversion=86400.0,
        length_conversion=3.28081,
        boundnames=True,
        nreaches=len(sfrconnectiondata),
        packagedata=sfrpackagedata,
        connectiondata=sfrconnectiondata,
        perioddata=sfrperioddata,
    )
    flopy.mf6.ModflowGwfmvr(
        gwf,
        maxmvr=2,
        print_flows=True,
        budget_filerecord=name + ".mvr.bud",
        maxpackages=2,
        packages=[["SFR-1"], ["LAK-1"]],
        perioddata=[
            ["SFR-1", 5, "LAK-1", 0, "FACTOR", 1.0],
            ["LAK-1", 0, "SFR-1", 6, "FACTOR", 1.0],
        ],
    )
    return gwf


def _build_gwt(
    sim,
    name,
    botm,
    lakibd,
    is_source,
    reaction_method,
    sustained,
    source_time_series,
    slug_source_conc,
):
    """Build one GWT species model. is_source -> the lake supplies this species."""
    gwt = flopy.mf6.ModflowGwt(sim, modelname=name, save_flows=True)
    idomain = sim.get_model("flow").dis.idomain.array

    flopy.mf6.ModflowGwtdis(
        gwt,
        length_units=length_units,
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=delr,
        delc=delc,
        top=top,
        botm=botm,
        idomain=idomain,
    )
    flopy.mf6.ModflowGwtic(gwt, strt=0.0)
    flopy.mf6.ModflowGwtmst(gwt, porosity=porosity)
    flopy.mf6.ModflowGwtadv(gwt, scheme="TVD")
    flopy.mf6.ModflowGwtdsp(gwt, alh=alpha_l, ath1=alpha_th, ath2=alpha_tv)
    flopy.mf6.ModflowGwtssm(gwt, sources=[[]])

    # SRC package for the reaction terms (used only by the "src_rhs" method). One
    # entry per active cell; the API overwrites the loading rates each time step.
    if reaction_method == "src_rhs":
        srcdata = [[cid, 0.0] for cid in active_cellids(idomain)]
        flopy.mf6.ModflowGwtsrc(
            gwt,
            stress_period_data=srcdata,
            maxbound=len(srcdata),
            save_flows=True,
            pname="SRC-1",
        )

    # LKT: lake transport (the source species lives here)
    lake_strt = slug_source_conc if (is_source and not sustained) else 0.0
    lktpackagedata = [
        (0, lake_strt, 99.0, 999.0, "mylake1"),
        (1, lake_strt, 99.0, 999.0, "mylake2"),
    ]
    if is_source and sustained:
        # lake1 held at a time-varying concentration (a time series); lake2 held
        # at zero for the whole simulation
        lktperioddata = [
            (0, "STATUS", "CONSTANT"),
            (0, "CONCENTRATION", "lakeconc"),
            (1, "STATUS", "CONSTANT"),
            (1, "CONCENTRATION", 0.0),
        ]
    else:
        lktperioddata = [(0, "STATUS", "ACTIVE"), (1, "STATUS", "ACTIVE")]
    lkt = flopy.mf6.modflow.ModflowGwtlkt(
        gwt,
        boundnames=True,
        save_flows=True,
        print_concentration=True,
        concentration_filerecord=name + ".lkt.bin",
        budget_filerecord=name + ".lkt.bud",
        packagedata=lktpackagedata,
        lakeperioddata=lktperioddata,
        pname="LAK-1",
        auxiliary=["aux1", "aux2"],
    )
    if is_source and sustained:
        lkt.ts.initialize(
            filename=name + ".lkt.ts",
            timeseries=source_time_series,
            time_series_namerecord=["lakeconc"],
            interpolation_methodrecord=["linear"],
        )

    # SFT: stream transport
    sfrpackagedata, sfrconnectiondata = get_stream_data()
    nreach = len(sfrconnectiondata)
    sftpackagedata = [
        (irno, 0.0, 99.0, 999.0, f"myreach{irno + 1}") for irno in range(nreach)
    ]
    flopy.mf6.modflow.ModflowGwtsft(
        gwt,
        boundnames=True,
        save_flows=True,
        print_concentration=True,
        concentration_filerecord=name + ".sft.bin",
        budget_filerecord=name + ".sft.bud",
        packagedata=sftpackagedata,
        reachperioddata=[(0, "STATUS", "ACTIVE")],
        pname="SFR-1",
        auxiliary=["aux1", "aux2"],
    )
    flopy.mf6.modflow.ModflowGwtmvt(gwt, print_flows=True)

    flopy.mf6.ModflowGwtoc(
        gwt,
        budget_filerecord=f"{name}.bud",
        concentration_filerecord=f"{name}.ucn",
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("CONCENTRATION", "LAST"), ("BUDGET", "ALL")],
    )
    return gwt
