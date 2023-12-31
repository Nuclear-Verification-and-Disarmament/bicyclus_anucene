#!/usr/bin/env python3

"""Classes to efficiently analyse lots of Cyclus output files."""

import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union


import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import rcParams
from mpi4py import MPI
from bs4 import BeautifulSoup

rcParams["axes.formatter.limits"] = -5, 4
sns.set_theme(style="darkgrid", context="paper", font="serif", font_scale=1)


@dataclass
class AnalyseAllFiles:
    """Class to efficiently analyse a large amount of Cyclus output files."""

    data_path: Union[Path, str]
    imgs_path: Union[Path, str]
    job_id: field(default="")
    max_files: field(default=0)

    def __post_init__(self):
        """Set up more attributes immediately after object initialisation."""
        self.data_path = Path(self.data_path)
        self.imgs_path = Path(self.imgs_path)
        try:
            self.imgs_path.mkdir(mode=0o760, parents=True, exist_ok=False)
            print(f"Creating path {self.imgs_path}")
        except FileExistsError:
            print(f"Path {self.imgs_path} already exists.")

        self.data_fname = self.imgs_path / "data.h5"
        self.sqlite_files = self.get_files()
        self.data = []

    def get_files(self):
        """Get list of all filenames to be used in the analysis."""
        sqlite_files = []
        for dirpath, _, filenames in os.walk(self.data_path):
            for f in filenames:
                if f.endswith(".sqlite") and self.job_id in f:
                    sqlite_files.append(os.path.join(dirpath, f))

        if self.max_files:
            sqlite_files = sqlite_files[: self.max_files]
        return sqlite_files

    def get_data(self, force_update=False, store_data=True):
        """Extract data from sqlite files using MPI.

        Parameters
        ----------
        force_update : bool, optional
            If True, always extract data from sqlite files.
            If False (default), only do so in case no presaved data file
            (data.h5) is available.

        store_data : bool, optional
            Store data as .h5 file.
        """

        def print_mpi(msg, **kwargs):
            """Helper function to get consistent MPI output."""
            print(
                f"Rank {rank:2}, "
                f"{time.strftime('%y/%m/%d %H:%M:%S', time.localtime())}   " + msg,
                **kwargs,
            )

        if os.path.isfile(self.data_fname) and not force_update:
            self.data = pd.read_hdf(self.data_fname, key="df")
            print(f"Read in data from {self.data_fname}")
            return

        comm = MPI.COMM_WORLD
        rank = comm.Get_rank()
        size = comm.Get_size()

        if rank == 0:
            # Maybe not the most elegant solution to distribute tasks but it works
            # and distributes them evenly.
            print_mpi(f"Analysing {len(self.sqlite_files)} in total.")
            n_per_task = len(self.sqlite_files) // size
            files_per_task = [
                self.sqlite_files[i * n_per_task : (i + 1) * n_per_task]
                for i in range(size)
            ]
            i = 0
            while i < len(self.sqlite_files) % size:
                files_per_task[i % size].append(
                    self.sqlite_files[size * n_per_task + i]
                )
                i += 1
        else:
            files_per_task = None

        files_per_task = comm.scatter(files_per_task, root=0)
        print_mpi(f"Received list of {len(files_per_task)} files.")

        # Keys: name of extracted data, values: lists with data
        d = defaultdict(list)
        for i, f in enumerate(files_per_task):
            if i % 50 == 0:
                print_mpi(f"{i:3}/{len(files_per_task)}")

            a = SqliteAnalyser(f, verbose=False)

            d["total_heu"].append(a.material_transfers(-1, "WeapongradeUSink")[1])
            d["total_pu"].append(a.material_transfers(-1, "SeparatedPuSink")[1])
            d["swu_sampled"].append(a.swu_sampled("EnrichmentFacility"))
            d["swu_available"].append(a.swu_available("EnrichmentFacility")[1])
            d["swu_used"].append(a.swu_used("EnrichmentFacility")[1])
            enrichment_feeds = a.enrichment_feeds("EnrichmentFacility")
            for feed_type, feed_qty in enrichment_feeds.items():
                d[f"enrichment_feed_{feed_type}"].append(feed_qty)

            d["NU_to_enrichment"].append(
                a.material_transfers("NaturalUStorage", "EnrichmentFacility")[1]
            )
            d["NU_to_reactors"].append(a.material_transfers("FreshFuelStorage", -1)[1])

            reactor_ops = a.all_reactor_operations(
                [f"Khushab{i}" for i in range(1, 5)]
            )["total"]
            d["capacity_factor_planned"].append(reactor_ops["capacity_factor_planned"])
            d["capacity_factor_used"].append(reactor_ops["capacity_factor_used"])
            d["dep_U_mass"].append(a.material_transfers(-1, "DepletedUSink")[1])
            d["cs137_mass"].append(a.cs137_mass("FinalWasteSink"))

        gatherdata = pd.DataFrame(d)
        gatherdata = comm.gather(gatherdata, root=0)
        print_mpi("Gathered data")

        if rank != 0:
            print_mpi("Exiting function")
            sys.exit()
        print_mpi("Leaving parallelised section.")
        print_mpi("=============================\n")

        print_mpi("Concatenating dataframes")
        data = gatherdata[0]
        for d in gatherdata[1:]:
            data = pd.concat([data, d], axis=0, ignore_index=True)

        self.data = data

        if store_data:
            data.to_hdf(self.data_fname, key="df", mode="w")
            print_mpi(f"Successfully stored data under {self.data_fname}.\n")

    def plot_1d_histogram(self, quantity, **hist_kwargs):
        """Generate seaborn 1D histogram."""
        n_entries = len(self.data[quantity])
        _, ax = plt.subplots(constrained_layout=True)
        sns.histplot(data=self.data, x=quantity, **hist_kwargs, ax=ax)
        ax.legend(labels=[f"#entries={n_entries}"])
        ax.set_xlabel(quantity.replace("_", " "))
        plt.savefig(self.imgs_path / f"histogram_{quantity}.png")
        plt.close()

    def plot_all_1d_histograms(self, **hist_kwargs):
        """Generate 1D histograms for all quantities stored in the data.

        Parameters
        ----------
        hist_kwargs : kwargs
            Keyword arguments passed to seaborn.histplot.
        """
        for quantity in self.data.columns:
            self.plot_1d_histogram(quantity, **hist_kwargs)

    def plot_2d_scatterplots(self, x, y, marginals=False, **plot_kwargs):
        """Generate seaborn 2D histogram."""
        if marginals:
            g = sns.JointGrid(data=self.data, x=x, y=y)
            g.plot_joint(sns.scatterplot)
            g.plot_marginals(sns.histplot, kde=True)
            g.set_axis_labels(x.replace("_", " "), y.replace("_", " "))
            g.savefig(self.imgs_path / f"scatter_{x}_{y}.png")
            plt.close()

            return

        n_entries = len(self.data[x])
        _, ax = plt.subplots(constrained_layout=True)
        sns.scatterplot(data=self.data, x=x, y=y, **plot_kwargs, ax=ax)
        ax.legend(labels=[f"#entries={n_entries}"])
        ax.set_xlabel(x.replace("_", " "))
        ax.set_ylabel(y.replace("_", " "))
        plt.savefig(self.imgs_path / f"scatter_{x}_{y}.png")
        plt.close()

    def pairplots(self, subset=None, fname=None):
        """Create a Seaborn pairplot.

        WARNING: This can be computationally expensive and can potentially
        generate very large plots.

        Parameters
        ----------
        subset : None or list of str, optional
            If None, use all data to generate the pairplot. If not None, this
            variable must contain a list of columns from self.data. Only these
            columns will be used to obtain the pairplot.
        """
        fname = "pairplot.png" if fname is None else fname
        data = self.data if subset is None else self.data[subset]

        pairplot_grid = sns.PairGrid(data, diag_sharey=False)
        pairplot_grid.map_upper(sns.kdeplot)
        pairplot_grid.map_diag(sns.histplot)
        pairplot_grid.map_lower(sns.scatterplot)
        plt.savefig(self.imgs_path / "pairplot.png")
        plt.close()

    def used_vs_planned_capacity_factor(self):
        """Plot the used vs. the planned overall capacity factor."""
        min_max = (
            min(self.data["capacity_factor_planned"]),
            max(self.data["capacity_factor_used"]),
        )
        _, ax = plt.subplots(constrained_layout=True)
        sns.scatterplot(
            data=self.data, x="capacity_factor_planned", y="capacity_factor_used", ax=ax
        )
        ax.plot(min_max, min_max, color="C3")
        plt.savefig(self.imgs_path / "cap_factors.png")
        plt.close()


