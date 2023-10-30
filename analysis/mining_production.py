#!/usr/bin/env python3

"""Scripts to read out results from Cyclus forward simulations."""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib import rc

sns.set_theme(style="darkgrid", context="paper", font="serif", font_scale=1)
rc("axes.formatter", use_mathtext=True)
sys.path.append("../simulations")

# Disable pylint's wrong-import-position in the following lines
from global_parameters import PARAMS  # pylint: disable=C0413,E0401
from pakistan_data import natural_u_production_df  # pylint: disable=C0413,E0401


def main():
    """Main entry point of the script."""
    plot_mining_production()


def plot_mining_production():
    """Plot the yearly production of natural uranium."""
    mining_df = natural_u_production_df(PARAMS["current_mining_production"])

    add_last_year = pd.DataFrame(
        {"year": [PARAMS["endyear"]], "mass": [mining_df["mass"].iloc[-1]]}
    )
    mining_df = pd.concat((mining_df, add_last_year))

    _, ax = plt.subplots(figsize=(4, 2), constrained_layout=True)
    ax.step(mining_df.year - mining_df.year.iloc[0], mining_df.mass / 1e3, where="post")
    ax.set_xlabel("in-simulation year")
    ax.set_ylabel("NU mining [t / year]")
    plt.savefig(Path("imgs/mining_production.eps"), format="eps")
    plt.close()


if __name__ == "__main__":
    main()
