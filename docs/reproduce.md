# Reproducing the Paper

[Published paper and evaluation scope](publication.md) ·
[IEEE Xplore](https://ieeexplore.ieee.org/document/11751433)

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
2. **`GBW` is converted to dB** (`20·log10`) before standardization, for SVM / kNN / NN only.
   The tree-based models take the raw features.

Re-run of this notebook on 2026-08-27 (Python 3.10.21, scikit-learn 1.7.2, xgboost 3.2.0),
executed twice so that library drift can be told apart from run-to-run variance:

| Model | Paper | Run 1 | Run 2 | Stable across runs? |
|---|---:|---:|---:|---|
| Random Forest | 0.9493 | 0.9493 | 0.9493 | yes — reproduces exactly |
| kNN | 0.9477 | 0.9478 | 0.9478 | yes |
| SVM | 0.9209 | 0.9210 | 0.9210 | yes |
| XGBoost | 0.9414 | 0.9366 | 0.9366 | yes, but ~0.005 below the paper |
| CART | 0.9318 | 0.9303 | 0.9319 | **no** |
| Neural network | 0.9052 | 0.9194 | 0.8878 | **no** |

Random forest matches the published accuracy at the shown precision; kNN and SVM are
within 0.0001 of the displayed paper values. XGBoost is stable but about 0.005 lower in these
reruns. Library-version differences may contribute; these reruns do not isolate the cause.

**CART and the MLP are not seeded, so expect them to move between runs.** The notebook builds
its final estimator as `Model(**grid_search.best_params_)`, and `best_params_` does not carry
the `random_state` that was set on the search estimator — so split tie-breaking (CART) and
weight initialisation (MLP) are left to chance. Across runs CART stays within roughly ±0.002
of the published value and the MLP within roughly ±0.02. Pass `random_state=42` when
constructing those two final models if you want bit-identical reruns.

## 3. Fig. 6 / Fig. 7 — design-space exploration

`notebooks/04_plot_pareto_fronts.ipynb` plots the shipped CSVs directly. The "before → after"
pair in Fig. 7 uses two adjacent snapshots of the same cumulative database:

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

The L1-only training stage needs only PyTorch and reproduces the reported loss curve; the
shipped checkpoint `circuit_database/SMC/P2C_model/P2C_Net_FD_SMC_20250522-161012.pt` is the
one behind the paper's `L1 = 0.0447`, so you can skip the 20 000-epoch run and load it directly.

The remaining columns need Spectre:

- the `L2` / `L3` loss terms estimate simulator gradients by finite differences —
  a batch of 10 samples with 11 parameters costs `10 × 11 × 2 = 220` simulations
- the TuRBO refinement calls the simulator once per candidate

Table II reports 9 iterations / 91 simulations / 80 s warm-started, versus
100 iterations / 1,088 simulations / 946 s from a cold start. The warm start reaches the
experiment's stopping criterion; its 99.60 dB gain is close to the 100 dB target. These are
historical measurements for that SMC experiment, with approximately 12× reductions in both
simulation count and runtime. A new run is stochastic and depends on the simulator, PDK,
hardware, target, and stopping settings.

The command-line drivers are `scripts/run_sizing_warmstart.py` and `scripts/run_sizing.py`;
configure the simulator and PDK first as described in [pdk_setup.md](pdk_setup.md).

## 5. Building a database for a new topology *(simulator required)*

1. Export a netlist from Cadence Virtuoso into `circuits/<YOUR_CKT>/<YOUR_CKT>_da.scs`,
   and write the matching `<YOUR_CKT>_da.mdl` testbench (copy an existing pair as a template).
2. Point the `include` line at your PDK — see [`pdk_setup.md`](pdk_setup.md).
3. Set the device bounds in `circuits/design_space.json`.
4. Run `01_dse_depth_first_turbo` with the four weight vectors
   `[1,1,1]`, `[1,0,−1]`, `[0,−1,1]`, `[−1,1,0]`, then `02_dse_breadth_first_nsga2`.

For the representative runs in §IV-B, four TuRBO passes × 50 iterations × batch 10 give
approximately 2,000 simulations, followed by NSGA-II with population 50 for 10 generations
(approximately 500 simulations). The paper also describes the Fig. 7 transition as “20
initial rounds”; that wording differs from the stated 10-iteration setup. The supplied CSV
snapshots establish the reported 117/50 → 204/99 sample counts independently of that wording.

The saved notebook defaults differ from the illustrated paper setup: the standalone
TuRBO cell uses 100 iterations, while the multi-topology loop uses 50; the NSGA-II cells
use 100 and 50 generations respectively, with population 50. See
[data_format.md](data_format.md#what-it-cost-to-build-this-database) before launching a run.
The notebooks update the database in place, so use a separate clone for new exploration
if you want to preserve the shipped CSVs for comparison.