class SqliteAnalyser:
    """Class to analyse Cyclus .sqlite output files."""

    def __init__(self, fname, verbose=True):
        """Initialise Analyser object.

        Parameters
        ----------
        fname : Path
            Path to .sqlite file

        verbose : bool, optional
            If true, increase verbosity of output.
        """
        self.fname = fname
        if not os.path.isfile(self.fname):
            msg = f"File {os.path.abspath(self.fname)} does not exist!"
            raise FileNotFoundError(msg)

        self.verbose = verbose
        if self.verbose:
            print(f"Opened connection to file {self.fname}.")

        self.connection = sqlite3.connect(self.fname)
        self.cursor = self.connection.cursor()
        # self.t_init = self.get_initial_time()
        self.duration = self.cursor.execute("SELECT Duration FROM Info").fetchone()[0]

        # (key,value): (agent_id, name), (name, agent_id),
        #              (spec, agent_id), (agent_id, spec)
        (self.agents, self.names, self.specs, self.agent_ids) = self.get_agents()

    def __del__(self):
        """Destructor closes the connection to the file."""
        try:
            self.connection.close()
            if self.verbose:
                print(f"Closed connection to file {self.fname}.")
        except AttributeError as e:
            raise RuntimeError(f"Error while closing file {self.fname}") from e

    def get_agents(self):
        """Get all agents that took part in the simulation.

        Returns
        -------
        dict : agent ID (int) -> agent name (str)
        dict : agent name (str) -> agent ID (int)
        dict : agent spec (str) -> agent ID (int)
        dict : agent ID (int) -> agent spec (str)
        """
        query = self.cursor.execute(
            "SELECT Spec, AgentId, Prototype FROM AgentEntry"
        ).fetchall()

        agents = {}
        names = {}
        specs = defaultdict(list)
        agent_ids = {}
        for agent in query:
            # Get the spec (without :agent: or :cycamore: etc. prefix)
            spec = str(agent[0])
            idx = [m.start() for m in re.finditer(":", spec)][-1]
            spec = spec[idx + 1 :]

            agent_id = int(agent[1])
            name = str(agent[2])

            agents[agent_id] = name
            names[name] = agent_id
            specs[spec].append(agent_id)
            agent_ids[agent_id] = spec

        return agents, names, specs, agent_ids

    def agent_id_or_name(self, agent_id_or_name):
        """Helper function to convert agent names into agent IDs."""
        if isinstance(agent_id_or_name, str):
            try:
                return self.names[agent_id_or_name]
            except KeyError as e:
                msg = f"Invalid agent name! Valid names are {self.names.keys()}."
                raise KeyError(msg) from e
        elif isinstance(agent_id_or_name, int):
            return agent_id_or_name
        else:
            raise ValueError("`agent_id_or_name` must be agent name (str) or id (int)!")

    def material_transfers(self, sender_id_or_name, receiver_id_or_name, sum_=True):
        """Get all material transfers between two facilities.

        Parameters
        ----------
        sender_id_or_name, receiver_id_or_name : int or str
            Agent IDs or agent names of sender and receiver, respectively. Use
            '-1' as placeholder for 'all facilities'.

        sum_ : bool, optional
            If true, sum over all timesteps.

        Returns
        -------
        transfer_array : np.array of shape (number of transfers, 2)
            The first element of each entry is the timestep of the transfer,
            the second is its mass. If sum_ is True, then the second element
            is the total mass (over all timesteps) and the time is set to -1.
        """
        sender_id = self.agent_id_or_name(sender_id_or_name)
        receiver_id = self.agent_id_or_name(receiver_id_or_name)

        sender_cond = "" if sender_id == -1 else "SenderId = :sender_id "
        recv_cond = "" if receiver_id == -1 else "ReceiverId = :receiver_id "

        if sender_cond and recv_cond:
            sqlite_condition = f"WHERE ({sender_cond} AND {recv_cond})"
        else:
            sqlite_condition = f"WHERE ({sender_cond}{recv_cond})"

        sender_receiver = {"sender_id": sender_id, "receiver_id": receiver_id}
        transfer_times = self.cursor.execute(
            f"SELECT Time FROM Transactions {sqlite_condition}", sender_receiver
        ).fetchall()
        transfer_masses = self.cursor.execute(
            "SELECT Quantity FROM Resources WHERE ResourceId IN "
            f"(SELECT ResourceId FROM Transactions {sqlite_condition});",
            sender_receiver,
        ).fetchall()

        transfer_array = np.array(
            [[time[0], mass[0]] for time, mass in zip(transfer_times, transfer_masses)]
        )

        if sum_:
            return np.array([-1, transfer_array[:, 1].sum()])

        return transfer_array

    def enrichment_feeds(self, agent_id_or_name):
        """Get the amount of each enrichment feed that got used."""
        agent_id = self.agent_id_or_name(agent_id_or_name)
        query = self.cursor.execute(
            "SELECT Value, Units FROM TimeSeriesEnrichmentFeed WHERE AgentId = :agent_id",
            {"agent_id": agent_id},
        ).fetchall()
        feeds = defaultdict(float)
        for value, feed in query:
            feeds[feed] += value
        return feeds

    def swu_sampled(self, agent_id_or_name):
        """Get the SWU available to one enrichment facility.

        Parameters
        ----------
        agent_id_or_name : str or int
            Agent ID or agent name

        Returns
        -------
        Last used separative power in kgSWU / year : float
        """
        agent_id = self.agent_id_or_name(agent_id_or_name)
        timestep = self.cursor.execute(
            "SELECT DurationSecs FROM TimeStepDur"
        ).fetchone()[0]
        data = self.cursor.execute(
            "SELECT swu_capacity_vals FROM "
            "AgentState_flexicamore_FlexibleEnrichmentInfo WHERE AgentId = :agent_id",
            {"agent_id": agent_id},
        ).fetchone()  # Boost vector with SWUs

        # Convert Boost vectors (in XML) into Python float in units of simulation
        # timesteps.
        swu_in_sim_ts = float(
            BeautifulSoup(data[-1], "xml").find_all("item")[-1].get_text()
        )
        # Convert to SWU / years
        return swu_in_sim_ts / timestep * 86400.0 * 365.0

    def swu_available(self, agent_id_or_name, sum_=True):
        """Get the SWU available to one enrichment facility.

        Parameters
        ----------
        agent_id_or_name : str or int
            Agent ID or agent name

        sum_ : bool, optional
            If True, only yield the total available SWU (summed over all
            timesteps).

        Returns
        -------
        np.array of shape (number of timesteps, 2) if `sum_` is False, else of
        shape (-2)
        """
        agent_id = self.agent_id_or_name(agent_id_or_name)
        enter_time = self.cursor.execute(
            "SELECT EnterTime FROM AgentEntry WHERE AgentId = :agent_id",
            {"agent_id": agent_id},
        ).fetchone()[0]
        data = self.cursor.execute(
            "SELECT swu_capacity_times, swu_capacity_vals FROM "
            "AgentState_flexicamore_FlexibleEnrichmentInfo WHERE AgentId = :agent_id",
            {"agent_id": agent_id},
        ).fetchone()  # (Boost vector with times, Boost vector with SWUs)

        # Convert Boost vectors (in XML) into Python lists.
        swu_times = []
        swu_vals = []
        for list_, cyclus_data in zip(
            (swu_times, swu_vals), [BeautifulSoup(d, "xml") for d in data]
        ):
            for item_ in cyclus_data.find_all("item"):
                list_.append(float(item_.get_text()))

        # Fill with timesteps where SWU was not changed.
        complete_list = []
        previous_time = swu_times[0]
        previous_val = swu_vals[0]
        # Ensure to take last SWU increase into account.
        if swu_times[-1] + enter_time < self.duration:
            swu_times.append(self.duration - enter_time)
            swu_vals.append(swu_vals[-1])
        for time, val in zip(swu_times, swu_vals):
            for t in range(int(previous_time), int(time)):
                complete_list += [[t, previous_val]]
            previous_time = time
            previous_val = val

        # Convert to array and transform timesteps since deployment to timesteps since
        # start of the simulation.
        swu_available = np.array(complete_list)
        swu_available[:, 0] += enter_time

        if sum_:
            return np.array([-1, swu_available[:, 1].sum()])
        return swu_available

    def swu_used(self, agent_id_or_name, sum_=True):
        """Get the SWU used by one enrichment facility.

        Parameters
        ----------
        agent_id_or_name : str or int
            Agent ID or agent name

        sum_ : bool, optional
            If True, only yield the total SWU used (summed over all timesteps).

        Returns
        -------
        np.array of shape (number of timesteps, 2) if `sum_` is False, else of
        shape (-2)
        """
        agent_id = self.agent_id_or_name(agent_id_or_name)
        query = self.cursor.execute(
            "SELECT Time, Value FROM TimeSeriesEnrichmentSWU WHERE AgentId = :agent_id",
            {"agent_id": agent_id},
        ).fetchall()
        rval = np.array(query, dtype=float)
        if sum_:
            return np.array([-1, rval[:, 1].sum()])

        return rval

    def cs137_mass(self, agent_id_or_name):
        """Get the total mass of Cs137 present in the inventory of the agent."""
        agent_id = self.agent_id_or_name(agent_id_or_name)

        resource_id = self.cursor.execute(
            "SELECT ResourceId FROM Transactions WHERE ReceiverId = :receiver_id",
            {"receiver_id": agent_id},
        ).fetchone()
        composition_id, spent_fuel_qty = self.cursor.execute(
            "SELECT QualId, Quantity FROM Resources WHERE ResourceId = :resource_id",
            {"resource_id": resource_id[0]},
        ).fetchone()
        mass_fractions = dict(
            self.cursor.execute(
                "SELECT NucId, MassFrac FROM Compositions WHERE QualId = :composition_id",
                {"composition_id": composition_id},
            ).fetchall()
        )
        cs137_mass_frac = mass_fractions[551370000] / sum(mass_fractions.values())

        return spent_fuel_qty * cs137_mass_frac

    def capacity_factor_planned(self, agent_id_or_name):
        """Get the planned capacity factor of one reactor.

        Note that this value corresponds to the capacity factor *as indicated
        in Cyclus' input file. Thus, the actual capacity factor (online time /
        total time) may be smaller than this value, e.g., in case of missing
        fresh fuel.

        Parameters
        ----------
        agent_id_or_name : str or int
            Agent ID or agent name

        Returns
        -------
        dict with keys cycle_time, refuelling_time, capacity_factor
        """
        agent_id = self.agent_id_or_name(agent_id_or_name)
        if self.agent_ids[agent_id] != "Reactor":
            msg = f"Agent ID {agent_id} does not correspond to a 'Reactor' facility"
            raise ValueError(msg)

        cycle_time, refuelling_time = self.cursor.execute(
            "SELECT cycle_time, refuel_time FROM AgentState_cycamore_ReactorInfo "
            "WHERE AgentId = :agent_id",
            {"agent_id": agent_id},
        ).fetchone()
        return {
            "cycle_time": cycle_time,
            "refuelling_time": refuelling_time,
            "capacity_factor_planned": cycle_time / (cycle_time + refuelling_time),
        }

    def reactor_operations(self, agent_id_or_name):
        """Calculate reactor stats such as the effective capacity factor.

        Parameters
        ----------
        agent_id_or_name : str or int
            Agent ID or agent name

        Returns
        -------
        dict with keys:
            'n_start',
            'n_end',
            'cycle_time',
            'refuelling_time',
            'capacity_factor_planned',
            'capacity_factor_used',
            'in_sim_time',
            'total_cf_time',

            Note that 'total_cf_time' is the total time considered in the
            calculation of the capacity factor.
        """
        agent_id = self.agent_id_or_name(agent_id_or_name)
        data = self.capacity_factor_planned(agent_id)
        enter_time, lifetime = self.cursor.execute(
            "SELECT EnterTime, Lifetime FROM AgentEntry WHERE AgentId = :agent_id",
            {"agent_id": agent_id},
        ).fetchone()
        in_sim_time = lifetime if lifetime != -1 else self.duration - enter_time
        data["in_sim_time"] = in_sim_time

        # Keywords used in 'ReactorEvents' table.
        cycle_start = "CYCLE_START"
        cycle_end = "CYCLE_END"

        reactor_events = self.cursor.execute(
            "SELECT Time, Event FROM ReactorEvents WHERE (AgentId = :agent_id)"
            " AND (Event = :cycle_start or Event = :cycle_end)",
            {"agent_id": agent_id, "cycle_start": cycle_start, "cycle_end": cycle_end},
        ).fetchall()
        data["n_start"] = sum(event == cycle_start for _, event in reactor_events)
        data["n_end"] = sum(event == cycle_end for _, event in reactor_events)

        # We cannot calculate the capacity factor if there are not at least
        # three events (i.e., cycle start, cycle end and another cycle start).
        if len(reactor_events) < 3:
            msg = "Need at least 3 events to be able to calculate the capacity factor."
            raise RuntimeError(msg)

        # We only consider complete cycles including refueling period.
        if reactor_events[-1][1] == cycle_start:
            online_time = data["n_end"] * data["cycle_time"]
            total_time = reactor_events[-1][0] - reactor_events[0][0]
        else:  # Last event = cycle_end
            time_to_sim_end = self.duration - reactor_events[-1][0]
            if time_to_sim_end > data["refuelling_time"]:
                # New cycle could have been started but did not --> This needs to be
                # taken into account in the capacity factor.
                online_time = data["n_end"] * data["cycle_time"]
                total_time = self.duration - reactor_events[0][0]
            else:
                # New cycle could not have been started before end of simulation
                # --> Do not take this cycle into account.
                online_time = (data["n_end"] - 1) * data["cycle_time"]
                total_time = reactor_events[-2][0] - reactor_events[0][0]

        data["capacity_factor_used"] = online_time / total_time
        data["total_cf_time"] = total_time

        return data

    def all_reactor_operations(self, agent_ids_or_names):
        """Get an overview over all reactor operations for all reactors.

        Parameters
        ----------
        agent_ids_or_name : iterable of int or str
            Values must be valid agent IDs or agent names.

        Returns
        -------
        dict: (str, int) -> dict: str -> float
            Keys of the 'outer' dict are 'total' and all reactor agent IDs.
            The 'inner' dict contains the following keys:
                'n_start',
                'n_end',
                'cycle_time',
                'refuelling_time',
                'capacity_factor_planned',
                'capacity_factor_used',
                'in_sim_time',
                'total_cf_time',
            except for the 'total' dict which contains only a subset of keys:
                'n_start',
                'n_end',
                'in_sim_time',
                'capacity_factor_planned',
                'capacity_factor_used',
        """
        all_reactor_ops = {"total": defaultdict(float)}
        for agent_id in map(self.agent_id_or_name, agent_ids_or_names):
            reactor_ops = self.reactor_operations(agent_id)
            all_reactor_ops[agent_id] = reactor_ops
            for k in ("n_start", "n_end", "in_sim_time"):
                all_reactor_ops["total"][k] += reactor_ops[k]

        all_reactor_ops["total"]["capacity_factor_planned"] = (
            sum(
                v["in_sim_time"] * v["capacity_factor_planned"]
                for k, v in all_reactor_ops.items()
                if k != "total"
            )
            / all_reactor_ops["total"]["in_sim_time"]
        )
        all_reactor_ops["total"]["capacity_factor_used"] = sum(
            v["total_cf_time"] * v["capacity_factor_used"]
            for k, v in all_reactor_ops.items()
            if k != "total"
        ) / sum(v["total_cf_time"] for k, v in all_reactor_ops.items() if k != "total")

        return all_reactor_ops
