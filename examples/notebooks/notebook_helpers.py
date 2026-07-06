"""Shared helper functions for the example notebooks.

Keeping this boilerplate in one place lets each notebook import what it needs
instead of repeating the same setup cells. Add other generic, notebook-agnostic
helpers here as more notebooks need them.
"""

import os
import pathlib as pl
import platform

# Time conversions. MODFLOW has no built-in units, but these notebooks run in
# seconds, so multiply or divide by these to report or interpret a model
# duration in the more familiar days or years.
seconds_per_day = 60 * 60 * 24
seconds_per_year = seconds_per_day * 365.25


def find_in_env(filename, env_path=None):
    """Return the path to ``filename`` inside the active pixi/conda environment.

    Checks the usual bin/lib locations first, then falls back to a recursive
    search (meson installs the Linux ``.so`` under a multiarch subdirectory such
    as ``lib/x86_64-linux-gnu`` that a fixed list would miss).

    Parameters
    ----------
    filename : str
        File to locate, e.g. ``"mf6"`` or ``"libmf6.dll"``.
    env_path : path-like, optional
        Environment prefix to search; defaults to ``$CONDA_PREFIX``.

    Returns
    -------
    pathlib.Path
    """
    if env_path is None:
        prefix = os.environ.get("CONDA_PREFIX", None)
        assert prefix is not None, "Notebook must be run from the pixi environment"
        env_path = pl.Path(prefix)
    env_path = pl.Path(env_path)

    # get_mf6.py installs mf6 into different subdirectories depending on platform
    # (bin on Windows; bin plus lib on Unix).
    search_dirs = ["bin", "lib", "Scripts", "Library/bin"]
    for d in search_dirs:
        candidate = env_path / d / filename
        if candidate.is_file():
            return candidate
    matches = sorted(env_path.rglob(filename))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"Could not find {filename} under {env_path} "
        f"(looked in {', '.join(search_dirs)} and recursively)"
    )


def find_mf6_libraries(env_path=None):
    """Locate the MODFLOW 6 shared library and executable in the active env.

    The API drives MODFLOW 6 through its compiled shared library (``libmf6``),
    not the ``mf6`` command-line executable, so both are returned. The file
    extensions differ by platform (``.so`` on Linux, ``.dylib`` on macOS,
    ``.dll`` on Windows).

    Returns
    -------
    (lib_name, mf6_exe) : tuple of pathlib.Path
        Paths to ``libmf6`` and ``mf6``.
    """
    system = platform.platform().lower()
    if "linux" in system:
        lib_ext, exe_ext = ".so", ""
    elif "darwin" in system or "macos" in system:
        lib_ext, exe_ext = ".dylib", ""
    else:
        lib_ext, exe_ext = ".dll", ".exe"

    lib_name = find_in_env(f"libmf6{lib_ext}", env_path=env_path)
    mf6_exe = find_in_env(f"mf6{exe_ext}", env_path=env_path)
    return lib_name, mf6_exe


# ---------------------------------------------------------------------------
# Synthetic-valley advanced-packages notebooks
# ---------------------------------------------------------------------------
# The advanced-packages notebooks each add one advanced package (UZF, MAW, SFR,
# LAK, MVR) to a single shared model under models/. The helpers below let every
# notebook find-or-create that model the same way and check package
# dependencies, so the notebooks can be run independently and in any order
# (subject to the dependencies enforced by require_packages).

IN2FT = 1.0 / 12.0  # inches -> feet unit conversion used by several packages


def synthetic_valley_workspaces(sample_frequency, name="sv"):
    """(base_ws, advanced_ws) paths for the selected sample frequency."""
    base_ws = pl.Path(
        f"../data/synthetic-valley/synthetic-valley-base-{sample_frequency}"
    )
    advanced_ws = pl.Path(f"models/synthetic-valley-advanced-{sample_frequency}")
    return base_ws, advanced_ws


