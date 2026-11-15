#!/usr/bin/env python
"""Build the synthetic-valley models on a Voronoi grid.

Each model is the structured model of the same kind moved onto the Voronoi
cells, for the valley or, with --variant coastal, the coastal valley. Most
inputs and boundaries come from the structured cell that contains each Voronoi
cell center. The hydraulic conductivity and the clay come from the truth
dataset in examples/data/synthetic-valley/data, and the land surface, the lake,
and where runoff goes come from the land surface raster there, in the same way
as in scripts/update_structured_models.py, which is run first. Layer 3 is
active only where the clay is. Both models start from their own steady-state
heads. Run inside the pixi environment, e.g.

    python scripts/build_vg_models.py --grid <dir with sv.disv>
"""

import argparse
import pathlib as pl
import shutil

import flopy
import numpy as np
import pandas as pd
import xarray as xr
from flopy.utils.gridintersect import GridIntersect
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString
from sv_surface import (
    LAKE,
    LAKE_EXTENT,
    LAKE_FLOOR,
    LAKE_K,
    LAKE_K33,
    LAKE_SY,
    Surface,
    drain_package,
    drain_rows,
    lake_package,
    mover_records,
    start_from_steady_state,
)
from update_structured_models import aquifer_storage

DATA_ROOT = pl.Path(__file__).resolve().parents[1] / "examples/data/synthetic-valley"
TRUTH = DATA_ROOT / "data/synthetic_valley_truth.nc"
WELL_INFO = DATA_ROOT / "data/obs_well_info.csv"
KINDS = ("base", "advanced")
VARIANTS = ("none", "coastal")
SEAWATER_CONCENTRATION = 35.0
# m, a reach shorter than this, where the stream clips a cell corner, is added
# to the reach below it
MIN_REACH_LENGTH = 5.0


