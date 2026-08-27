# Reproducing the Paper

## 0. What needs a simulator, and what does not

This is the first thing worth knowing. **The Pareto-front database is shipped with this
repository**, so a large part of the paper reproduces with nothing but Python.

| Paper result | Notebook | Needs Spectre + PDK? |
|---|---|---|
| Fig. 6 — depth-first search trajectories | `04_plot_pareto_fronts` | no (plots shipped data) |
| Fig. 7 — breadth-first Pareto expansion | `04_plot_pareto_fronts` | no |
| `result_all.csv` (634 Pareto samples) | `03_build_database` | no |
| **Table I — topology prediction** | `05_topology_prediction` | **no** |
| Table II — parameter tuning | `06_parameter_tuning` | **yes** |
| Building a database for a *new* topology | `01_dse_*`, `02_dse_*` | **yes** |

## 1. Setup

```bash
conda env create -f environment.yml     # or: pip install -r requirements.txt
conda activate paradigm
pip install -e .                        # makes `import paradigm` work anywhere
jupyter lab                             # notebooks/ are numbered in execution order
```

Every notebook opens with a bootstrap cell that `chdir`s to the repository root, so you can
launch Jupyter from either `notebooks/` or the repository root.

## 2. Table I — topology prediction

`notebooks/05_topology_prediction.ipynb`. Runs end-to-end on CPU in well under a minute.

Two details matter if you want to match the published numbers:

1. **`cv=5` is passed as an integer**, which makes scikit-learn use an *unshuffled*
   `StratifiedKFold`. The database rows are ordered by discovery time, so folds are not
   i.i.d. — that is exactly why the reported standard deviations are as large as they are.
   Passing `StratifiedKFold(shuffle=True)` instead collapses the std to ~0.015 and no longer
   matches the paper.
2. **`GBW` is converted to dB** (`20·log10`) before standardisation, for SVM / kNN / NN only.
   The tree-based models take the raw features.

Re-run on 2026-08-27 under Python 3.10.21 / scikit-learn 1.7.2 / xgboost 3.2.0:

| Model | Acc (paper) | Acc (re-run) | Δ | F1-macro (paper) | F1-macro (re-run) | Δ |
|---|---:|---:|---:|---:|---:|---:|
| CART | 0.9318 | 0.9319 | **+0.0001** | 0.9241 | 0.9263 | +0.0022 |
| Random Forest | 0.9493 | 0.9446 | −0.0047 | 0.9429 | 0.9376 | −0.0053 |
| XGBoost | 0.9414 | 0.9398 | −0.0016 | 0.9270 | 0.9252 | −0.0018 |
| SVM | 0.9209 | 0.9210 | **+0.0001** | 0.9105 | 0.9106 | **+0.0001** |
| kNN | 0.9477 | 0.9478 | **+0.0001** | 0.9376 | 0.9376 | **0.0000** |
| Neural net | 0.9052 | 0.9067 | +0.0015 | 0.8944 | 0.8849 | −0.0095 |

CART, SVM and kNN reproduce to within 1e-4. Random Forest and XGBoost land within 0.005 —
tie-breaking and histogram binning changed across library versions. The MLP is the loosest,
which is expected: its initialisation RNG and Adam implementation are version-sensitive.
Reported standard deviations reproduce to within 0.001 for every model except the MLP.

## 3. Fig. 6 / Fig. 7 — design-space exploration

`notebooks/04_plot_pareto_fronts.ipynb` plots the shipped CSVs directly. The "before → after"
pairs in the paper are two adjacent snapshots of the same cumulative database:

| Paper figure | Before | After |
|---|---|---|
| Fig. 7 (IAC) | `circuit_database/IAC/result_20250521-232905_allweights.csv` — 117 samples, 50 Pareto | `circuit_database/IAC/result_20250522-005729_allweights_nsga2.csv` — 204 samples, 99 Pareto |

The equivalent SMC progression (used in the source thesis) is
`result_20250521-132544_allweights.csv` (194 / 54) →
`result_20250521-235404_allweights_nsga2.csv` (286 / 105) →
`result.csv` (378 / 169).

## 4. Table II — parameter tuning *(simulator required)*

`notebooks/06_parameter_tuning.ipynb`, target `GBW = 10 MHz, Gain = 100 dB, Pdiss = 0.5 mW`
on SMC.

The L1-only training stage needs only PyTorch and reproduces the published loss curve; the
shipped checkpoint `circuit_database/SMC/P2C_model/P2C_Net_FD_SMC_20250522-161012.pt` is the
one behind the paper's `L1 = 0.0447`, so you can skip the 20 000-epoch run and load it directly.

The remaining columns need Spectre:

- the `L2` / `L3` loss terms estimate simulator gradients by finite differences —
  a batch of 10 samples with 11 parameters costs `10 × 11 × 2 = 220` simulations
- the TuRBO refinement calls the simulator once per candidate

Published run: 9 iterations / 91 simulations / 80 s warm-started, versus
100 iterations / 1088 simulations / 946 s from a cold start.

## 5. Building a database for a new topology *(simulator required)*

1. Export a netlist from Cadence Virtuoso into `circuits/<YOUR_CKT>/<YOUR_CKT>_da.scs`,
   and write the matching `<YOUR_CKT>_da.mdl` testbench (copy an existing pair as a template).
2. Point the `include` line at your PDK — see [`pdk_setup.md`](pdk_setup.md).
3. Set the device bounds in `circuits/design_space.json`.
4. Run `01_dse_depth_first_turbo` with the four weight vectors
   `[1,1,1]`, `[1,0,−1]`, `[0,−1,1]`, `[−1,1,0]`, then `02_dse_breadth_first_nsga2`.

Budget from the paper: ~4 000 simulations for depth-first plus ~1 000 for breadth-first per
topology, 40–80 minutes on an i7-12700 at roughly one second per simulation.