def load_or_create_advanced_model(sample_frequency, name="sv"):
    """Return the advanced-packages simulation for the selected frequency.

    If the advanced model already exists under models/ (i.e. an earlier notebook
    created it), load and return it so this notebook adds to the packages built
    earlier. Otherwise load the calibrated base model from ../data, repoint it at
    the models/ workspace, and write it there - creating the base model in
    models/ - before returning it.
    """
    import flopy

    base_ws, advanced_ws = synthetic_valley_workspaces(sample_frequency, name)
    if (advanced_ws / "mfsim.nam").is_file():
        sim = flopy.mf6.MFSimulation.load(
            sim_name=name,
            sim_ws=advanced_ws,
            write_headers=False,
            verbosity_level=0,
        )
    else:
        sim = flopy.mf6.MFSimulation.load(
            sim_name=name,
            sim_ws=base_ws,
            write_headers=False,
            verbosity_level=0,
        )
        sim.set_sim_path(advanced_ws)
        sim.write_simulation(silent=True)
    return sim


def drop_packages(gwf, *names):
    """Remove packages from a model by name if they are present (idempotent)."""
    for n in names:
        if gwf.get_package(n) is not None:
            gwf.remove_package(n)


def require_packages(gwf, required, feature):
    """Raise if any required package is missing from the advanced model.

    Used to enforce build-order dependencies, e.g. the MVR notebook requires the
    UZF, LAK, and SFR packages to have been built first.
    """
    missing = [p for p in required if gwf.get_package(p) is None]
    if missing:
        raise RuntimeError(
            f"The {feature} package requires {', '.join(required)}, but "
            f"{', '.join(missing)} not found in the advanced model. Build the "
            f"missing package(s) first (run the matching advanced-packages-* "
            f"notebook) so models/ contains them, then re-run this notebook."
        )


def load_temporal_data(sample_frequency):
    """Time-varying forcing (precip, ET, pumping) for the selected frequency."""
    import pandas as pd

    path = pl.Path(
        f"../data/synthetic-valley/data/temporal_data_{sample_frequency}.parquet"
    )
    return pd.read_parquet(path)


def load_spatial_data():
    """(nc_ds, lake_location, lake_area) from the synthetic-valley truth dataset."""
    import xarray as xa

    nc_path = pl.Path("../data/synthetic-valley/data/synthetic_valley_truth.nc")
    nc_ds = xa.open_dataset(nc_path)
    lake_location = nc_ds["lake_location"].to_numpy()
    lake_area = float(lake_location.sum()) * 500.0 * 500.0
    return nc_ds, lake_location, lake_area


# ---------------------------------------------------------------------------
# Generic grid / geometry helpers (shared by e.g. the parallel notebook)
# ---------------------------------------------------------------------------
def string2geom(geostring, conversion=None):
    """Convert a multi-line string of ``"x y"`` vertices to a list of (x, y) tuples."""
    multiplier = 1.0 if conversion is None else float(conversion)
    res = []
    for line in geostring.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        res.append((float(parts[0]) * multiplier, float(parts[1]) * multiplier))
    return res


def set_structured_idomain(modelgrid, boundary):
    """Set a structured grid's idomain (in place) from a boundary polygon.

    Cells intersected by the polygon are marked active (idomain 1), all others
    inactive (0). ``boundary`` is a list of (x, y) vertices.
    """
    import numpy as np
    from flopy.utils.gridintersect import GridIntersect
    from shapely.geometry import Polygon

    if modelgrid.grid_type != "structured":
        raise ValueError(f"modelgrid must be 'structured' not '{modelgrid.grid_type}'")

    ix = GridIntersect(modelgrid, rtree=True)
    result = ix.intersect(Polygon(boundary))
    idx = np.array([coords for coords in result.cellids], dtype=int)
    nr = idx.shape[0]
    if idx.ndim == 1:
        idx = idx.reshape((nr, 1))
    idx = tuple(idx[:, i] for i in range(idx.shape[1]))
    idomain = np.zeros(modelgrid.shape[1:], dtype=int)
    idomain[idx] = 1
    modelgrid.idomain = idomain.reshape(modelgrid.shape)


