# MODFLOW 6 training notebooks

The hands-on core of the [MODFLOW 6 training](../../README.md): a collection of
Jupyter notebooks that each demonstrate one MODFLOW 6 capability, built and
post-processed with [FloPy](https://github.com/modflowpy/flopy). They are written
for students with limited-to-no Python or MODFLOW experience — every notebook
pairs plain-language markdown (what each step does, why it matters, and what to
look for in the results) with runnable code, and closes with a short recap.

Between them the notebooks cover building models from scratch with FloPy, driving
MODFLOW 6 live through its API, the advanced hydrologic packages (UZF, MAW, SFR,
LAK, MVR), solute and heat transport, variable-density flow, land subsidence,
particle tracking, the XT3D flow formulation, unstructured-grid generation, local
grid refinement, and running models in parallel.

## How to use

1. **Set up the environment once.** Follow the [top-level README](../../README.md)
   to install [pixi](https://pixi.sh) and run `pixi install`; the first activation
   also installs MODFLOW 6 and the mp7 / Triangle / Gridgen executables the
   notebooks need.

2. **Launch JupyterLab** from the repository root and open any notebook:

   ```bash
   pixi run jupyter
   ```

3. **Run a notebook top to bottom.** Each one is self-contained: it builds its
   model, runs MODFLOW 6, and plots the results. Model input/output is written
   under `examples/notebooks/models/` (git-ignored), so nothing you run pollutes
   the repository.

4. **Where to start.** The `flopy-intro-*` notebooks are the guided introduction
   to building and post-processing a model with FloPy; after those, explore by
   topic using the tables below. The `mf6-api-*` and `mf6-advanced-packages-*`
   notebooks are each meant to be read in order (a → f, and the advanced packages
   build on a shared model), and they check for and explain any prerequisites.

5. **Paired helper modules.** A few notebooks keep their bulkier setup in a
   same-named Python module (for example `mf6-gwt1d.ipynb` ↔ `mf6_gwt1d.py`,
   `mf6-gwe-stallman.ipynb` ↔ `mf6_gwe_stallman.py`). These are imported by the
   notebook, not run directly. The shared `mf6_notebook_helpers.py` and
   `mf6_mesh_helpers.py` provide utilities used across several notebooks.

6. **Smoke-test from the command line.** To confirm the fast notebooks still run
   end to end (this is what CI does), use the run script — with no arguments it
   runs a default subset, or pass specific paths:

   ```bash
   pixi run test-notebooks
   pixi run python scripts/run_notebooks.py examples/notebooks/mf6-gwt1d.ipynb
   ```

   A handful of notebooks are intentionally slow (several minutes each) and are
   left out of the default set — for example `mf6-api-a`/`-e`/`-f`,
   `mf6-gwe-stallman`, `mf6-density-henry-hilleke`, the `mf6-advanced-packages-*`
   series, and `mf6-parallel` — but they still run.

> **Naming.** Notebooks are prefixed `mf6-` (or `flopy-` for the FloPy-basics
> introductions). A notebook's paired helper module shares its name with hyphens
> replaced by underscores (Python modules cannot contain hyphens).

## The notebooks

### Getting started with FloPy

| Notebook | What it demonstrates |
|---|---|
| [`flopy-intro-gwf-only`](flopy-intro-gwf-only.ipynb) | Build a groundwater flow (GWF) model from scratch with FloPy — DIS, NPF, IC, RCH, WEL, RIV, OC — then write it, run MODFLOW 6, and post-process and plot the heads. The guided starting point. |
| [`flopy-intro-gwt-a`](flopy-intro-gwt-a.ipynb) | Load, run, and inspect an existing GWF model: view hydraulic conductivity, recharge, and the simulated heads through time. A walk-through of how a MODFLOW 6 flow model is assembled. |
| [`flopy-intro-gwt-b`](flopy-intro-gwt-b.ipynb) | Add solute transport (GWT) on top of that flow model, coupled one-way through the Flow Model Interface (FMI), and plot concentrations through time. |

### Unstructured-grid generation

| Notebook | What it demonstrates |
|---|---|
| [`mf6-mesh-generation-rectilinear`](mf6-mesh-generation-rectilinear.ipynb) | Build structured (DIS) grids over a watershed: constant spacing, variable spacing that refines toward the river, and a local grid refinement (LGR) grid with a nested child. |
| [`mf6-mesh-generation-gridgen`](mf6-mesh-generation-gridgen.ipynb) | Build a quadtree unstructured (DISV) grid with the Gridgen program, refining cells near the river and the area of interest. |
| [`mf6-mesh-generation-triangle-voronoi`](mf6-mesh-generation-triangle-voronoi.ipynb) | Build triangular and Voronoi unstructured (DISV) grids over the same watershed with the Triangle program. |

### Controlling MODFLOW 6 with the API

Driving a running model through [modflowapi](https://github.com/MODFLOW-USGS/modflowapi) and the `libmf6` shared library.

| Notebook | What it demonstrates |
|---|---|
| [`mf6-api-a`](mf6-api-a.ipynb) | Basic API use: step a model through time with `update()` and read its state, introducing the API lifecycle and callback mechanism. |
| [`mf6-api-b`](mf6-api-b.ipynb) | Monitor solver convergence live by driving a manual solver loop through the API. |
| [`mf6-api-c`](mf6-api-c.ipynb) | Change a model input (recharge) while the simulation is running, using a modflowapi callback. |
| [`mf6-api-d`](mf6-api-d.ipynb) | Add a head-dependent boundary (a reverse drain) directly through the API package. |
| [`mf6-api-e`](mf6-api-e.ipynb) | Augment streamflow with a prediction well whose pumping rate is recomputed each outer iteration from the simulated SFR flow. |
| [`mf6-api-f`](mf6-api-f.ipynb) | Couple three transport models through a first-order sequential reaction chain via API callbacks. |

### Advanced hydrologic packages

Each notebook swaps one boundary condition of a shared, calibrated model for an advanced package.

| Notebook | What it demonstrates |
|---|---|
| [`mf6-advanced-packages-uzf`](mf6-advanced-packages-uzf.ipynb) | Unsaturated Zone Flow (UZF): route infiltration through an unsaturated column before it reaches the water table. |
| [`mf6-advanced-packages-maw`](mf6-advanced-packages-maw.ipynb) | Multi-Aquifer Well (MAW): represent a single well screened across several layers and compute its exchange with each. |
| [`mf6-advanced-packages-sfr`](mf6-advanced-packages-sfr.ipynb) | Streamflow Routing (SFR): route flow between connected stream reaches that exchange water with the aquifer. |
| [`mf6-advanced-packages-lak`](mf6-advanced-packages-lak.ipynb) | Lake (LAK): simulate lake stage and its exchange with the groundwater system. |
| [`mf6-advanced-packages-mvr`](mf6-advanced-packages-mvr.ipynb) | Water Mover (MVR): route water between the UZF, LAK, and SFR packages. |
| [`mf6-advanced-packages-processing`](mf6-advanced-packages-processing.ipynb) | Run the assembled advanced model and evaluate it — head residuals, pumping-induced drawdown, streamflow capture, and lake stage. |

### Land subsidence

| Notebook | What it demonstrates |
|---|---|
| [`mf6-csub`](mf6-csub.ipynb) | Skeletal Storage, Compaction, and Subsidence (CSUB): pumping-induced land subsidence in a layered aquifer system (adapted from `ex-gwf-csub-p04`), run with **no-delay** vs **delay** interbeds and compared by their maximum subsidence at the end of the simulation. |

### Transport and variable-density flow

| Notebook | What it demonstrates |
|---|---|
| [`mf6-gwt1d`](mf6-gwt1d.ipynb) | One-dimensional solute transport (GWT) in a steady flow field; compare advection schemes, cell size, and time step against an analytical solution to study numerical dispersion. |
| [`mf6-density-bubble`](mf6-density-bubble.ipynb) | Variable-density flow (BUY): a dense saltwater bubble sinking through fresh water, coupling GWF and GWT. |
| [`mf6-density-henry-hilleke`](mf6-density-henry-hilleke.ipynb) | Coupled variable-density flow with heat (GWF + GWT + GWE + PRT): a Henry-type saltwater intrusion in which temperature also affects fluid density. |

### Heat transport

| Notebook | What it demonstrates |
|---|---|
| [`mf6-gwe-stallman`](mf6-gwe-stallman.ipynb) | Groundwater energy transport (GWE): 1-D transient heat conduction and advection under a sinusoidal surface temperature (the Stallman problem), compared to the analytical solution. |

### Particle tracking (PRT)

| Notebook | What it demonstrates |
|---|---|
| [`mf6-prt-backward`](mf6-prt-backward.ipynb) | Backward particle tracking to delineate a well's capture zone, cross-checked against MODPATH 7. |
| [`mf6-prt-voronoi`](mf6-prt-voronoi.ipynb) | Particle tracking on a Voronoi (DISV) grid with an XT3D flow field and a coupled GWE model. |
| [`mf6-prt-watertable`](mf6-prt-watertable.ipynb) | Particle tracking through a water table that wets and dries, contrasting the standard and Newton flow formulations. |

### XT3D flow formulation

| Notebook | What it demonstrates |
|---|---|
| [`mf6-xt3d-unstructured`](mf6-xt3d-unstructured.ipynb) | The XT3D formulation for more accurate flows on an unstructured (DISV) grid with a quadtree-refined interior. |
| [`mf6-xt3d-whirls`](mf6-xt3d-whirls.ipynb) | Fully 3D anisotropy with XT3D, producing spiral "groundwater whirls" visualized with particle tracking. |

### Grid refinement, model splitting, and parallel runs

| Notebook | What it demonstrates |
|---|---|
| [`mf6-lgr-flopy`](mf6-lgr-flopy.ipynb) | Local grid refinement (LGR): couple a coarse parent and a nested finer child GWF model through a GWF-GWF exchange, built with FloPy's `Lgr` utility. |
| [`mf6-model-splitting-with-flopy`](mf6-model-splitting-with-flopy.ipynb) | Split a single model into submodels with FloPy's `Mf6Splitter` (manual and load-balanced partitions) for parallel or serial runs, then reassemble the results. |
| [`mf6-parallel`](mf6-parallel.ipynb) | Build and run a model in parallel across multiple processes (MPI), then reassemble and interpret the combined solution. |
