#!/usr/bin/env python
"""Build the synthetic-valley Voronoi grid.

The cells are smaller along the stream, around the three pumping wells, and
over the lake at its highest level (LAKE_EXTENT in scripts/sv_surface.py). The
grid is written as the discretization (DISV) file of a one-layer model, which
scripts/build_vg_models.py reads with --grid. Run inside the
pixi environment, e.g.

    python scripts/build_vg_grid.py --dest <dir>
"""

import argparse
import pathlib as pl

import flopy
import matplotlib.pyplot as plt
import numpy as np
from flopy.utils.triangle import Triangle
from flopy.utils.voronoi import VoronoiGrid
from shapely.geometry import LineString, Polygon, box
from sv_surface import LAKE_EXTENT, Surface

FT2M = 1.0 / 3.28081
# m, the approximate cell size along the model boundary, along the stream, and
# over the lake
BOUNDARY_SIZE, STREAM_SIZE, LAKE_SIZE = 100.0, 25.0, 40.0
# m, the radius of the area of small cells around each well, and the largest
# triangle area there (m2) from which the cells are built
WELL_RADIUS, WELL_AREA = 100.0, 500.0
# m, how far the simplified lake shoreline may depart from the flooded area
SHORE_TOLERANCE = 10.0
LENGTH, WIDTH = 6096.0, 3810.0


def feet(points):
    return np.array(points, dtype=float) * FT2M


BOUNDARY = feet([(0.0, 0.0), (0.0, 20000.0), (12500.0, 20000.0), (12500.0, 0.0)])
STREAM = feet([(4250.0, 8750.0), (4250.0, 0.0)])
STREAM_BOX = feet([(3500.0, 0.0), (3500.0, 9500.0), (5000.0, 9500.0), (5000.0, 0.0)])
WELLS = feet([(7250.0, 17250.0), (7750.0, 2750.0), (2750.0, 3750.0)])
# a point inside each area that gets its own cell size: the areas of large
# cells, the lake, and the box around the stream
COARSE_POINTS = [(10.0, 10.0), (3050.0, 3050.0)]
LAKE_POINT = (900.0, 4600.0)
STREAM_POINT = (1200.0, 150.0)


def densify(line, step):
    """Points along a line, no more than ``step`` apart."""
    xy = []
    for a, b in zip(line[:-1], line[1:], strict=True):
        segment = LineString([a, b])
        for d in np.arange(0.0, segment.length + step, step):
            p = segment.interpolate(d)
            if (p.x, p.y) not in xy:
                xy.append((p.x, p.y))
    return np.array(xy)


def circle(center, radius, dtheta=10.0):
    a = np.radians(np.arange(0.0, 360.0, dtheta))
    return np.column_stack(
        [center[0] + radius * np.cos(a), center[1] + radius * np.sin(a)]
    )


def shoreline(surface):
    """Points LAKE_SIZE apart around the lake shoreline at its highest level."""
    water = surface.flooded(LAKE_EXTENT).astype(float)
    x = (np.arange(surface.ncol) + 0.5) * surface.cell
    y = surface.nrow * surface.cell - (np.arange(surface.nrow) + 0.5) * surface.cell
    contour = plt.contour(x, y, water, levels=[0.5])
    path = max(contour.allsegs[0], key=len)
    plt.close()
    poly = Polygon(path).buffer(0).simplify(SHORE_TOLERANCE)
    # keep the shoreline at least one lake cell from the model edge
    poly = poly.intersection(
        box(LAKE_SIZE, LAKE_SIZE, WIDTH - LAKE_SIZE, LENGTH - LAKE_SIZE)
    )
    # evenly spaced, so no very short cell edges are left at the corners
    ring = poly.exterior
    n = int(np.ceil(ring.length / LAKE_SIZE))
    distances = np.linspace(0.0, ring.length, n, endpoint=False)
    return np.array([(p.x, p.y) for p in (ring.interpolate(d) for d in distances)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", type=pl.Path, required=True, help="grid directory")
    args = parser.parse_args(argv)
    args.dest.mkdir(parents=True, exist_ok=True)

    work = args.dest / "triangle"
    work.mkdir(exist_ok=True)
    tri = Triangle(angle=30, nodes=densify(STREAM, STREAM_SIZE), model_ws=work)
    tri.add_polygon(densify(BOUNDARY, BOUNDARY_SIZE))
    tri.add_polygon(densify(STREAM_BOX, STREAM_SIZE))
    tri.add_polygon(shoreline(Surface()))
    for point in COARSE_POINTS:
        tri.add_region(point, attribute=10, maximum_area=BOUNDARY_SIZE**2)
    tri.add_region(LAKE_POINT, attribute=11, maximum_area=LAKE_SIZE**2)
    tri.add_region(STREAM_POINT, attribute=10, maximum_area=STREAM_SIZE**2)
    for n, well in enumerate(WELLS):
        tri.add_polygon(circle(well, WELL_RADIUS))
        tri.add_region(tuple(well), attribute=n, maximum_area=WELL_AREA)
    tri.build(verbose=False)
    props = VoronoiGrid(tri).get_disv_gridprops()

    sim = flopy.mf6.MFSimulation(sim_name="sv", sim_ws=args.dest, write_headers=False)
    flopy.mf6.ModflowTdis(sim)
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="sv")
    flopy.mf6.ModflowGwfdisv(gwf, nlay=1, top=0.0, botm=-1.0, **props)
    sim.write_simulation(silent=True)
    print(f"{args.dest.name}: {props['ncpl']} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
