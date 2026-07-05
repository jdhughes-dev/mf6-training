"""Shared setup and helpers for the mesh-generation notebooks.

The three mesh-generation notebooks (gridgen, rectilinear, triangle-voronoi)
build different grids over the SAME watershed, so they share the problem extent,
the fine topographic raster, the boundary/stream geometry, and three helpers that
sample topography onto a grid, flag the cells the river crosses, and draw the
boundary and streams. That shared setup lives here so each notebook imports it
instead of repeating ~40 identical lines. Import from the notebook working
directory (examples/notebooks) so the ``../data`` path resolves.
"""

import json
import pathlib as pl

import flopy
import numpy as np
from notebook_helpers import string2geom
from shapely.geometry import LineString

# problem extent and display settings
Lx, Ly = 180000, 100000
extent = (0, Lx, 0, Ly)
vmin, vmax = 0.0, 100.0
levels = np.arange(10, 110, 10)

# the fine topography every grid samples, and the shared watershed geometry
data_path = pl.Path("../data/mesh-generation")
fine_topo = flopy.utils.Raster.load(data_path / "fine_topo.asc")
geometries = json.loads((data_path / "watershed_geometry.json").read_text())

boundary_polygon = string2geom(geometries["boundary"])
bp = np.array(boundary_polygon)
sgs = [string2geom(geometries[f"streamseg{i}"]) for i in range(1, 5)]


def resample_topo(grid):
    """Sample the fine topography raster onto a model grid."""
    return fine_topo.resample_to_grid(
        grid, band=fine_topo.bands[0], method="linear", extrapolate_edges=True
    )


def river_intersection(grid, all_intersections=False):
    """Return an array flagged 1 in cells the river segments cross."""
    ixs = flopy.utils.GridIntersect(grid)
    cellids = []
    for sg in sgs:
        kw = {}
        if all_intersections:
            kw = dict(return_all_intersections=True)
        v = ixs.intersect(LineString(sg), sort_by_cellid=True, **kw)
        cellids += v["cellids"].tolist()
    arr = np.zeros(grid.shape[1:])
    for loc in cellids:
        arr[loc] = 1
    return arr


def draw_boundary_river(ax, river_alpha=1.0):
    """Draw the watershed boundary (black) and stream segments (blue) on ``ax``."""
    ax.plot(bp[:, 0], bp[:, 1], "k-")
    for sg in sgs:
        sa = np.array(sg)
        ax.plot(sa[:, 0], sa[:, 1], "b-", alpha=river_alpha)