def intersect_segments(modelgrid, segments):
    """Intersect line segments with a grid.

    Returns ``(GridIntersect, cellids, lengths)`` where ``cellids`` and
    ``lengths`` are the concatenated intersected cell ids and reach lengths for
    all segments. ``segments`` is a list of lists of (x, y) tuples.
    """
    import flopy
    from shapely.geometry import LineString

    ixs = flopy.utils.GridIntersect(
        modelgrid,
    )
    cellids = []
    lengths = []
    for sg in segments:
        v = ixs.intersect(LineString(sg), sort_by_cellid=True)
        cellids += v["cellids"].tolist()
        lengths += v["lengths"].tolist()
    return ixs, cellids, lengths


def cell_areas(modelgrid):
    """Return per-cell areas for a structured (2-D array) or vertex (1-D) grid."""
    import numpy as np
    from shapely.geometry import Polygon

    if modelgrid.grid_type == "structured":
        nrow, ncol = modelgrid.nrow, modelgrid.ncol
        areas = np.zeros((nrow, ncol), dtype=float)
        for r in range(nrow):
            for c in range(ncol):
                vertices = np.array(modelgrid.get_cell_vertices((r, c)))
                areas[r, c] = Polygon(vertices).area
    elif modelgrid.grid_type == "vertex":
        areas = np.zeros(modelgrid.ncpl, dtype=float)
        for idx in range(modelgrid.ncpl):
            vertices = np.array(modelgrid.get_cell_vertices(idx))
            areas[idx] = Polygon(vertices).area
    else:
        raise ValueError(
            f"modelgrid must be 'structured' or 'vertex' not {modelgrid.grid_type}"
        )
    return areas


def get_model_cell_count(model):
    """Return ``(ncells, nactive)`` for a MODFLOW 6 model."""
    import numpy as np

    modelgrid = model.modelgrid
    if modelgrid.grid_type == "structured":
        ncells = modelgrid.nlay * modelgrid.nrow * modelgrid.ncol
    elif modelgrid.grid_type == "vertex":
        ncells = modelgrid.nlay * modelgrid.ncpl
    else:
        raise ValueError(f"modelgrid grid type '{modelgrid.grid_type}' not supported")
    idomain = modelgrid.idomain
    nactive = ncells if idomain is None else int(np.count_nonzero(idomain == 1))
    return ncells, nactive


def get_simulation_cell_count(simulation):
    """Return ``(ncells, nactive)`` summed over all models in a simulation."""
    ncells = 0
    nactive = 0
    for model_name in simulation.model_names:
        i, j = get_model_cell_count(simulation.get_model(model_name))
        ncells += i
        nactive += j
    return ncells, nactive


def densify_geometry(line, step, keep_internal_nodes=True):
    """Return a list of (x, y) points along ``line`` spaced about ``step`` apart.

    Used to seed extra nodes along river geometries before triangulating. When
    ``keep_internal_nodes`` is True the original vertices are preserved.
    """
    import numpy as np
    import shapely.geometry

    xy = []
    if keep_internal_nodes:
        lines_strings = [
            shapely.geometry.LineString(line[i - 1 : i + 1])
            for i in range(1, len(line))
        ]
    else:
        lines_strings = [shapely.geometry.LineString(line)]

    for line_string in lines_strings:
        length_m = line_string.length
        for distance in np.arange(0, length_m + step, step):
            pt = line_string.interpolate(distance)
            if (pt.x, pt.y) not in xy:
                xy.append((pt.x, pt.y))
        if keep_internal_nodes:
            end = line_string.coords[-1]
            if end not in xy:
                xy.append(end)
    return xy


