"""Land surface, lake, and runoff paths shared by the synthetic-valley model builders.

The land surface and lake bed come from a grid of 15.24 m cells (a raster)
written by scripts/build_topography.py. Each model cell is described by the
raster cells whose centers fall inside it: the top of the model cell is their
mean elevation, the model cell is part of the lake where at least half of them
are under water when the lake is at LAKE_EXTENT, and its runoff goes where most
of them drain over the land surface.
"""

import heapq
import pathlib as pl
import shutil
import subprocess
import tempfile
from collections import Counter

import flopy
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.path import Path
from scipy import ndimage

DATA_ROOT = pl.Path(__file__).resolve().parents[1] / "examples/data/synthetic-valley"
TOPOGRAPHY = DATA_ROOT / "data/synthetic_valley_topography.nc"
LAKE, STREAM, COAST = "lak-1", "sfr-1", "coast"
# m, the bottom of layer 1; the deepest part of the lake bed is flat at this
# elevation
LAKE_FLOOR = -1.524
# m, the lake level that sets which cells are lake cells; it is the highest the
# lake reaches in the advanced models
LAKE_EXTENT = 6.5
# m, the lake level at which the lake would spill over the ridge to the south;
# the table of lake volume and area runs from LAKE_FLOOR to this level
SPILL = 14.96
# m, the lake level interval of that table
TABLE_STEP = 0.1524
# m/d, the horizontal hydraulic conductivity of the base models' lake cells,
# high enough to keep the lake surface flat, and the ratio of vertical to
# horizontal hydraulic conductivity in them
LAKE_K, LAKE_K33 = 609600.0, 2000000.0
# m, the models start from their steady-state heads, each changed by a random
# amount between -START_OFFSET and START_OFFSET, so a run does not begin at the
# answer; START_SEED makes the random amounts the same on every rebuild
START_OFFSET = 0.1
START_SEED = 20261112
# m, heads at or above this mark dry or inactive cells
HDRY = 1.0e20
# m (0.5 ft), the depth below the land surface at which a seepage drain starts
# to remove groundwater; it removes water at its full rate once the water table
# reaches the land surface
DRAIN_DEPTH = 0.1524
# the base models' recharge on the land is the advanced models' infiltration
# minus their potential evapotranspiration, times this factor; the factor puts
# the structured base model's steady-state heads at the observation wells about
# 0.27 m below the true heads on average, as they were before the land surface
# raster was used
BASE_RECHARGE_SCALE = 2.08


def drainage(top, neighbors, outlets):
    """Follow water downhill over the land surface to where it leaves.

    ``top`` is the land surface elevation of each cell, ``neighbors[n]`` lists
    the (cell, distance) pairs next to cell n, and ``outlets`` maps each cell
    where water leaves the land surface (the lake, a stream reach, or the coast)
    to its (package, id, elevation). Returns the (package, id) that each cell
    drains to and the downhill neighbor of each cell (-1 at an outlet).
    """
    ncell = len(top)
    # fill closed depressions so every cell has a downhill path to an outlet:
    # work up from the outlets, lowest first, and remember which cell each cell
    # was reached from, which gives a path across flat ground
    filled = np.array(top, dtype=float)
    parent = np.full(ncell, -1)
    reached = np.zeros(ncell, dtype=bool)
    heap = []
    for n, (_, _, z) in outlets.items():
        reached[n] = True
        filled[n] = z
        heapq.heappush(heap, (z, n))
    while heap:
        z, n = heapq.heappop(heap)
        for m, _ in neighbors[n]:
            if not reached[m]:
                reached[m] = True
                filled[m] = max(top[m], z)
                parent[m] = n
                heapq.heappush(heap, (filled[m], m))

    # each cell drains to its steepest downhill neighbor, or, on flat ground,
    # to the cell it was reached from
    downslope = parent.copy()
    for n in range(ncell):
        if n in outlets:
            downslope[n] = -1
            continue
        steepest = 0.0
        for m, dist in neighbors[n]:
            slope = (filled[n] - filled[m]) / dist
            if slope > steepest + 1.0e-12:
                steepest = slope
                downslope[n] = m

    # follow each cell's path downhill to its outlet
    outlet = [None] * ncell
    for n in range(ncell):
        path = []
        m = n
        while outlet[m] is None and downslope[m] >= 0:
            path.append(m)
            m = downslope[m]
        found = outlet[m] if outlet[m] is not None else outlets[m][:2]
        outlet[m] = found
        for p in path:
            outlet[p] = found
    return outlet, downslope


