# Synthetic valley

The synthetic valley is an aquifer system in a valley that drains south. It is
described in Hughes, J.D., Langevin, C.D., Paulinski, S.R., Larsen, J.D., and
Brakenhoff, D., 2024, FloPy workflows for creating structured and unstructured
MODFLOW models: Groundwater, v. 62, no. 1, p. 124–139,
https://doi.org/10.1111/gwat.13327. The coastal models here and in the
[modflow-class-dsd26](https://github.com/mjr-deltares/modflow-class-dsd26)
class are built by the same scripts.

Every model works in meters and days and has five layers:

- layers 1 and 2 are the upper aquifer,
- layer 3 is a clay confining unit, active only where the clay is present;
  elsewhere its cells are vertical pass-through cells (`idomain` of -1) with
  no thickness, which connect layer 2 directly to layer 4, and
- layers 4 and 5 are the lower aquifer.

Layer 1 is convertible: its saturated thickness follows the water table, which
stores and releases water with a specific yield of 0.1. The base models' lake
cells keep their full thickness and store water as open water does, with a
specific yield of 1 and no specific storage. The top of layer 1 is the land
surface, from the mean of a 15.24 m raster of the land surface and lake bed over
each cell. The lake is the basin of that surface flooded to 6.5 m, the largest
extent of the lake in the advanced models; a cell is in the lake where the
flooded basin covers at least half of it. Groundwater that reaches the land
surface away from the lake and the stream leaves through seepage drains (DRN) on
the layer 1 cells. Each starts to discharge 0.1524 m (0.5 ft) below the land
surface and reaches its full conductance, the vertical hydraulic conductivity of
layer 1 times the cell area over the layer thickness, at the land surface. Every
model starts from its steady-state heads, changed by a uniform random amount of
up to 0.1 m, and an advanced model's lake from its steady-state level.

The simulation starts with a 16,071-day steady-state stress period, which gives
the flow system before pumping, followed by 20 one-year (annual) or 240
one-month (monthly) transient periods. Two pumping wells, `reilly` and `vc`,
screened in layers 4 and 5, start in the second stress period, and a prediction
well starts halfway through the transient periods.

| Model | Grid | Stresses |
|---|---|---|
| `synthetic-valley-base-{annual,monthly}` | structured, 40 rows by 25 columns of 152.4 m cells | Recharge (RCH); a lake of high hydraulic conductivity layer 1 cells whose top is the water surface at the lake's largest extent, with Evapotranspiration (EVT); a stream of River (RIV) cells; seepage drains; the pumping wells, one Well (WEL) cell per layer |
| `synthetic-valley-advanced-{annual,monthly}` | structured, as above | Unsaturated Zone Flow (UZF) on the land; Streamflow Routing (SFR); Lake (LAK) on top of the aquifer, with a stage-volume-area table; seepage drains; Water Mover (MVR), which routes UZF runoff and the drains' water to where the land surface drains: the lake, or the stream reach it reaches; the pumping wells as Multi-Aquifer Wells (MAW) |
| `synthetic-valley-coastal-{base,advanced}-annual` | structured, as above | the annual model of the same kind, with a General-Head Boundary (GHB) at sea level along the southern edge; runoff that reaches the coast leaves the model |
| `synthetic-valley-vg-{base,advanced}-annual` | Voronoi, 6,150 cells per layer | the annual model of the same kind; the advanced model defines the truth |

The base models' land recharge is the advanced models' infiltration less their
potential evapotranspiration, times 2.08. In the advanced models the lake is
connected vertically to the layer 1 cell under it, whose top is the lake bed.
Where the bed is the bottom of layer 1, the layer 1 cell is a vertical
pass-through cell and the lake is connected to layer 2. The stage-volume-area
table runs from the bottom of layer 1 to 14.94 m, just below the 14.96 m at
which the flooded basin would cross the ridge, so the lake has no outlet.

In the advanced models the streambed falls 0.0002 m per meter of stream, the
drop of the streambed from one reach to the next over the reach length; with
the flow, it sets how deep the water in the stream is.

The coastal GHB holds a head of 0 m and carries the elevation of the boundary
and a seawater concentration of 35 kilograms per cubic meter as auxiliary
variables, for density-dependent flow. The conductance of each boundary cell is
its horizontal hydraulic conductivity times the area of its face on the sea,
over half the cell length, and layer 3 has boundary cells only where the clay
is.

The structured models share their aquifer properties, which represent the
valley with one horizontal hydraulic conductivity field for both aquifers. The
Voronoi-grid models take their aquifer properties from the truth dataset
instead: a separate hydraulic conductivity field for each layer, interpolated
to the cell centers, and the clay's own vertical hydraulic conductivity. Their
other inputs come from the structured model of the same kind, at the
structured cell that holds each Voronoi cell center, except the top, the lake,
and the runoff routing, which come from the land surface raster. The Voronoi
grid is refined along the stream, around the pumping wells, and over the lake
at its largest extent.

## Data

`data` holds the data the models are built from, the forcing, and the truth:

| File | Contents |
|---|---|
| `synthetic_valley_truth.nc` | the truth dataset on the structured grid, in meters: hydraulic conductivity of each layer, the clay and its vertical hydraulic conductivity, layer elevations, and the heads of the original model |
| `synthetic_valley_topography.nc` | the land surface and lake bed on 400 rows by 250 columns of 15.24 m cells, in meters |
| `synthetic_valley_land_surface.nc` | the lake and runoff input of the annual advanced model on the structured grid, which the `mf6-adv-*` notebooks build the advanced model from: the lake cells, the lake bed, the layer the lake leaks to, layer 1 hydraulic conductivity under the lake, where each cell's runoff goes, and the lake volume and area at each lake level |
| `synthetic_valley_vg_truth.nc` | the heads in every cell at the end of each stress period of the Voronoi-grid advanced model, its geometry and hydraulic conductivity, and its observed series: heads at the observation wells, stream flow, the lake level, and the exchange of the lake and stream with the aquifer |
| `obs_well_info.csv` | the 17 observation wells: row and column of the structured grid (counted from 1), location, well depth, and the layer of the lower-aquifer observation |
| `temporal_data_{annual,monthly}.parquet` | precipitation, lake evaporation, and land evapotranspiration in meters per day, and the pumping rates of the two wells in cubic meters per day, for each stress period |

## Rebuilding the models

Run these inside the pixi environment, in this order:

1. `python scripts/build_topography.py --mesh <file>` writes
   `synthetic_valley_topography.nc` from the synthetic-valley mesh
   (`TriMesh_with_densified_contours.exp`, in feet), interpolated linearly
   within its triangles. It is needed only to change the raster.
2. `pixi run build-valley` (`scripts/update_structured_models.py`) puts the top,
   the lake, the seepage drains, and the runoff routing on the base and advanced
   models, in place, and writes `synthetic_valley_land_surface.nc`.
3. `pixi run build-coastal` (`scripts/build_coastal_datasets.py`) makes the
   coastal models from the annual ones.
4. `python scripts/build_vg_grid.py --dest <dir>` builds the Voronoi grid. It is
   needed only to change the grid.
5. `pixi run build-vg` (`scripts/build_vg_models.py`) rebuilds both
   Voronoi-grid models from the structured models, the truth dataset, and the
   raster.
6. `python scripts/write_vg_truth.py --model <run>` writes
   `synthetic_valley_vg_truth.nc` from a run of the Voronoi-grid advanced model.

Runoff is routed over the raster, cell to cell, to the steepest downslope
neighbor after the pits are filled, and each UZF cell's runoff goes to where
most of its raster cells drain: the lake or a stream reach. All of a seepage
drain's discharge goes to the same place as the runoff of its cell. Water whose
path reaches the coast is not moved, since a General-Head Boundary cannot
receive water from MVR. Steps 2, 3, and 5 run each model to find its
steady-state heads.
