"""Output and plotting helpers for the mf6-olf overland-flow notebook.

The notebook builds and runs the OLF model; these functions read the results
and draw the water-surface map so the notebook can stay focused on the model
and its interpretation.
"""

import matplotlib.pyplot as plt
import numpy as np
from flopy.plot import styles


def get_stage(sim, idomain):
    """Return the steady water-surface stage as an ``(nrow, ncol)`` masked
    array, with the inactive cells masked out."""
    nrow, ncol = idomain.shape
    stage = sim.get_model("mf6-olf").output.stage().get_data().reshape(nrow, ncol)
    return np.ma.masked_where(idomain == 0, stage)


def total_discharge(sim):
    """Total throughflow across the plane (m^3/s): the water added at the
    fixed-stage boundary, i.e. the sum of the positive CHD flows."""
    q = sim.get_model("mf6-olf").output.budget().get_data(text="CHD")[0]["q"]
    return float(q[q > 0].sum())


def plot_stage(sim, idomain, delr, delc, levels):
    """Map the steady water surface (stage), with contours and the inactive
    block shown in grey. The OLF DIS2D grid is regular, so the array is drawn
    directly with its cell size (row 0 is the north edge)."""
    stage = get_stage(sim, idomain)
    nrow, ncol = idomain.shape
    cmap = plt.get_cmap("Blues").with_extremes(bad="0.85")
    extent = [0, ncol * delr, 0, nrow * delc]
    xc = (np.arange(ncol) + 0.5) * delr
    yc = (nrow - 0.5 - np.arange(nrow)) * delc
    xx, yy = np.meshgrid(xc, yc)
    with styles.USGSMap():
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        im = ax.imshow(stage, cmap=cmap, extent=extent, origin="upper", aspect="equal")
        cl = ax.contour(xx, yy, stage, levels=levels, colors="black", linewidths=0.6)
        ax.clabel(cl, fmt="%.1f", fontsize=7)
        fig.colorbar(im, ax=ax, shrink=0.85, label="Water-surface stage (m)")
        ax.set_title("Steady overland flow: water surface (flow west to east)")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        plt.show()