def structured_neighbors(nrow, ncol, delr):
    """The eight cells around each cell of a regular grid, and their distances."""
    neighbors = []
    for i in range(nrow):
        for j in range(ncol):
            cells = []
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    a, b = i + di, j + dj
                    if (di or dj) and 0 <= a < nrow and 0 <= b < ncol:
                        cells.append((a * ncol + b, delr * np.hypot(di, dj)))
            neighbors.append(cells)
    return neighbors


class Surface:
    """The land surface and lake bed raster, and how the model cells sit on it."""

    def __init__(self, path=TOPOGRAPHY):
        ds = xr.open_dataset(path)
        self.z = ds["elevation"].values.astype(float)
        self.nrow, self.ncol = self.z.shape
        self.cell = float(ds["x"].values[1] - ds["x"].values[0])
        xx, yy = np.meshgrid(ds["x"].values, ds["y"].values)
        self.points = np.column_stack([xx.ravel(), yy.ravel()])
        # the flat deepest part of the lake bed, where the lake starts to fill;
        # its elevation is set to the bottom of layer 1 exactly, since the file
        # stores it with fewer digits
        self.floor = self.z <= LAKE_FLOOR + 1.0e-6
        self.z[self.floor] = LAKE_FLOOR

    def flooded(self, stage):
        """Raster cells under water when the lake level is ``stage``.

        Only low ground connected to the lake floor is flooded, not other
        depressions below that level.
        """
        label, _ = ndimage.label(self.z < stage)
        ids = np.unique(label[self.floor])
        return np.isin(label, ids[ids > 0])

    def members(self, modelgrid):
        """The raster cells whose centers fall inside each cell of a FloPy model
        grid, layer 1 cells numbered row by row on a structured grid.

        A model cell too small to hold a raster cell center takes the raster
        cell nearest to the middle of its corners.
        """
        x, y = self.points[:, 0], self.points[:, 1]
        members = []
        for n in range(modelgrid.ncpl):
            p = np.array(modelgrid.get_cell_vertices(n))
            near = np.nonzero(
                (x >= p[:, 0].min())
                & (x <= p[:, 0].max())
                & (y >= p[:, 1].min())
                & (y <= p[:, 1].max())
            )[0]
            m = near[Path(p).contains_points(self.points[near])]
            if m.size == 0:
                c = p.mean(axis=0)
                m = np.array([np.argmin((x - c[0]) ** 2 + (y - c[1]) ** 2)])
            members.append(m)
        return members

    def cells(self, members):
        """The top of each model cell, whether it is a lake cell, and its lake bed.

        The lake bed is the mean elevation of the part of the cell under water,
        no lower than the bottom of layer 1, and NaN outside the lake.
        """
        z = self.z.ravel()
        water = self.flooded(LAKE_EXTENT).ravel()
        top = np.array([z[m].mean() for m in members])
        lake = np.array([water[m].mean() >= 0.5 for m in members])
        bed = np.full(len(members), np.nan)
        for n in np.nonzero(lake)[0]:
            m = members[n]
            bed[n] = max(z[m[water[m]]].mean(), LAKE_FLOOR)
        return top, lake, bed

    def stage_table(self):
        """Lake volume and surface area at each lake level, from the lake floor
        to the level at which the lake would spill over the ridge.

        Each row is (lake level, volume, area), in m, m3, and m2.
        """
        area = self.cell * self.cell
        rows = []
        for stage in np.round(np.arange(LAKE_FLOOR, SPILL + 1.0e-6, TABLE_STEP), 4):
            f = self.flooded(stage)
            rows.append(
                (
                    float(stage),
                    float(np.sum(stage - self.z[f]) * area),
                    float(f.sum() * area),
                )
            )
        return rows

    def runoff_outlets(self, members, lake, reaches, coast):
        """Where the runoff of each model cell goes: the lake, a stream reach, or
        the coast, as (package, id).

        ``lake`` marks the lake cells, ``reaches`` maps a model cell to its
        stream reach, and ``coast`` lists the cells along the coast. A model
        cell's runoff goes where most of its raster cells drain.
        """
        z = self.z.ravel()
        outlets = {}
        for n in np.nonzero(lake)[0]:
            for f in members[n]:
                outlets[f] = (LAKE, 0, z[f])
        for n, ifno in reaches.items():
            for f in members[n]:
                outlets[f] = (STREAM, ifno, z[f])
        for n in coast:
            for f in members[n]:
                outlets.setdefault(f, (COAST, 0, z[f]))
        neighbors = structured_neighbors(self.nrow, self.ncol, self.cell)
        outlet, _ = drainage(z, neighbors, outlets)
        return [Counter(outlet[f] for f in m).most_common(1)[0][0] for m in members]


