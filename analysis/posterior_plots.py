#!/usr/bin/env python3

"""Script only used to plot results from the inference run."""

import json
from pathlib import Path

import arviz as az
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="darkgrid", context="paper", font="serif", font_scale=1)


def main():
    """Main entry point."""
    get_posterior()


def get_posterior():
    """Get the merged traces and plot the posterior densities."""
    job_ids = (34397257,)  # Job ID(s) of the inference run(s)
    with open(
        Path("../simulations/parameters/reconstruction/swu_cap_factor_true.json"), "r"
    ) as f:
        groundtruth = json.load(f)

    for job_id in job_ids:
        path = Path(f"imgs/{job_id}/{job_id}_{job_id}.cdf")
        data = az.from_netcdf(path)

        _, ax = plt.subplots(ncols=2, constrained_layout=True, figsize=(4.5, 2))
        for axis, xlabel in zip(ax, ("capacity factor", "separative power [kgSWU/yr]")):
            axis.set_title("")
            axis.set_xlabel(xlabel)
        for axis, xlabel in zip(ax, ("global_capacity_factor", "swu_increase2")):
            sns.histplot(
                data=data["posterior"][xlabel].values.flatten(),
                ax=axis,
                bins=9,
                stat="density",
                kde=False,
                alpha=0.5,
            )
            axis.set_ylabel("")
            axis.set_yticks([])
            axis.axvline(groundtruth[xlabel], linestyle="dashed", color="C3")

        ax[0].set_ylabel("density")
        fname = path.parent / f"posterior_{job_id}.eps"
        print(f"Saving plot under {fname}")
        plt.savefig(fname, format="eps")
        plt.close()


if __name__ == "__main__":
    main()
