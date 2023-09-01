#!/usr/bin/env python3

"""Scripts to read out results from Cyclus forward simulations."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib import rc

from sqlite_analyser import AnalyseAllFiles

sns.set_theme(style="darkgrid", context="paper", font="serif", font_scale=1)
rc("axes.formatter", use_mathtext=True)


def main():
    """Main entry point of the script."""
    args = argparser()
    analyser = AnalyseAllFiles(
        data_path=args.data_path,
        imgs_path=args.imgs_path,
        job_id=args.job_id,
        max_files=args.max_files,
    )
    analyser.get_data(force_update=args.force_update)

    final_plots(
        analyser,
        groundtruth_path=args.groundtruth_path,
        groundtruth_jobid=args.groundtruth_jobid,
    )


def final_plots(analyser, groundtruth_path=None, groundtruth_jobid=None):
    """Plots used in the paper."""
    _, ax = plt.subplots(constrained_layout=True, figsize=(4.5, 4))
    sns.histplot(
        data=analyser.data,
        x="total_heu",
        y="total_pu",
        bins=10,
        stat="count",
        cbar=True,
        ax=ax,
    )
    ax.set_xlabel("total HEU production [kg]")
    ax.set_ylabel("total Pu production [kg]")
    plt.savefig(analyser.imgs_path / f"total_pu_total_heu_{analyser.job_id}.pdf")
    plt.close()

    if groundtruth_path:
        print(
            f"Using groundtruth options with groundtruth_path {groundtruth_path}, "
            f"groundtruth_jobid {groundtruth_jobid}"
        )
        gt_analyser = AnalyseAllFiles(
            data_path=groundtruth_path,
            imgs_path=Path("imgs", groundtruth_jobid),
            job_id=groundtruth_jobid,
            max_files=10,
        )
        gt_analyser.get_data(force_update=False)

    _, ax = plt.subplots(ncols=2, constrained_layout=True, figsize=(4.5, 2))
    for i, (x, xlabel) in enumerate(
        zip(("total_pu", "total_heu"), ("total Pu [kg]", "total HEU [kg]"))
    ):
        sns.histplot(
            data=analyser.data,
            x=x,
            ax=ax[i],
            kde=False,
            alpha=0.5,
            stat="density",
            bins=6,
        )
        if groundtruth_path:
            ax[i].axvline(
                gt_analyser.data[x][0],
                linestyle="dashed",
                color="C3",
                label="groundtruth",
            )
        ax[i].set_ylabel("")
        ax[i].set_yticks([])
        ax[i].set_xlabel(xlabel)
    ax[0].set_ylabel("density")
    plt.savefig(analyser.imgs_path / f"fissile_material_{analyser.job_id}.pdf")
    plt.close()

    data = analyser.data
    x = "capacity_factor_planned"
    y = "swu_sampled"
    hue = "enrichment_feed_SeparatedU"
    data[y] = data[y] / 1000
    data[hue] = data[hue] / 1000
    norm = plt.Normalize(data[hue].min(), data[hue].max())
    cmap = sns.cubehelix_palette(as_cmap=True)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)  # bit hacky to add a colorbar
    sm.set_array([])
    _, ax = plt.subplots(ncols=2, constrained_layout=True, figsize=(5.35, 2.1))
    sns.histplot(
        data=data, x=hue, ax=ax[0], kde=False, alpha=0.5, stat="density", bins=7
    )
    ax[0].set_xlabel("RU enrichment feed [t]")
    ax[0].set_ylabel("density")
    ax[0].set_yticks([])
    ax[0].set_xlim(left=0)
    # Colored scatterplot
    sns.scatterplot(data=data, x=x, y=y, hue=hue, ax=ax[1], palette=cmap)
    ax[1].set_xlabel("capacity factor")
    ax[1].set_ylabel("sep. power [tSWU/year]")
    ax[1].get_legend().remove()
    cbar = plt.colorbar(sm, ax=ax[1], pad=0.0)
    cbar.ax.set_ylabel("RU enrichment feed [t]")
    plt.savefig(analyser.imgs_path / "2dhistogram_params_RU_enrichment_feed.pdf")
    plt.close()


def argparser():
    """A simple argparser for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Analyse Cyclus .sqlite output files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-path",
        default=".",
        help="Path to output files. The program recursively "
        "walks through all subdirectories.",
    )
    parser.add_argument(
        "--imgs-path", default="imgs/", help="Directory where plots are stored."
    )
    parser.add_argument(
        "--max-files",
        default=None,
        type=int,
        help="If set, do not exceed this amount of files "
        "considered in the analysis.",
    )
    parser.add_argument(
        "--job-id",
        default="",
        type=str,
        help="If set, only consider files with `job-id` in their filename.",
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help=(
            "If set, always extract data from sqlite files. If not set, only "
            "do so in case no presaved data file (data.h5) is available."
        ),
    )
    parser.add_argument("--groundtruth-path", default=None)
    parser.add_argument("--groundtruth-jobid", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
