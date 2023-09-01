# Bicyclus: A Statistical Fuel Cycle Simulation Framework for Nuclear Verification
This repository contains the code used during the case study from _Bicyclus: A
Statistical Fuel Cycle Simulation Framework for Nuclear Verification_ (Max
Schalz, Lewin Bormann, Malte Göttsche, under submission in Annals of Nuclear
Energy).

## Structure
- `simulations/` contains the driver files used in the forward and inference
  runs (`forward_simulations.py` and `reconstruction_run.py`) as well as
  functions used to generate the Cyclus input files (`cyclus_input.py` and
  others).
- `analysis/` contains the scripts used to read out data and generate the
  figures.
  `analysis/imgs/` contains data from the different runs (as `.cdf` or `.h5`
  files) and will also contain the figures after running the scripts.

## Requirements
To run the simulations, you need to have
[Bicyclus](https://github.com/Nuclear-Verification-and-Disarmament/bicyclus)
installed.

The plotting scripts use standard scientific Python packages, including
[Pandas](https://pandas.pydata.org/), [matplotlib](https://matplotlib.org/) and
[seaborn](https://seaborn.pydata.org/).