class VoronoiMap:
    """A Voronoi grid, and the structured cell that contains each Voronoi cell center.

    ``grid`` and ``structured`` are the FloPy model grids of the two models.
    """

    def __init__(self, grid, structured):
        self.grid = grid
        self.ncpl = grid.ncpl
        self.xc, self.yc = grid.xcellcenters, grid.ycellcenters
        self.structured = structured
        self.nrow, self.ncol = structured.nrow, structured.ncol
        self.delr = float(structured.delr[0])
        self.delc = float(structured.delc[0])
        self.ylen = self.nrow * self.delc
        rc = np.array(
            [self.dis_rowcol(x, y) for x, y in zip(self.xc, self.yc, strict=True)]
        )
        self.ri, self.ci = rc[:, 0], rc[:, 1]

    def dis_rowcol(self, x, y):
        """(row, column) of the structured cell that contains a point.

        Many Voronoi cell centers are on the edge of the model, where FloPy's
        StructuredGrid.intersect() finds no cell, so the row and column are
        counted from the cell size.
        """
        i = min(max(int((self.ylen - y) // self.delc), 0), self.nrow - 1)
        j = min(max(int(x // self.delr), 0), self.ncol - 1)
        return i, j

    def dis_center(self, i, j):
        return self.structured.xcellcenters[i, j], self.structured.ycellcenters[i, j]

    def cell(self, x, y):
        """The Voronoi cell that contains a point."""
        return int(self.grid.intersect(x, y))

    def cell_at_dis(self, i, j):
        return self.cell(*self.dis_center(i, j))

    def layers(self, arr):
        """Values of a structured (layer, row, column) array at the Voronoi cells."""
        return np.array([arr[k][self.ri, self.ci] for k in range(arr.shape[0])])

    def coast(self):
        """The length of coastline, along the southern edge, in each cell on it."""
        xmin, xmax, _, _ = self.grid.extent
        hits = GridIntersect(self.grid).intersect(
            LineString([(xmin, 0.0), (xmax, 0.0)])
        )
        return {
            int(icpl): float(length)
            for icpl, length in zip(hits["cellids"], hits["lengths"], strict=True)
            if length > 0.0
        }


def truth_k(vmap, truth, nlay):
    """Hydraulic conductivity of the truth at the Voronoi cell centers.

    The logarithm of K is interpolated between the structured cell centers.
    """
    tx = truth["x"].values
    ty = truth["y"].values[::-1]
    pts = np.column_stack(
        [np.clip(vmap.yc, ty[0], ty[-1]), np.clip(vmap.xc, tx[0], tx[-1])]
    )
    k11 = np.empty((nlay, vmap.ncpl))
    for k in range(nlay):
        kt = truth[f"k1_layer{k + 1}"].values[::-1]
        # the truth has no K under its lake, so those cells take the nearest value
        missing = np.isnan(kt)
        if missing.any():
            _, (ii, jj) = distance_transform_edt(missing, return_indices=True)
            kt = kt[ii, jj]
        interp = RegularGridInterpolator((ty, tx), np.log10(kt))
        k11[k] = 10.0 ** interp(pts)
    return k11


def stream_reaches(vmap, gwf, first_cell, ncells):
    """(top y, bottom y, cell, length) of each stream reach, upstream first.

    The structured stream runs down the center of one column from the top of
    ``first_cell`` for ``ncells`` cells.
    """
    _, i0, j0 = first_cell
    x = (j0 + 0.5) * vmap.delr
    y_up = vmap.ylen - i0 * vmap.delc
    y_dn = vmap.ylen - (i0 + ncells) * vmap.delc
    res = GridIntersect(gwf.modelgrid).intersect(LineString([(x, y_up), (x, y_dn)]))
    reaches = []
    for cid, geom, length in zip(
        res["cellids"], res["ixshapes"], res["lengths"], strict=True
    ):
        if length > 1e-6:
            ys = [p[1] for p in geom.coords]
            reaches.append((max(ys), min(ys), int(cid), float(length)))
    reaches.sort(reverse=True)
    merged, carry = [], 0.0
    for yt, yb, icpl, length in reaches:
        if length < MIN_REACH_LENGTH:
            carry += length
            continue
        merged.append((yt, yb, icpl, length + carry))
        carry = 0.0
    return merged


def linear_in_y(vmap, cellids, values):
    """Straight-line fit, in the north-south direction, of a value at structured cell centers."""
    y = np.array([vmap.ylen - (c[1] + 0.5) * vmap.delc for c in cellids])
    return np.polyfit(y, values, 1)


def coastal_ghb(vmap, top, botm, idomain, k11, skip):
    """General-head boundary cells at sea level along the southern edge.

    The conductance per unit length of coastline is the structured models'.
    """
    flow_length = 0.5 * vmap.delc
    coast = vmap.coast()
    rows = []
    for k in range(botm.shape[0]):
        for icpl in sorted(coast):
            if icpl == skip or idomain[k, icpl] <= 0:
                continue
            cell_top = top[icpl] if k == 0 else botm[k - 1, icpl]
            cell_bot = botm[k, icpl]
            cond = k11[k, icpl] * coast[icpl] * (cell_top - cell_bot) / flow_length
            elevation = 0.5 * (min(cell_top, 0.0) + cell_bot)
            rows.append(
                ((k, icpl), 0.0, cond, elevation, SEAWATER_CONCENTRATION, "coast")
            )
    return rows


def head_obs(vmap, obs, wells):
    """Head observations: the observation wells at their surveyed locations,
    the others at the structured cell centers.

    ``wells`` lists each observation well by the row and column, counted from 1,
    of the structured cell it is in.
    """
    xy = wells.set_index(["row", "column"])
    continuous = {}
    for fname, rec in obs.continuous.get_data().items():
        if fname in ("sv.gwf.aq.csv", "sv.gwf.wt.csv"):
            continuous[fname] = []
            for name, cid in zip(rec["obsname"], rec["id"], strict=True):
                x, y = xy.loc[(cid[1] + 1, cid[2] + 1), ["x", "y"]]
                continuous[fname].append((name, "head", (cid[0], vmap.cell(x, y))))
        else:
            continuous[fname] = [
                (name, otype, (cid[0], vmap.cell_at_dis(cid[1], cid[2])))
                for name, otype, cid in zip(
                    rec["obsname"], rec["obstype"], rec["id"], strict=True
                )
            ]
    return continuous


def layered(arr):
    """Values by layer, with a single number for a layer that has one value."""
    return [a.flat[0].item() if np.all(a == a.flat[0]) else a for a in arr]


def period_values(data, nper, fields):
    """The value of each field in each stress period, for input that is the same
    in every cell; a period without input keeps the previous period's values."""
    values = {f: [] for f in fields}
    current = None
    for kper in range(nper):
        if kper in data:
            d = data[kper]
            current = {}
            for f in fields:
                # FloPy may read a value that could name a time series as text
                u = np.unique(d[f].astype(float))
                if u.size != 1:
                    raise ValueError(f"{f} varies between cells in period {kper + 1}")
                current[f] = float(u[0])
        for f in fields:
            values[f].append(current[f])
    return values


def stepwise_ts(package, filename, sim_s, series):
    """Add a time series that holds each value constant through its stress period."""
    perlen = sim_s.tdis.perioddata.array["perlen"]
    times = np.concatenate([[0.0], np.cumsum(perlen)])
    names = list(series)
    rows = []
    for n, t in enumerate(times):
        kper = min(n, len(perlen) - 1)
        rows.append((float(t), *(series[name][kper] for name in names)))
    package.ts.initialize(
        filename=filename,
        timeseries=rows,
        time_series_namerecord=names,
        interpolation_methodrecord=["stepwise"] * len(names),
    )


def wel_spd(vmap, wel):
    """Pumping well input with each well at the center of its structured cell."""
    spd = {}
    for kper, d in wel.stress_period_data.get_data().items():
        rows = []
        for r in d:
            c = r["cellid"]
            row = [(c[0], vmap.cell_at_dis(c[1], c[2])), r["q"]]
            if "boundname" in d.dtype.names:
                row.append(r["boundname"])
            rows.append(tuple(row))
        spd[kper] = rows
    return spd


def model_name(kind, variant, grid="vg"):
    """The folder name of a model: synthetic-valley[-coastal][-vg]-<kind>-annual."""
    parts = ["synthetic-valley"] + ([variant] if variant == "coastal" else [])
    parts += [grid] if grid else []
    return "-".join(parts + [kind, "annual"])


def build(kind, grid_ws, dest, variant):
    src = DATA_ROOT / model_name(kind, variant, grid=None)
    coastal = variant == "coastal"
    sim_s = flopy.mf6.MFSimulation.load(sim_ws=src, verbosity_level=0)
    s = sim_s.get_model()
    dis = s.dis
    nlay = dis.nlay.data
    grid_model = flopy.mf6.MFSimulation.load(
        sim_ws=grid_ws, verbosity_level=0, load_only=["disv"]
    ).get_model()
    vertices = grid_model.disv.vertices.array
    cell2d = grid_model.disv.cell2d.array
    vmap = VoronoiMap(grid_model.modelgrid, s.modelgrid)
    truth = xr.open_dataset(TRUTH)
    wells = pd.read_csv(WELL_INFO)

    surface = Surface()
    members = surface.members(vmap.grid)
    top, lake, bed = surface.cells(members)
    botm = vmap.layers(dis.botm.array)
    idomain = vmap.layers(dis.idomain.array)
    idomain[0] = 1
    # layer 3 is the clay; where there is no clay its cells pass water straight
    # between layers 2 and 4
    clay = truth["clay_location"].values[vmap.ri, vmap.ci] == 1
    idomain[2, ~clay] = -1
    # MODFLOW 6 starts layer 4 at the bottom of layer 3, so a pass-through cell
    # takes the bottom of layer 2 and has no thickness
    botm[2, ~clay] = botm[1, ~clay]

    k11 = truth_k(vmap, truth, nlay)
    k11[2, clay] = truth["clay_kv"].values[vmap.ri, vmap.ci][clay]
    k33 = vmap.layers(s.npf.k33.array)
    k_s = s.npf.k.array[0]
    k33[0] = float(np.median(s.npf.k33.array[0][k_s < 0.1 * LAKE_K]))
    icelltype = np.zeros((nlay, vmap.ncpl), dtype=int)
    icelltype[0] = 1
    shape_s = s.sto.sy.array.shape
    iconvert, ss, sy = (
        vmap.layers(a.reshape(shape_s))
        for a in aquifer_storage(s.sto, vmap.nrow, vmap.ncol)
    )
    if kind == "base":
        # the top of the lake cells is the lake surface at its highest level
        top[lake] = LAKE_EXTENT
        k11[0, lake], k33[0, lake] = LAKE_K, LAKE_K33
        # the lake cells are treated as always saturated; with their very high
        # hydraulic conductivity, letting their saturated thickness follow the
        # head makes the steady-state solution fail to converge
        icelltype[0, lake] = 0
        # the lake cells store water as open water does, with no compressibility
        sy[0, lake], ss[0, lake] = LAKE_SY, 0.0
        to_layer2 = np.zeros(vmap.ncpl, dtype=bool)
    else:
        # the lake sits on the aquifer; where its bed is at the bottom of layer
        # 1, layer 1 has no thickness and passes water straight to layer 2
        to_layer2 = lake & (bed - LAKE_FLOOR <= 1.0e-6)
        to_layer1 = lake & ~to_layer2
        top[to_layer1] = bed[to_layer1]
        top[to_layer2] = LAKE_FLOOR
        idomain[0, to_layer2] = -1

    # no FloPy header lines, so a rebuild changes only the files whose input
    # changes
    sim = flopy.mf6.MFSimulation(
        sim_name="sv", sim_ws=dest, memory_print_option=None, write_headers=False
    )
    # write more digits than FloPy's default, which would round the structured
    # models' stress values
    sim.simulation_data.float_precision = 12
    sim.simulation_data.float_characters = 20
    flopy.mf6.ModflowTdis(
        sim,
        time_units="days",
        nper=sim_s.tdis.nper.data,
        perioddata=sim_s.tdis.perioddata.array.tolist(),
    )
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname="sv", save_flows=True, newtonoptions="under_relaxation"
    )
    flopy.mf6.ModflowGwfdisv(
        gwf,
        length_units="meters",
        nlay=nlay,
        ncpl=vmap.ncpl,
        nvert=len(vertices),
        top=top,
        botm=layered(botm),
        idomain=layered(idomain),
        vertices=vertices.tolist(),
        cell2d=cell2d.tolist(),
    )
    flopy.mf6.ModflowGwfic(gwf, strt=vmap.layers(s.ic.strt.array))
    flopy.mf6.ModflowGwfnpf(
        gwf,
        save_specific_discharge=True,
        k33overk=True,
        icelltype=layered(icelltype),
        k=k11,
        k33=layered(k33),
    )
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=layered(iconvert),
        ss=layered(ss),
        sy=layered(sy),
        steady_state={0: True},
        transient={1: True},
    )

    kv = k11[0] * k33[0]
    if kind == "advanced":
        outlet, note = build_advanced_boundaries(
            vmap,
            sim_s,
            gwf,
            surface,
            members,
            lake,
            to_layer2,
            top,
            botm[0],
            kv,
            coastal,
        )
    else:
        outlet, note = build_base_boundaries(vmap, sim_s, gwf, lake, top, botm[0], kv)

    flopy.mf6.ModflowGwfwel(
        gwf,
        pname="prediction",
        filename="sv.prediction.well",
        stress_period_data=wel_spd(vmap, s.get_package("prediction")),
    )
    ghb = coastal_ghb(vmap, top, botm, idomain, k11, outlet) if coastal else []
    if coastal:
        flopy.mf6.ModflowGwfghb(
            gwf,
            pname="ghb-1",
            auxiliary=["ELEVATION", "CONCENTRATION"],
            boundnames=True,
            print_flows=True,
            stress_period_data={0: ghb},
            observations={
                "sv.ghb.obs.csv": [("coast-swgw", "ghb", "coast")],
                "filename": "sv.ghb.obs",
            },
        )
    # the head observations, not the observations of a boundary package
    obs_s = [
        p
        for p in s.packagelist
        if p.package_type == "obs" and "sv.gwf.aq.csv" in p.continuous.get_data()
    ][0]
    flopy.mf6.ModflowUtlobs(
        gwf,
        pname=obs_s.package_name,
        filename=pl.Path(obs_s.filename).name,
        print_input=True,
        continuous=head_obs(vmap, obs_s, wells),
    )
    flopy.mf6.ModflowGwfoc(gwf)

    if dest.exists():
        shutil.rmtree(dest)
    sim.write_simulation(silent=True)
    # the time steps, solver settings, and output settings are the structured
    # model's
    for name in ("sv.tdis", "sv.ims", "sv.oc"):
        shutil.copy(src / name, dest / name)
    note += "; " + start_from_steady_state(dest)
    print(
        f"{dest.name}: {vmap.ncpl} cells per layer, {len(ghb)} GHB cells, "
        f"{lake.sum()} lake cells; {note}"
    )


def seepage_drains(vmap, gwf, top, bottom, kv, lake, stream, mover):
    """Seepage drains on the land cells away from the lake and the stream.

    Returns the cells with a drain.
    """
    land = ~lake
    land[list(stream)] = False
    cells = [int(icpl) for icpl in np.nonzero(land)[0]]
    area = vmap.grid.area[cells]
    rows = drain_rows(
        [(0, icpl) for icpl in cells], top[cells], bottom[cells], kv[cells], area
    )
    drain_package(gwf, rows, mover)
    return cells


def build_advanced_boundaries(
    vmap, sim_s, gwf, surface, members, lake, to_layer2, top, bottom, kv, coastal
):
    """Stream, lake, unsaturated zone, drain, Water Mover, and multi-aquifer well
    input; returns the cell where the stream leaves the model and a summary."""
    s = sim_s.get_model()
    sfr_s = s.sfr.packagedata.array
    reaches = stream_reaches(vmap, gwf, sfr_s["cellid"][0], len(sfr_s))
    rtp_fit = linear_in_y(vmap, sfr_s["cellid"], sfr_s["rtp"])
    # the slope of the stream, from the straight-line fit of its streambed
    rgrd = float(rtp_fit[0])
    r0 = sfr_s[0]
    nreach = len(reaches)
    packagedata = []
    for n, (yt, yb, icpl, length) in enumerate(reaches):
        packagedata.append(
            (
                n,
                (0, icpl),
                length,
                r0["rwid"],
                rgrd,
                float(np.polyval(rtp_fit, 0.5 * (yt + yb))),
                r0["rbth"],
                r0["rhk"],
                r0["man"],
                1 if n in (0, nreach - 1) else 2,
                1.0,
                0,
                "riv",
            )
        )
    connectiondata = (
        [[0, -1]]
        + [[n, n - 1, -(n + 1)] for n in range(1, nreach - 1)]
        + [[nreach - 1, nreach - 2]]
    )
    # the stream flow observation goes at the downstream end of the same
    # structured reach (reaches in the observation file are numbered from 1)
    sfr_obs = s.sfr.obs.continuous.get_data()["sv.sfr.obs.csv"]
    iobs = int(sfr_obs["id"][1]) - 1
    y_obs = vmap.ylen - (sfr_s["cellid"][iobs][1] + 1) * vmap.delc
    iobs = int(np.argmin([abs(r[1] - y_obs) for r in reaches]))
    flopy.mf6.ModflowGwfsfr(
        gwf,
        pname="sfr-1",
        boundnames=True,
        save_flows=True,
        mover=True,
        unit_conversion=86400.0,
        nreaches=nreach,
        packagedata=packagedata,
        connectiondata=connectiondata,
        observations={
            "sv.sfr.obs.csv": [
                ("riv-swgw", "sfr", "riv"),
                ("riv-flow", "downstream-flow", (iobs,)),
            ],
            "filename": "sv.sfr.obs",
        },
    )

    # the lake sits on the aquifer and leaks through its bed to the cells under
    # it
    lak_s = s.lak
    bedleak = float(lak_s.connectiondata.array["bedleak"][0])
    pdata = lak_s.packagedata.array[0]
    connections = [
        ((1 if to_layer2[icpl] else 0, int(icpl)), bedleak)
        for icpl in np.nonzero(lake)[0]
    ]
    lake_package(
        gwf,
        connections,
        float(pdata["strt"]),
        pdata["boundname"],
        dict(lak_s.perioddata.get_data().items()),
        surface.stage_table(),
    )

    # an unsaturated zone (UZF) cell on every land cell, with the properties of
    # the nearest structured UZF cell
    uz_s = s.uzf.packagedata.array
    uz_xy = np.array([vmap.dis_center(int(c[1]), int(c[2])) for c in uz_s["cellid"]])
    uz_cells = [int(icpl) for icpl in np.nonzero(~lake)[0]]
    packagedata = []
    for n, icpl in enumerate(uz_cells):
        m = int(
            np.argmin(
                (uz_xy[:, 0] - vmap.xc[icpl]) ** 2 + (uz_xy[:, 1] - vmap.yc[icpl]) ** 2
            )
        )
        r = uz_s[m]
        # no UZF cell below this one (-1, written to the file as 0)
        packagedata.append(
            (
                n,
                (0, icpl),
                r["landflag"],
                -1,
                r["surfdep"],
                r["vks"],
                r["thtr"],
                r["thts"],
                r["thti"],
                r["eps"],
            )
        )
    # every cell has the same rates, so the cells are listed once and the rates
    # that change from year to year come from a time series
    fields = ("finf", "pet", "extdp", "extwc", "ha", "hroot", "rootact")
    values = period_values(s.uzf.perioddata.get_data(), sim_s.tdis.nper.data, fields)
    series = {}
    row = []
    for f in fields:
        if len(set(values[f])) > 1:
            series[f"uzf_{f}"] = values[f]
            row.append(f"uzf_{f}")
        else:
            row.append(values[f][0])
    perioddata = {0: [(n, *row) for n in range(len(uz_cells))]}
    uzf = flopy.mf6.ModflowGwfuzf(
        gwf,
        pname="uzf-1",
        mover=True,
        simulate_et=True,
        nuzfcells=len(packagedata),
        ntrailwaves=s.uzf.ntrailwaves.data,
        nwavesets=s.uzf.nwavesets.data,
        packagedata=packagedata,
        perioddata=perioddata,
    )
    stepwise_ts(uzf, "sv.uzf.ts", sim_s, series)
    # the runoff of each UZF cell goes where it drains over the land surface: the
    # lake, a stream reach, or out of the model at the coast
    reach_cells = {icpl: n for n, (_, _, icpl, _) in enumerate(reaches)}
    coast = vmap.coast() if coastal else {}
    outlet = surface.runoff_outlets(members, lake, reach_cells, coast)
    mvr_s = s.mvr.perioddata.get_data(0)[0]
    mvr = [
        ("uzf-1", *r)
        for r in mover_records(
            uz_cells, outlet, mvr_s["mvrtype"], float(mvr_s["value"])
        )
    ]
    to_lake = sum(r[2] == LAKE for r in mvr)
    note = (
        f"{to_layer2.sum()} connected to layer 2; {len(uz_cells)} UZF cells; runoff "
        f"from {to_lake} to the lake, {len(mvr) - to_lake} to the stream, "
        f"{len(uz_cells) - len(mvr)} to the coast"
    )
    # groundwater that seeps out at the land surface goes where the runoff of
    # its cell goes
    drains = seepage_drains(vmap, gwf, top, bottom, kv, lake, reach_cells, mover=True)
    drn = [("drn-1", *r) for r in mover_records(drains, outlet, "FACTOR", 1.0)]
    note += f"; {len(drains)} drains, {len(drn)} moved to the lake or the stream"
    flopy.mf6.ModflowGwfmvr(
        gwf,
        maxmvr=len(mvr) + len(drn),
        maxpackages=4,
        packages=[["uzf-1"], ["lak-1"], ["sfr-1"], ["drn-1"]],
        perioddata={0: mvr + drn},
    )

    maw_cd = []
    for r in s.maw.connectiondata.array:
        k, i, j = r["cellid"]
        maw_cd.append(
            (
                r["ifno"],
                r["icon"],
                (k, vmap.cell_at_dis(i, j)),
                r["scrn_top"],
                r["scrn_bot"],
                r["hk_skin"],
                r["radius_skin"],
            )
        )
    flopy.mf6.ModflowGwfmaw(
        gwf,
        pname="pwell",
        boundnames=True,
        nmawwells=s.maw.nmawwells.data,
        packagedata=s.maw.packagedata.array.tolist(),
        connectiondata=maw_cd,
        perioddata=dict(s.maw.perioddata.get_data().items()),
    )
    return reaches[-1][2], note


def build_base_boundaries(vmap, sim_s, gwf, lake, top, bottom, kv):
    """Recharge, evapotranspiration, river, drain, and pumping well input; returns
    the cell where the stream leaves the model and a summary."""
    s = sim_s.get_model()
    nper = sim_s.tdis.nper.data

    # recharge is the same everywhere on the land and everywhere on the lake, so
    # each cell takes the time series of the land or the lake
    rch_data = s.get_package("rch").stress_period_data.get_data()
    series = {}
    for b in ("lake", "land"):
        by_zone = {kper: d[d["boundname"] == b] for kper, d in rch_data.items()}
        series[f"rch_{b}"] = period_values(by_zone, nper, ("recharge",))["recharge"]
    rch_spd = []
    for icpl in range(vmap.ncpl):
        b = "lake" if lake[icpl] else "land"
        rch_spd.append(((0, icpl), f"rch_{b}", b))
    rch = flopy.mf6.ModflowGwfrch(
        gwf,
        pname="rch_0",
        boundnames=True,
        maxbound=vmap.ncpl,
        stress_period_data={0: rch_spd},
    )
    stepwise_ts(rch, "sv.rch.ts", sim_s, series)

    # lake evaporation, on the lake cells
    evt_data = s.get_package("evt").stress_period_data.get_data()
    values = period_values(evt_data, nper, ("surface", "rate", "depth"))
    evt_spd = [
        ((0, int(icpl)), values["surface"][0], "evt_rate", values["depth"][0])
        for icpl in np.nonzero(lake)[0]
    ]
    evt = flopy.mf6.ModflowGwfevt(
        gwf,
        pname="evt_0",
        maxbound=len(evt_spd),
        stress_period_data={0: evt_spd},
    )
    stepwise_ts(evt, "sv.evt.ts", sim_s, {"evt_rate": values["rate"]})

    # river stage, river bottom, and conductance per meter of river from the
    # structured river cells
    riv_s = s.riv.stress_period_data.get_data(0)
    reaches = stream_reaches(vmap, gwf, riv_s["cellid"][0], len(riv_s))
    stage_fit = linear_in_y(vmap, riv_s["cellid"], riv_s["stage"])
    rbot_fit = linear_in_y(vmap, riv_s["cellid"], riv_s["rbot"])
    cond_per_length = float(riv_s["cond"][0]) / vmap.delc
    riv_spd = []
    for yt, yb, icpl, length in reaches:
        y = 0.5 * (yt + yb)
        riv_spd.append(
            (
                (0, icpl),
                float(np.polyval(stage_fit, y)),
                cond_per_length * length,
                float(np.polyval(rbot_fit, y)),
                "riv",
            )
        )
    flopy.mf6.ModflowGwfriv(
        gwf,
        pname="riv-1",
        boundnames=True,
        print_flows=True,
        stress_period_data={0: riv_spd},
        observations={
            "sv.riv.obs.csv": [("riv-swgw", "riv", "riv")],
            "filename": "sv.riv.obs",
        },
    )

    flopy.mf6.ModflowGwfwel(
        gwf,
        pname="pwell",
        filename="sv.pwell.wel",
        boundnames=True,
        stress_period_data=wel_spd(vmap, s.get_package("pwell")),
    )
    stream = [icpl for _, _, icpl, _ in reaches]
    drains = seepage_drains(vmap, gwf, top, bottom, kv, lake, stream, mover=False)
    return reaches[-1][2], f"{len(evt_spd)} EVT cells; {len(drains)} drains"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--grid",
        type=pl.Path,
        default=DATA_ROOT / "synthetic-valley-vg-advanced-annual",
        help="model directory whose sv.disv holds the Voronoi grid",
    )
    parser.add_argument("--kind", choices=KINDS, nargs="+", default=list(KINDS))
    parser.add_argument("--variant", choices=VARIANTS, default="none")
    parser.add_argument(
        "--dest",
        type=pl.Path,
        default=DATA_ROOT,
        help="directory to write the models in (default: the repository data)",
    )
    args = parser.parse_args(argv)
    for kind in args.kind:
        dest = args.dest / model_name(kind, args.variant)
        build(kind, args.grid, dest, args.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
