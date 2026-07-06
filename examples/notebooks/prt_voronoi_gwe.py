"""Heat-transport (GWE) model for the prt-voronoi notebook.

The GWE model is not the focus of that notebook (PRT is) — it only supplies a
temperature field to colour the particle tracks — and the notebook itself says
the material-property constants are not worth memorizing. So the ~90-line GWE
construction lives here and the notebook just calls ``build_gwe``. Adapted from
MODFLOW 6 example ``ex-gwe-prt``. Import from the notebook working directory so
relative flow-output paths resolve.
"""

import os
from pathlib import Path

import flopy

# GWE material properties (heat transport)
STRT_TEMP = 10.0  # initial temperature (deg C)
ALH = 0.0  # longitudinal mechanical dispersivity (m)
ATH1 = 0.0  # transverse mechanical dispersivity (m)
KTW = 0.56 * 86400  # thermal conductivity of water, W/(m K) -> J/(m day K)
KTS = 2.5 * 86400  # thermal conductivity of solids, W/(m K) -> J/(m day K)
RHOW = 1000.0  # density of water (kg/m^3)
CPW = 4180.0  # heat capacity of water (J/(kg K))
RHOS = 2650.0  # density of dry solid (kg/m^3)
CPS = 900.0  # heat capacity of dry solid (J/(kg K))
LHV = 2500.0  # latent heat of vaporization (J/kg)


def build_gwe(base_ws, gwf_ws, gwf_name, mg, name, porosity, time_unit="days"):
    """Build the GWE heat-transport simulation on the same DISV grid as the flow
    model, reading the flow output in ``gwf_ws`` through its FMI package.

    Uses a different time discretization than flow (1e6 days over 1000 steps) so
    the temperature field approaches steady state. Returns ``(gwe_sim, gwe)``.
    """
    gwe_ws = base_ws / "gwe"
    gwe_ws.mkdir(exist_ok=True, parents=True)

    gwe_sim = flopy.mf6.MFSimulation(
        sim_name=name,
        sim_ws=gwe_ws,
        exe_name="mf6",
    )
    flopy.mf6.ModflowTdis(
        gwe_sim,
        time_units=time_unit,
        perioddata=[[1.0e6, 1000, 1.003]],
    )
    gwe = flopy.mf6.MFModel(
        gwe_sim,
        model_type="gwe6",
        modelname=name,
        model_nam_file=f"{name}.name",
    )
    imsgwe = flopy.mf6.ModflowIms(
        gwe_sim,
        print_option="SUMMARY",
        outer_dvclose=1e-6,
        outer_maximum=1000,
        under_relaxation="NONE",
        inner_maximum=200,
        inner_dvclose=1e-6,
        rcloserecord=1e-6,
        linear_acceleration="BICGSTAB",
        scaling_method="NONE",
        reordering_method="NONE",
        relaxation_factor=1.0,
        filename=f"{name}.ims",
    )
    gwe_sim.register_ims_package(imsgwe, [gwe.name])
    flopy.mf6.ModflowGwedisv(
        gwe,
        nlay=mg.nlay,
        ncpl=mg.ncpl,
        nvert=mg.nvert,
        vertices=mg._vertices,
        cell2d=mg.cell2d,
        top=mg.top[0],
        botm=mg.top_botm[1][0],
    )
    flopy.mf6.ModflowGweic(
        gwe,
        strt=STRT_TEMP,
    )
    flopy.mf6.ModflowGweadv(
        gwe,
        scheme="TVD",
    )
    flopy.mf6.ModflowGwecnd(
        gwe,
        alh=ALH,
        ath1=ATH1,
        ktw=KTW,
        kts=KTS,
    )
    flopy.mf6.ModflowGweest(
        gwe,
        porosity=porosity,
        heat_capacity_water=CPW,
        density_water=RHOW,
        latent_heat_vaporization=LHV,
        heat_capacity_solid=CPS,
        density_solid=RHOS,
    )
    flopy.mf6.ModflowGwessm(
        gwe,
        sources=[("WELL", "AUX", "TEMPERATURE"), ("CHD", "AUX", "TEMPERATURE")],
    )
    flopy.mf6.ModflowGweoc(
        gwe,
        budget_filerecord=f"{name}.cbc",
        temperature_filerecord=f"{name}.ucn",
        saverecord={0: [("TEMPERATURE", "ALL"), ("BUDGET", "ALL")]},
        printrecord=[("TEMPERATURE", "LAST"), ("BUDGET", "LAST")],
    )
    rel_gwf_ws = os.path.relpath(gwf_ws, gwe_ws)
    flopy.mf6.ModflowGwefmi(
        gwe,
        packagedata=[
            ("GWFHEAD", Path(f"{rel_gwf_ws}/{gwf_name}.hds"), None),
            ("GWFBUDGET", Path(f"{rel_gwf_ws}/{gwf_name}.cbc"), None),
        ],
    )
    return gwe_sim, gwe