def set_idomain(grid, boundary):
    """Set a grid's idomain (in place) from a boundary polygon, structured OR vertex.

    Unlike ``set_structured_idomain`` this works for VertexGrid
    (quadtree/triangle/voronoi) as well as StructuredGrid - GridIntersect
    auto-detects the grid type. Cells intersected by the polygon are active (1),
    others 0.
    """
    import numpy as np
    from flopy.utils.gridintersect import GridIntersect
    from shapely.geometry import Polygon

    ix = GridIntersect(grid, rtree=True)
    result = ix.intersect(Polygon(boundary))
    idx = np.array([coords for coords in result.cellids], dtype=int)
    nr = idx.shape[0]
    if idx.ndim == 1:
        idx = idx.reshape((nr, 1))
    idx = tuple(idx[:, i] for i in range(idx.shape[1]))
    idomain = np.zeros(grid.shape[1:], dtype=int)
    idomain[idx] = 1
    grid.idomain = idomain.reshape(grid.shape)


# ---------------------------------------------------------------------------
# MODFLOW 6 API notebooks
# ---------------------------------------------------------------------------
def plot_convergence(fig, ax, history, max_ticks=25):
    """Redraw a live outer-iteration convergence plot from a solver-loop history.

    ``history`` is a list of ``(cumulative_iteration, abs_max_head_change,
    stress_period, time_step)`` tuples appended once per outer iteration by a
    manual API solver loop. Each time step is given an equal-width x-axis slot so
    the long initial steady-state solve does not crowd out the transient time
    steps, and the SP/TS labels are thinned to at most ``max_ticks``. Call this
    once per time step from inside a ``flopy.plot.styles.USGSPlot()`` context to
    animate convergence as the model runs.
    """
    import flopy
    import numpy as np
    from IPython.display import clear_output, display

    ax.clear()
    if history:
        # group consecutive iterations into (stress period, time step) blocks
        blocks, b0 = [], 0
        for k in range(len(history)):
            if k == len(history) - 1 or history[k][2:] != history[k + 1][2:]:
                blocks.append((b0, k))
                b0 = k + 1

        # spread each block's iterations evenly within its unit-width slot so
        # every time step gets the same width regardless of iteration count
        xs, ys = [], []
        for bi, (i0, i1) in enumerate(blocks):
            n = i1 - i0 + 1
            for j, k in enumerate(range(i0, i1 + 1)):
                xs.append(bi + (j + 0.5) / n if n > 1 else bi + 0.5)
                yv = history[k][1]
                ys.append(np.nan if yv == 0.0 else yv)  # skip exact zeros on log axis
        ax.semilogy(
            xs, ys, marker="o", ms=4, lw=1.0, color="0.25", mfc="cyan", mec="0.25"
        )

        # thin the labels/separators so at most ~max_ticks are drawn
        stride = max(1, -(-len(blocks) // max_ticks))
        ticks, labels = [], []
        for bi, (i0, i1) in enumerate(blocks):
            if bi % stride == 0 or bi == len(blocks) - 1:
                ticks.append(bi + 0.5)
                labels.append(f"SP {history[i1][2]}\nTS {history[i1][3]}")
                if bi > 0:
                    ax.axvline(bi, color="0.5", lw=0.5)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)

    flopy.plot.styles.heading(
        ax=ax,
        heading="Outer iteration convergence",
    )
    flopy.plot.styles.xlabel(
        ax=ax,
        label="Stress period and time step",
    )
    flopy.plot.styles.ylabel(
        ax=ax,
        label="Maximum head change, ft",
    )
    flopy.plot.styles.remove_edge_ticks(
        ax=ax,
    )

    clear_output(wait=True)
    display(fig)


# ---------------------------------------------------------------------------
# flopy-intro GWF/GWT notebooks
# ---------------------------------------------------------------------------
def time_slider_view(make_fig, ntimes, value=None, description="time index", dpi=200):
    """Drive a time-index slider that always shows exactly one figure, identically
    in VS Code and JupyterLab. Each frame is rendered to a PNG and pushed into a
    single ipywidgets.Image; assigning Image.value *replaces* the displayed frame
    in every frontend, so figures never stack. ``make_fig(time_index)`` must build
    and return a Matplotlib figure.
    """
    import io

    import matplotlib.pyplot as plt
    from IPython.display import display
    from ipywidgets import Image, IntSlider

    image = Image(format="png")
    # scale the rendered PNG to the notebook cell width so it is not clipped or
    # oversized (e.g. in VS Code) while preserving the figure aspect ratio
    image.layout.width = "100%"
    image.layout.height = "auto"
    slider = IntSlider(
        min=0,
        max=ntimes - 1,
        step=1,
        value=ntimes - 1 if value is None else value,
        description=description,
        continuous_update=False,
    )

    def update(*_):
        fig = make_fig(slider.value)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)
        plt.close(fig)  # keep the inline backend from also emitting the figure
        image.value = buf.getvalue()

    slider.observe(update, names="value")
    display(slider, image)
    update()


