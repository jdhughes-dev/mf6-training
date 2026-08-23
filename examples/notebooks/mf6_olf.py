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
    """Total throughflow across the plane (m^3/s): the sum of the positive flows
    of every package that adds water - CHD for the fixed-stage edges or FLW for
    a free outflow, plus PCP when it is raining."""
    budget = sim.get_model("mf6-olf").output.budget()
    names = [name.decode().strip() for name in budget.get_unique_record_names()]
    total = 0.0
    for text in ("CHD", "FLW", "PCP"):
        if text in names:
            q = budget.get_data(text=text)[0]["q"]
            total += float(q[q > 0].sum())
    return total


def draw_map(ax, field, delr, delc, levels=None, title=None, vmin=None, vmax=None):
    """Draw one masked ``(nrow, ncol)`` field on ``ax``, inactive cells in grey.
    The OLF DIS2D grid is regular, so the array is drawn directly with its cell
    size (row 0 is the north edge). Returns the image, for the color bar."""
    nrow, ncol = field.shape
    cmap = plt.get_cmap("Blues").with_extremes(bad="0.85")
    extent = [0, ncol * delr, 0, nrow * delc]
    xc = (np.arange(ncol) + 0.5) * delr
    yc = (nrow - 0.5 - np.arange(nrow)) * delc
    xx, yy = np.meshgrid(xc, yc)

    im = ax.imshow(
        field,
        cmap=cmap,
        extent=extent,
        origin="upper",
        aspect="equal",
        vmin=vmin,
        vmax=vmax,
    )
    cl = ax.contour(xx, yy, field, levels=levels, colors="black", linewidths=0.6)
    ax.clabel(cl, fmt="%.2f", fontsize=7)
    ax.set_title(title)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    return im


def plot_stage(stage, delr, delc, levels):
    """Map the steady water surface (stage) on a figure of its own."""
    with styles.USGSMap():
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        im = draw_map(
            ax,
            stage,
            delr,
            delc,
            levels=levels,
            title="Steady overland flow: water surface (flow west to east)",
        )
        fig.colorbar(im, ax=ax, shrink=0.85, label="Water-surface stage (m)")
        plt.show()
