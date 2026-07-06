"""Plumbing for the Stallman heat-transport notebook (mf6-gwe-stallman).

The ``StallmanProblem`` class holds the model parameters and derived quantities,
builds the coupled GWF + GWE (and, for Exercise B, an optional GWT "surrogate")
simulation, runs it, evaluates Stallman's analytical solution, and plots or
animates the temperature profiles. Keeping this mechanical setup here lets the
notebook stay focused on the exercises. The physics and the model construction
are unchanged from the original single-notebook version - the module-level
globals simply became attributes of the problem object.
"""

import pathlib as pl

import flopy
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
from mf6_notebook_helpers import seconds_per_year


class StallmanProblem:
    """One-dimensional transient heat transport with a sinusoidal surface
    temperature (the Stallman problem). Create one, then ``build()``, ``write()``
    and ``run()`` it; ``plot(ktau=...)`` shows the temperature profile after
    ``ktau`` surface-temperature cycles against Stallman's analytical solution."""

    def __init__(self, sim_name="gwe-stallman", ws="./models"):
        # Model units
        self.length_units = "meters"
        self.time_units = "seconds"

        # Grid parameters (the +1 layer is an extra, very thin cell at the top)
        self.nlay = 200 + 1
        self.nrow = 1
        self.ncol = 1
        self.delr = 1.0  # Column width (m)
        self.delc = 1.0  # Row width (m)
        self.top = 0.0  # Top elevation of the model, i.e. land surface (m)
        self.bot = -100.0  # Bottom elevation of model (m)

        # Flow parameters
        self.hydraulic_conductivity = 1.0e-4  # (m / s)
        self.darcy_flux = 5.00e-07  # Darcy flux, a.k.a. specific discharge (m / s)

        # Heat-transport parameters
        self.porosity = 0.35
        self.rho_w = 1000  # Density of water (kg / m^3)
        self.rho_s = 2630  # Density of solid (kg / m^3)
        self.c_w = 4174  # Specific heat of water (J / kg / deg_C)
        self.c_s = 800  # Specific heat of solid (J / kg / deg_C)
        self.k_w = 0.58  # Thermal conductivity of water (J / s / m / deg_C)
        self.k_s = 2  # Thermal conductivity of solid (J / s / m / deg_C)
        self.alphal = 0.0  # Longitudinal dispersivity (m)
        self.alphat = 0.0  # Transverse dispersivity (m)

        # Surface-temperature parameters
        self.T_az = 10  # Ambient temperature (deg_C)
        self.dT = 5  # Amplitude of surface-temperature cycle (deg_C)
        self.tau = 1.0 * seconds_per_year  # Period of surface-temperature cycle (s)

        # Simulation timing parameters
        self.ntau = 6  # Number of surface-temperature cycles to simulate
        self.nstptau = 360  # Number of time steps per surface-temperature cycle

        # Solver parameters
        self.nouter = 100
        self.ninner = 300
        self.dvclose = 1e-8
        self.rclose = 1e-8
        self.relax = 0.97

        # Workspace / figure paths
        self.sim_name = sim_name
        self.sim_ws = pl.Path(ws) / sim_name
        self.figs_path = self.sim_ws

        # Derived quantities
        self._derive()

        # Simulation state (populated by build / run / add_gwt_surrogate)
        self.sim = None
        self.gwf = None
        self.gwe = None
        self.gwt = None
        self.sim_gwt = None
        self.zout = None
        self.Tout = []
        self.fake_it_with_gwt = False

    def _derive(self):
        """Compute timing, bulk thermal properties, the analytical-solution
        constants, and the grid-layer bottoms from the base parameters."""
        # Timing
        self.nper = 1  # One stress period covering the whole simulation
        self.perlen = self.tau * self.ntau  # Length of the one stress period (s)
        self.nstp = self.ntau * self.nstptau  # Number of time steps
        self.tslen = self.tau / self.nstptau  # Time step length (s)
        self.per_data = [(self.perlen, self.nstp, 1.0)]

        # Bulk thermal properties
        self.c_rho_w = self.c_w * self.rho_w  # per-volume specific heat, water
        self.c_rho_s = self.c_s * self.rho_s  # per-volume specific heat, solid
        self.c_rho_b = (
            self.porosity * self.c_rho_w + (1 - self.porosity) * self.c_rho_s
        )  # bulk per-volume specific heat
        self.k_b = (
            self.porosity * self.k_w + (1 - self.porosity) * self.k_s
        )  # bulk thermal conductivity
        self.alpha_b = self.k_b / self.c_rho_b  # bulk thermal diffusivity (m^2 / s)
        self.c_rho_ratio = self.c_rho_w / self.c_rho_b  # ratio, for convenience

        # Constants for Stallman's analytical solution
        self.tpot = 2 * np.pi / self.tau
        self.Kstal = np.pi / self.alpha_b / self.tau
        self.Vstal = self.darcy_flux * self.c_rho_ratio / 2 / self.alpha_b
        self.astal = (
            (self.Kstal**2 + self.Vstal**4 / 4) ** 0.5 + self.Vstal**2 / 2
        ) ** 0.5 - self.Vstal
        self.bstal = (
            (self.Kstal**2 + self.Vstal**4 / 4) ** 0.5 - self.Vstal**2 / 2
        ) ** 0.5

        # Grid-layer bottoms: equally spaced, then split the topmost cell into a
        # very thin cell (whose node sits just below land surface, where the
        # surface-temperature boundary is applied) above a slightly-thinner one.
        self.nlay_equal = self.nlay - 1
        self.delz = (self.top - self.bot) / self.nlay_equal
        botm = [self.top - (k + 1) * self.delz for k in range(self.nlay_equal)]
        self.topmost_cell_thickness = 0.00002 * self.delz
        self.topmost_cell_bottom = self.top - self.topmost_cell_thickness
        botm[:0] = [self.topmost_cell_bottom]  # insert new cell bottom at front
        self.botm = botm

    # ------------------------------------------------------------------ data
    def _gwf_data(self):
        """Constant-head boundary data for the flow model (a fixed gradient
        that drives the specified Darcy flux downward through the column)."""
        ztnode = 0.5 * (self.top + self.botm[0])
        zbnode = 0.5 * (self.botm[self.nlay - 2] + self.botm[self.nlay - 1])
        htnode = ztnode
        hgrad = -self.darcy_flux / self.hydraulic_conductivity
        hbnode = htnode - (zbnode - ztnode) * hgrad
        return {0: [[(0, 0, 0), htnode], [(self.nlay - 1, 0, 0), hbnode]]}

    def _gwe_data(self):
        """Initial temperatures, the sinusoidal surface-temperature time series,
        and the constant-temperature cell record for the transport model."""
        Tstrt = self.T_az * np.ones((self.nlay, 1, 1), dtype=np.float32)
        ts_data = []
        for n in range(0, self.nstp + 1):
            t = n * self.tslen
            Tsurf = self.T_az + self.dT * np.sin(self.tpot * t)
            ts_data.append((t, Tsurf))
        ts_dict = {
            "filename": "Tsurf0.ts",
            "time_series_namerecord": "Tsurf",
            "timeseries": ts_data,
            "interpolation_methodrecord": "linear",
        }
        ctp_data = [((0, 0, 0), "Tsurf")]
        return Tstrt, ts_dict, ctp_data

    # -------------------------------------------------------------- builders
    def _build_gwf_model(self, sim):
        print(f"Building GWF model for {sim.name}")
        chd_data = self._gwf_data()

        gwf = flopy.mf6.ModflowGwf(
            sim,
            modelname="gwf",
            save_flows=True,
        )

        ims = flopy.mf6.ModflowIms(
            sim,
            print_option="ALL",
            outer_dvclose=self.dvclose,
            outer_maximum=self.nouter,
            under_relaxation="NONE",
            inner_maximum=self.ninner,
            inner_dvclose=self.dvclose,
            rcloserecord=self.rclose,
            linear_acceleration="CG",
            scaling_method="NONE",
            reordering_method="NONE",
            relaxation_factor=self.relax,
            filename=f"{gwf.name}.ims",
        )
        sim.register_ims_package(ims, [gwf.name])

        flopy.mf6.ModflowGwfdis(
            gwf,
            length_units=self.length_units,
            nlay=self.nlay,
            nrow=self.nrow,
            ncol=self.ncol,
            delr=self.delr,
            delc=self.delc,
            top=self.top,
            botm=self.botm,
        )
        flopy.mf6.ModflowGwfnpf(
            gwf,
            save_specific_discharge=True,
            save_saturation=True,
            save_flows=True,
            icelltype=0,
            k=self.hydraulic_conductivity,
        )
        flopy.mf6.ModflowGwfic(
            gwf,
            strt=self.top,
        )
        flopy.mf6.ModflowGwfchd(
            gwf,
            stress_period_data=chd_data,
        )
        flopy.mf6.ModflowGwfoc(
            gwf,
            head_filerecord=f"{gwf.name}.hds",
            budget_filerecord=f"{gwf.name}.bud",
            saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        )
        return gwf

    def _build_gwe_model(self, sim):
        print(f"Building GWE model for {sim.name}")
        Tstrt, ts_dict, ctp_data = self._gwe_data()

        gwe = flopy.mf6.ModflowGwe(
            sim,
            modelname="gwe",
        )

        imsgwe = flopy.mf6.ModflowIms(
            sim,
            print_option="ALL",
            outer_dvclose=self.dvclose,
            outer_maximum=self.nouter,
            under_relaxation="NONE",
            inner_maximum=self.ninner,
            inner_dvclose=self.dvclose,
            rcloserecord=self.rclose,
            linear_acceleration="BICGSTAB",
            scaling_method="NONE",
            reordering_method="NONE",
            relaxation_factor=self.relax,
            filename=f"{gwe.name}.ims",
        )
        sim.register_ims_package(imsgwe, [gwe.name])

        flopy.mf6.ModflowGwedis(
            gwe,
            length_units=self.length_units,
            nlay=self.nlay,
            nrow=self.nrow,
            ncol=self.ncol,
            delr=self.delr,
            delc=self.delc,
            top=self.top,
            botm=self.botm,
        )
        flopy.mf6.ModflowGweest(
            gwe,
            porosity=self.porosity,
            heat_capacity_solid=self.c_s,
            density_solid=self.rho_s,
            heat_capacity_water=self.c_w,
            density_water=self.rho_w,
        )
        flopy.mf6.ModflowGweic(
            gwe,
            strt=Tstrt,
        )
        flopy.mf6.ModflowGweadv(
            gwe,
            scheme="TVD",
        )
        flopy.mf6.ModflowGwecnd(
            gwe,
            xt3d_off=True,
            alh=self.alphal,
            ath1=self.alphat,
            ktw=self.k_w,
            kts=self.k_s,
        )
        flopy.mf6.ModflowGwessm(
            gwe,
            sources=[[]],
        )
        ctp = flopy.mf6.ModflowGwectp(
            gwe,
            stress_period_data=ctp_data,
            timeseries=ts_dict,
        )
        ctp.ts.time_series_namerecord = "Tsurf"
        flopy.mf6.ModflowGweoc(
            gwe,
            budget_filerecord=f"{gwe.name}.cbc",
            temperature_filerecord=f"{gwe.name}.ucn",
            temperatureprintrecord=[
                ("COLUMNS", 10, "WIDTH", 15, "DIGITS", 6, "GENERAL")
            ],
            saverecord=[("TEMPERATURE", "ALL")],
            printrecord=[("TEMPERATURE", "ALL"), ("BUDGET", "LAST")],
        )
        flopy.mf6.ModflowGwfgwe(
            sim,
            exgtype="GWF6-GWE6",
            exgmnamea=self.gwf.name,
            exgmnameb=gwe.name,
        )
        return gwe

    def _build_gwt_model(self, sim, bulk_density=1, distcoef=1, diffc=1):
        print(f"Building GWT model for {sim.name}")
        Tstrt, ts_dict, ctp_data = self._gwe_data()

        gwt = flopy.mf6.ModflowGwt(
            sim,
            modelname="gwt",
        )

        imsgwt = flopy.mf6.ModflowIms(
            sim,
            print_option="ALL",
            outer_dvclose=self.dvclose,
            outer_maximum=self.nouter,
            under_relaxation="NONE",
            inner_maximum=self.ninner,
            inner_dvclose=self.dvclose,
            rcloserecord=self.rclose,
            linear_acceleration="BICGSTAB",
            scaling_method="NONE",
            reordering_method="NONE",
            relaxation_factor=self.relax,
            filename=f"{gwt.name}.ims",
        )
        sim.register_ims_package(imsgwt, [gwt.name])

        flopy.mf6.ModflowGwtdis(
            gwt,
            length_units=self.length_units,
            nlay=self.nlay,
            nrow=self.nrow,
            ncol=self.ncol,
            delr=self.delr,
            delc=self.delc,
            top=self.top,
            botm=self.botm,
        )
        flopy.mf6.ModflowGwtmst(
            gwt,
            porosity=self.porosity,
            sorption="linear",
            bulk_density=bulk_density,
            distcoef=distcoef,
        )
        flopy.mf6.ModflowGwtic(
            gwt,
            strt=Tstrt,
        )
        flopy.mf6.ModflowGwtadv(
            gwt,
            scheme="TVD",
        )
        flopy.mf6.ModflowGwtdsp(
            gwt,
            xt3d_off=True,
            alh=self.alphal,
            ath1=self.alphat,
            diffc=diffc,
        )
        flopy.mf6.ModflowGwtssm(
            gwt,
            sources=[[]],
        )
        cnc = flopy.mf6.ModflowGwtcnc(
            gwt,
            stress_period_data=ctp_data,
            timeseries=ts_dict,
        )
        cnc.ts.time_series_namerecord = "Tsurf"
        flopy.mf6.ModflowGwtoc(
            gwt,
            budget_filerecord=f"{gwt.name}.cbc",
            concentration_filerecord=f"{gwt.name}.ucn",
            concentrationprintrecord=[
                ("COLUMNS", 10, "WIDTH", 15, "DIGITS", 6, "GENERAL")
            ],
            saverecord=[("CONCENTRATION", "ALL")],
            printrecord=[("CONCENTRATION", "ALL"), ("BUDGET", "LAST")],
        )
        flopy.mf6.ModflowGwtfmi(
            gwt,
            packagedata=[
                ("GWFHEAD", "gwf.hds"),
                ("GWFBUDGET", "gwf.bud"),
            ],
        )
        return gwt

    # ---------------------------------------------------------- build / run
    def build(self):
        """Create the coupled GWF + GWE simulation (Exercise A base case)."""
        sim = flopy.mf6.MFSimulation(
            sim_name=self.sim_name,
            sim_ws=self.sim_ws,
            exe_name="mf6",
        )
        flopy.mf6.ModflowTdis(
            sim,
            nper=self.nper,
            perioddata=self.per_data,
            time_units=self.time_units,
        )
        self.sim = sim
        self.gwf = self._build_gwf_model(sim)
        self.gwe = self._build_gwe_model(sim)
        self.fake_it_with_gwt = False
        return sim

    def write(self):
        self.sim.write_simulation(silent=True)

    def run(self):
        """Run the GWF + GWE simulation and store node elevations (``zout``) and
        the GWE temperature output (``Tout[0]``)."""
        print("Running simulation ...")
        success, buff = self.sim.run_simulation(silent=True)
        assert success, "MODFLOW 6 did not terminate normally"
        print("Run finished")
        self.zout = self.gwf.modelgrid.zcellcenters.flatten()
        self.Tout = [self.gwe.output.temperature()]
        return self.zout, self.Tout

    def add_gwt_surrogate(self):
        """Exercise B, step 1: build and write a separate GWT simulation that
        will emulate heat transport once its surrogate parameters are set."""
        sim_gwt = flopy.mf6.MFSimulation(
            sim_name=self.sim_name + "_gwt",
            sim_ws=self.sim_ws,
            exe_name="mf6",
        )
        flopy.mf6.ModflowTdis(
            sim_gwt,
            nper=self.nper,
            perioddata=self.per_data,
            time_units=self.time_units,
        )
        self.sim_gwt = sim_gwt
        self.gwt = self._build_gwt_model(sim_gwt)
        self.fake_it_with_gwt = True
        sim_gwt.write_simulation(silent=True)

    def run_gwt_surrogate(self, bulk_density, distcoef, diffc):
        """Exercise B, step 2: set the surrogate sorption/diffusion parameters,
        rewrite the affected packages, run the GWT model, and store its output
        as ``Tout[1]`` so it can be plotted alongside GWE and the analytical
        solution."""
        self.gwt.mst.bulk_density = bulk_density
        self.gwt.mst.distcoef = distcoef
        self.gwt.mst.write()
        self.gwt.dsp.diffc = diffc
        self.gwt.dsp.write()
        success, buff = self.sim_gwt.run_simulation(silent=True)
        assert success, "MODFLOW 6 did not terminate normally"
        conc = self.gwt.output.concentration()
        if len(self.Tout) == 1:
            self.Tout.append(conc)
        else:
            self.Tout[1] = conc

    # --------------------------------------------------- analytical + plots
    def stallman(self, t, zvalues):
        """Stallman's analytical temperature at time ``t`` for a list of
        elevations ``zvalues``."""
        Tstal = np.zeros(len(zvalues))
        for i in range(len(zvalues)):
            depth = -zvalues[i]
            Tstal[i] = self.T_az + self.dT * np.exp(-self.astal * depth) * np.sin(
                self.tpot * t - self.bstal * depth
            )
        return Tstal

    def _label_marker(self):
        label = ["Analytical solution"]
        marker = ["k--"]
        label.append("GWE")
        marker.append("bo")  # blue circles for GWE
        if self.fake_it_with_gwt:
            label.append("GWT")
            marker.append("r+")  # red plusses for GWT
        return label, marker

    def _extract(self, kstp="all"):
        """Assemble analytical and simulated temperature profiles for plotting.
        ``kstp`` is a 0-based time-step index, or ``"all"`` for every time."""
        if kstp == "all":
            tplot = np.array(self.Tout[0].get_times())
        else:
            tplot = [np.array(self.Tout[0].get_times())[kstp]]

        Tplot = []
        Tplot0 = []
        for t in tplot:
            Tplot0.append(self.stallman(t, self.zout))
        Tplot.append(np.array(Tplot0))
        for idx in range(len(self.Tout)):
            if kstp == "all":
                Tplot.append(self.Tout[idx].get_alldata().reshape(Tplot[0].shape))
            else:
                Tplot.append([self.Tout[idx].get_data(totim=tplot[0]).flatten()])
        return tplot, np.array(Tplot)

    def _plot_temperature_profiles(self, tplot, Tplot, zplot, framestride=1):
        animate = len(tplot) > 1
        label, marker = self._label_marker()

        fig = plt.figure(figsize=(6, 4))
        ax = fig.add_subplot(1, 1, 1)
        ax.set_xlim(self.T_az - self.dT, self.T_az + self.dT)
        ax.set_ylim(self.bot, self.top)
        ax.set_ylabel("z (m)")
        ax.set_xlabel("Temperature (deg C)")

        def update(kplot):
            for idx in range(len(Tplot)):
                graph[idx].set_data(Tplot[idx, kplot, :], zplot)
            t = tplot[kplot]
            ax.set_title(f"Time = {t:.1f} seconds ({t / seconds_per_year:.4f} years)")

        graph = [0] * len(Tplot)
        for idx in reversed(range(len(Tplot))):  # so graph[0] is plotted on top
            graph[idx] = ax.plot(
                [], [], marker[idx], mfc="none", label=label[idx], linewidth=1.0
            )[0]
        update(0)
        ax.legend(loc="lower left")

        if animate:
            frames = range(0, tplot.shape[0], framestride)
            ani = animation.FuncAnimation(fig, update, frames=frames)
            fpth = self.figs_path / f"{self.sim_name}-temperature.gif"
            ani.save(fpth, fps=5)
            print("Animated gif saved to", fpth)
            plt.close()
            return ani

        plt.show()
        fpth = self.figs_path / f"{self.sim_name}-temperature.png"
        fig.savefig(fpth)
        print("Figure is saved to", fpth)

    def plot(self, ktau):
        """Static temperature profile at the end of ``ktau`` surface-temperature
        cycles (``ktau`` may be fractional, e.g. 1.5, and must be <= ``ntau``)."""
        kstp = round(ktau * self.nstptau) - 1  # "-1": time-step numbering is 0-based
        tplot, Tplot = self._extract(kstp)
        return self._plot_temperature_profiles(tplot, Tplot, self.zout)

    def animate(self, framestride=1):
        """Animate the temperature profile over all times and return the
        ``FuncAnimation`` (wrap in ``IPython.display.HTML(ani.to_jshtml())`` to
        show it). ``framestride`` thins the frames to speed up generation."""
        tplot, Tplot = self._extract("all")
        return self._plot_temperature_profiles(
            tplot, Tplot, self.zout, framestride=framestride
        )