def gwf_oc_expected_kstpkper(gwf, sim):
    """(kstp, kper) pairs (zero-based) the gwf OC is set to save, per record type."""
    nstp = sim.tdis.perioddata.array["nstp"]
    saverecord = gwf.oc.saverecord.get_data()  # {kper: recarray} or None

    expected = {}  # rtype -> set of (kstp, kper)
    current = {}  # rtype -> (ocsetting, ocsetting_data); forward-filled over periods
    for kper in range(nstp.size):
        rec = saverecord.get(kper) if saverecord else None
        if rec is not None:
            for rtype, setting, data in rec:
                current[rtype.lower()] = (setting.lower(), data)
        ns = int(nstp[kper])
        for rtype, (setting, data) in current.items():
            if setting == "all":
                ksteps = range(ns)
            elif setting == "first":
                ksteps = [0]
            elif setting == "last":
                ksteps = [ns - 1]
            elif setting == "frequency":
                freq = int(data[0])
                ksteps = [k for k in range(ns) if (k + 1) % freq == 0]
            elif setting == "steps":
                want = {int(s) for s in data}
                ksteps = [k for k in range(ns) if (k + 1) in want]
            else:
                ksteps = range(ns)
            expected.setdefault(rtype, set()).update((k, kper) for k in ksteps)
    return expected


def gwf_output_available(gwf, sim, ws):
    """True only if every output file the gwf OC writes exists and is complete.

    Lets a notebook skip ``sim.run_simulation()`` when the head and budget files
    already contain every time step the OC package is configured to save.
    """
    expected = gwf_oc_expected_kstpkper(gwf, sim)
    readers = {
        "head": (gwf.oc.head_filerecord.array, gwf.output.head),
        "budget": (gwf.oc.budget_filerecord.array, gwf.output.budget),
    }
    for rtype, want in expected.items():
        if not want:
            continue
        filerecord, reader = readers.get(rtype, (None, None))
        if reader is None or filerecord is None:
            return False
        # the output file must exist on disk
        if not (ws / filerecord[0][0]).is_file():
            return False
        # ...and contain every requested time step
        try:
            have = {(int(k), int(p)) for k, p in reader().get_kstpkper()}
        except Exception:
            return False
        if not want.issubset(have):
            return False
    return True


def require_gwf_output(
    gwf, ws, hint="run flopy-intro-gwt-A.ipynb to run the gwf model first"
):
    """Raise a clear error if the gwf head or budget output is missing or empty.

    Used by a downstream transport notebook that reads the flow model's saved
    heads and flows, to fail early (pointing back to the flow notebook) instead
    of deep inside the transport build.
    """
    checks = {
        "head": (gwf.oc.head_filerecord.array, gwf.output.head),
        "budget": (gwf.oc.budget_filerecord.array, gwf.output.budget),
    }
    for rtype, (filerecord, reader) in checks.items():
        if filerecord is None:
            raise FileNotFoundError(f"gwf OC has no {rtype} output configured; {hint}")
        fpath = ws / filerecord[0][0]
        if not fpath.is_file() or fpath.stat().st_size == 0:
            raise FileNotFoundError(
                f"gwf {rtype} output '{fpath}' is missing or empty; {hint}"
            )
        if not reader().get_times():
            raise ValueError(f"gwf {rtype} output '{fpath}' contains no times; {hint}")
