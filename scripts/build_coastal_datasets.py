#!/usr/bin/env python
"""Build the coastal synthetic-valley datasets from the shipped models.

Each coastal model is a shipped base or advanced model plus a general-head
boundary (GHB) at sea level along the southern edge, which turns the valley into
a coastal aquifer. Nothing else changes, so a coastal model can be compared cell
for cell with the model it came from. Run inside the pixi env, e.g.
`pixi run build-coastal`.
"""

import argparse
import filecmp
import pathlib as pl
import shutil
import sys
import tempfile

import flopy

sys.path.insert(0, str(pl.Path(__file__).resolve().parents[1] / "examples/notebooks"))

from mf6_notebook_helpers import coastal_ghb_data  # noqa: E402

DATA_ROOT = pl.Path(__file__).resolve().parents[1] / "examples/data/synthetic-valley"
KINDS = ("base", "advanced")
FREQUENCIES = ("annual", "monthly")
# Only the annual models are built by default. The coastal notebooks use them,
# and a coastal copy of the monthly advanced model would add 20 MB to the
# repository for a dataset nothing reads; pass --frequency monthly for it.
DEFAULT_FREQUENCIES = ("annual",)


def build_one(kind, sample_frequency, dest, cond_mult=1.0, name="sv"):
    """Write one coastal model and return its GHB stress-period data."""
    src = DATA_ROOT / f"synthetic-valley-{kind}-{sample_frequency}"
    sim = flopy.mf6.MFSimulation.load(
        sim_name=name, sim_ws=src, write_headers=False, verbosity_level=0
    )
    gwf = sim.get_model()
    spd, auxiliary = coastal_ghb_data(gwf, cond_mult=cond_mult)
    flopy.mf6.ModflowGwfghb(
        gwf,
        pname="ghb-1",
        auxiliary=auxiliary,
        boundnames=True,
        print_flows=True,
        stress_period_data={0: spd},
        observations={
            f"{name}.ghb.obs.csv": [("coast-swgw", "ghb", "coast")],
            "filename": f"{name}.ghb.obs",
        },
    )
    if dest.exists():
        shutil.rmtree(dest)
    sim.set_sim_path(dest)
    sim.write_simulation(silent=True)
    return spd


def targets(only, frequency):
    """The (kind, sample_frequency) pairs the command line asks for."""
    kinds = KINDS if only is None else (only,)
    frequencies = DEFAULT_FREQUENCIES if frequency is None else (frequency,)
    return [(kind, freq) for kind in kinds for freq in frequencies]


def differences(built, committed):
    """Names of the files that differ between two model workspaces."""
    if not committed.is_dir():
        return [f"{committed.name}/ is missing"]
    names = sorted(
        {p.name for p in built.iterdir()} | {p.name for p in committed.iterdir()}
    )
    match, mismatch, errors = filecmp.cmpfiles(built, committed, names, shallow=False)
    return sorted(mismatch + errors)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=KINDS, help="build just one kind of model")
    parser.add_argument(
        "--frequency", choices=FREQUENCIES, help="build just one sampling frequency"
    )
    parser.add_argument(
        "--cond-mult",
        type=float,
        default=1.0,
        help="scale every GHB conductance (default 1.0)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="build into a temporary directory and report any drift from the "
        "committed datasets instead of overwriting them",
    )
    args = parser.parse_args(argv)

    drifted = []
    for kind, frequency in targets(args.only, args.frequency):
        committed = DATA_ROOT / f"synthetic-valley-coastal-{kind}-{frequency}"
        with tempfile.TemporaryDirectory() as tmp:
            dest = pl.Path(tmp) / committed.name if args.check else committed
            spd = build_one(kind, frequency, dest, cond_mult=args.cond_mult)
            print(f"{committed.name}: {len(spd)} GHB cells")
            if args.check:
                changed = differences(dest, committed)
                if changed:
                    drifted.append((committed.name, changed))

    if args.check and drifted:
        for workspace, changed in drifted:
            print(f"drift in {workspace}: {', '.join(changed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