def mover_records(cells, outlet, mvrtype, value):
    """Water Mover rows that send each cell's water to the lake or stream.

    Each row is (cell number in the sending package, receiving package, lake or
    reach number, how the amount is set, amount). Water that drains to the
    coast is not moved and leaves the model.
    """
    return [
        (n, outlet[cell][0], outlet[cell][1], mvrtype, value)
        for n, cell in enumerate(cells)
        if outlet[cell][0] != COAST
    ]


def drain_rows(cellids, top, bottom, kv, area):
    """Drain rows that remove groundwater seeping out at the land surface.

    Each row is (cell, elevation, conductance, depth, name). A drain starts to
    remove water when the water table is DRAIN_DEPTH below the land surface.
    Its conductance is the vertical hydraulic conductivity of layer 1 times the
    cell area, divided by the thickness of layer 1.
    """
    return [
        (cellid, t - DRAIN_DEPTH, k * a / (t - b), DRAIN_DEPTH, "seepage")
        for cellid, t, b, k, a in zip(cellids, top, bottom, kv, area, strict=True)
    ]


def drain_package(gwf, rows, mover):
    """Drain package whose drains remove water gradually over DRAIN_DEPTH.

    With ``mover``, the drains pass their water to the Water Mover.
    """
    return flopy.mf6.ModflowGwfdrn(
        gwf,
        pname="drn-1",
        filename="sv.drn",
        auxiliary=["DDRN"],
        auxdepthname="DDRN",
        boundnames=True,
        mover=mover,
        maxbound=len(rows),
        stress_period_data={0: rows},
    )


def lake_package(gwf, connections, strt, boundname, perioddata, table):
    """Lake package for one lake that leaks through its bed to the cells beneath it.

    ``connections`` lists each cell under the lake and the leakance of the lake
    bed there, and ``table`` the lake volume and area at each lake level.
    """
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="lak-1",
        boundnames=True,
        print_input=True,
        print_stage=True,
        stage_filerecord="sv.lak.hds",
        mover=True,
        nlakes=1,
        ntables=1,
        packagedata=[(0, strt, len(connections), boundname)],
        connectiondata=[
            (0, n, cellid, "vertical", bedleak, 0.0, 0.0, 0.0, 0.0)
            for n, (cellid, bedleak) in enumerate(connections)
        ],
        tables=[(0, "sv.lak.tab")],
        perioddata=perioddata,
        observations={
            "sv.lake.obs.csv": [
                ("lake-stage", "stage", boundname),
                ("lake-swgw", "lak", boundname),
            ],
            "filename": "sv.lak.obs",
        },
    )
    flopy.mf6.ModflowUtllaktab(
        gwf, filename="sv.lak.tab", nrow=len(table), ncol=3, table=table
    )
    return lak


def run(ws):
    """Run the model in ``ws`` and stop with its message if it fails."""
    result = subprocess.run(["mf6"], cwd=ws, capture_output=True, text=True)
    if "Normal termination" not in result.stdout:
        raise RuntimeError(f"{ws.name} failed:\n{result.stdout[-2000:]}")


def start_from_steady_state(ws):
    """Set the starting heads to the model's own steady-state heads.

    Each head is changed by a random amount of up to START_OFFSET, and an
    advanced model's lake starts at its steady-state level. The model runs in a
    temporary copy, so no output files are left in ``ws``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = pl.Path(tmp) / ws.name
        shutil.copytree(ws, out)
        run(out)
        head = flopy.utils.HeadFile(out / "sv.hds").get_data(idx=0)
        stage_file = out / "sv.lake.obs.csv"
        stages = pd.read_csv(stage_file) if stage_file.exists() else None
    sim = flopy.mf6.MFSimulation.load(
        sim_ws=ws,
        verbosity_level=0,
        load_only=["dis", "disv", "ic", "lak"],
        write_headers=False,
    )
    sim.simulation_data.float_precision = 12
    sim.simulation_data.float_characters = 20
    gwf = sim.get_model()
    strt = gwf.ic.strt.array
    head = head.reshape(strt.shape)
    valid = np.abs(head) < HDRY
    rng = np.random.default_rng(START_SEED)
    offset = rng.uniform(-START_OFFSET, START_OFFSET, strt.shape)
    gwf.ic.strt = np.where(valid, head + offset, strt)
    gwf.ic.write()
    note = f"starting heads from steady state, +/-{START_OFFSET} m"
    lak = gwf.get_package("lak")
    if lak is not None:
        stage = stages["LAKE-STAGE"].iloc[0]
        pdata = lak.packagedata.array.copy()
        pdata["strt"] = stage
        lak.packagedata = pdata
        lak.write()
        note += f", lake stage {stage:.4f} m"
    return note
