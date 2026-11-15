#!/usr/bin/env python
"""Write the synthetic-valley Voronoi-grid truth from a run of the advanced model.

The heads in every cell at the end of each stress period, the cell geometry,
and the observed series go in examples/data/synthetic-valley/data, for sampling
true observations. Run inside the pixi environment after running the model,
e.g.

    python scripts/write_vg_truth.py
"""

import argparse
import pathlib as pl

import flopy
import numpy as np
import pandas as pd
import xarray as xr

DATA_ROOT = pl.Path(__file__).resolve().parents[1] / "examples/data/synthetic-valley"
MODEL = DATA_ROOT / "synthetic-valley-vg-advanced-annual"
DEST = DATA_ROOT / "data/synthetic_valley_vg_truth.nc"
# heads at or above this are dry or inactive cells
HDRY = 1.0e20


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=pl.Path, default=MODEL, help="model run")
    parser.add_argument("--dest", type=pl.Path, default=DEST, help="NetCDF file")
    args = parser.parse_args(argv)

    sim = flopy.mf6.MFSimulation.load(
        sim_ws=args.model, verbosity_level=0, load_only=["disv", "npf"]
    )
    gwf = sim.get_model()
    disv = gwf.disv
    nlay, ncpl = disv.nlay.data, disv.ncpl.data

    hds = flopy.utils.HeadFile(args.model / "sv.hds")
    times = np.array(hds.get_times())
    head = np.array([hds.get_data(totim=t).reshape(nlay, ncpl) for t in times])
    head[np.abs(head) >= HDRY] = np.nan

    layer = np.arange(1, nlay + 1)
    cell = np.arange(1, ncpl + 1)
    ds = xr.Dataset(
        {
            "heads": (("time", "layer", "cell"), head.astype(np.float32)),
            "x": ("cell", gwf.modelgrid.xcellcenters),
            "y": ("cell", gwf.modelgrid.ycellcenters),
            "top": ("cell", disv.top.array),
            "bottom": (("layer", "cell"), disv.botm.array),
            "idomain": (("layer", "cell"), disv.idomain.array),
            "k": (("layer", "cell"), gwf.npf.k.array),
        },
        coords={"time": times, "layer": layer, "cell": cell},
    )
    units = {"heads": "m", "x": "m", "y": "m", "top": "m", "bottom": "m", "k": "m/d"}
    for name, unit in units.items():
        ds[name].attrs["units"] = unit
    ds["time"].attrs["units"] = "days since 1962-01-01"

    # the observed series, one variable per observation, on the output times
    for csv in sorted(args.model.glob("*.csv")):
        if "budget" in csv.name:
            continue
        obs = pd.read_csv(csv, index_col=0)
        for name in obs.columns:
            values = obs[name].reindex(times).to_numpy()
            ds[f"obs_{name.lower()}"] = ("time", values)
            ds[f"obs_{name.lower()}"].attrs["source"] = csv.name

    ds.attrs["source"] = (
        f"{args.model.name} run with MODFLOW 6; heads at the end of each stress period"
    )
    encoding = {v: {"zlib": True} for v in ds.data_vars}
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(args.dest, encoding=encoding)
    print(f"{args.dest.name}: {len(times)} times, {nlay} layers, {ncpl} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
