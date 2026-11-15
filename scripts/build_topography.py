#!/usr/bin/env python
"""Write the synthetic-valley land surface and lake bathymetry on a 15.24 m raster.

The land surface is interpolated linearly within the triangles of the
synthetic-valley mesh (TriMesh_with_densified_contours.exp, in feet). The mesh
has no elevations inside its lake, so the lake bed is made to slope down from
the land at the shore to the bottom of layer 1, which it reaches halfway from
the shore to the point farthest from shore, and is flat beyond that. The raster goes in examples/data/synthetic-valley/data. Run inside the
pixi environment, e.g.

    python scripts/build_topography.py --mesh <path to TriMesh_with_densified_contours.exp>
"""

import argparse
import pathlib as pl

import matplotlib.tri as mtri
import numpy as np
import xarray as xr
from scipy.ndimage import distance_transform_edt
from sv_surface import LAKE_FLOOR, TOPOGRAPHY

FT2M = 0.3048
# m (50 ft), a tenth of the width of a structured model cell
CELL = 15.24
NROW, NCOL = 400, 250
# the lake bed reaches the bottom of layer 1 at this fraction of the largest
# distance from shore
FLOOR_FRACTION = 0.5


def read_mesh(path):
    """Mesh point coordinates and elevations (m), the triangles, and whether
    each triangle is in the lake."""
    nodes, elements = [], []
    for line in path.read_text().splitlines():
        s = line.split()
        if s and s[0] == "N":
            nodes.append((float(s[2]), float(s[3]), float(s[-1])))
        elif s and s[0] == "E":
            elements.append(
                (int(s[2]) - 1, int(s[3]) - 1, int(s[4]) - 1, s[5] == "lake")
            )
    nodes = np.array(nodes) * FT2M
    triangles = np.array([e[:3] for e in elements])
    lake = np.array([e[3] for e in elements])
    return nodes, triangles, lake


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mesh", type=pl.Path, required=True, help="mesh .exp file")
    parser.add_argument("--dest", type=pl.Path, default=TOPOGRAPHY, help="NetCDF file")
    args = parser.parse_args(argv)

    nodes, triangles, lake_tri = read_mesh(args.mesh)
    tri = mtri.Triangulation(nodes[:, 0], nodes[:, 1], triangles)
    x = (np.arange(NCOL) + 0.5) * CELL
    y = NROW * CELL - (np.arange(NROW) + 0.5) * CELL
    xx, yy = np.meshgrid(x, y)
    land = mtri.LinearTriInterpolator(tri, nodes[:, 2])(xx, yy).filled(np.nan)
    lake = lake_tri[tri.get_trifinder()(xx, yy)]

    # the lake bed slopes down from the land at the nearest shore cell to the
    # bottom of layer 1
    dist, (ii, jj) = distance_transform_edt(lake, sampling=CELL, return_indices=True)
    shore = land[ii, jj]
    frac = np.minimum(dist / (FLOOR_FRACTION * dist[lake].max()), 1.0)
    elevation = np.where(lake, shore + (LAKE_FLOOR - shore) * frac, land)

    ds = xr.Dataset(
        {
            "elevation": (("y", "x"), elevation.astype(np.float32)),
            "mesh_lake": (("y", "x"), lake.astype(np.int8)),
        },
        coords={"y": y, "x": x},
    )
    ds["elevation"].attrs = {
        "units": "m",
        "long_name": "land surface, with the lake bed inside the mesh lake",
    }
    ds["mesh_lake"].attrs["long_name"] = "1 inside the lake of the mesh"
    ds["x"].attrs["units"] = "m"
    ds["y"].attrs["units"] = "m"
    ds.attrs["source"] = (
        f"{args.mesh.name}, interpolated linearly within its triangles to the "
        "centers of 15.24 m cells"
    )
    encoding = {v: {"zlib": True} for v in ds.data_vars}
    ds.to_netcdf(args.dest, encoding=encoding)
    print(
        f"{args.dest.name}: {NROW} x {NCOL} cells of {CELL} m, elevation "
        f"{np.nanmin(elevation):.2f} to {np.nanmax(elevation):.2f} m"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
