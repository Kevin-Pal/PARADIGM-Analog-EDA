# Paper → Code Map

Every claim, algorithm, and number in the paper, mapped to the file that produces it.

> **Paper.** A. Peng, C. Liu, Y. Du, L. Du, *"PARADIGM: Pareto-Optimized Analog Design via
> Intelligent Database-Guided Methodology,"* ISEDA 2026 (to appear).

## 1. Methodology (Paper §III)

| Paper item | Where it lives |
|---|---|
| **Algorithm 1** — simulator interface: `(batch, dim_param) → (batch, dim_perf)`, parallel via `subprocess` | `paradigm/netlist_utils.py`: `C2P_Simulator`, `FitnessFunction_Prallel`, `FitnessFunction_Prallel_Tailor`, `FitnessFunction_Prallel_Multiobj`, `write_vector2netlist`, `read_multiple_performances`, `find_matching_scs_mdl` |
| **Algorithm 2** — TuRBO-M, modified for this work (`x_init` / `fx_init` / `max_iters` / `f_threshold`, matrix-valued objective) | `paradigm/turbo/turbo_m_plus.py`, `turbo_1_plus.py` (each carries `*NEW FEATURE*` markers on the four additions). Upstream originals kept as `turbo_1.py` / `turbo_m.py` |
| **Algorithm 3** — NSGA-II with a user-supplied initial population | `notebooks/02_dse_breadth_first_nsga2.ipynb` (via `pymoo`) |
| **Eq. (3)** — `Fitness = lg(A × B × C)`, weights `1 / 0 / −1` ↦ identity / sqrt / log | `paradigm/netlist_utils.py`: `fitness_function_ABC`, `make_fitness_function`, `fitness_function_essay` |
| Pareto-dominance admission rule + `STALE` marking + validity screen (PM / GM / SR) | `paradigm/netlist_utils.py`: `is_a_valuable_solution`, `fitness_function_multiobj`, `add_datapoint2database`, `collect_dominated_points_from_database` |
| **§III-A** DSE, depth-first (TuRBO-5, batch 10, four weight vectors) | `notebooks/01_dse_depth_first_turbo.ipynb` |
| **§III-A** DSE, breadth-first (NSGA-II, population 50, seed 1) | `notebooks/02_dse_breadth_first_nsga2.ipynb` |
| **§III-B** Topology prediction — six classifiers, grid search, 5-fold CV | `notebooks/05_topology_prediction.ipynb` |
| CART decision-tree visualization (first three levels) | `notebooks/05_topology_prediction.ipynb` (`plot_tree`) |
| **§III-C** P2C Net — MLP 256/512/256, ReLU, dropout 0.2, `InputScaler` in, Sigmoid + `FromUnicube` out | `notebooks/06_parameter_tuning.ipynb` |
| **Eq. (4)** — `L_total = L1 + λ1·L2 + λ2·L3`, all MRSE; FDM gradients for the simulator | `notebooks/06_parameter_tuning.ipynb`; simulator-side gradient path in `paradigm/netlist_utils.py::C2P_Simulator` |
| **§III-C** warm-started TuRBO-1 (init from P2C Net, ≤100 iterations, early stop) | `notebooks/06_parameter_tuning.ipynb` + `paradigm/turbo/turbo_1_plus.py` |
| Database aggregation (drop `STALE`, merge circuits) | `notebooks/03_build_database.ipynb` → `circuit_database/result_all.csv` |
| Figures 6 / 7 (3-D Pareto scatter, search trajectories) | `notebooks/04_plot_pareto_fronts.ipynb` |
| Seven amplifier topologies, netlist + MDL testbench | `circuits/{SMC,NGCC,DFCFC1,TCFC,IAC,NMCNR,AZC}/` |
| Device-size and supply constraints | `circuits/design_space.json` |
| CSMC 0.18 µm PDK | **Not distributed** (NDA). See [`pdk_setup.md`](pdk_setup.md) |

## 2. Experimental numbers

Every figure below was checked against the shipped data files.

| Paper claim | Source in this repo | Status |
|---|---|---|
| Pareto samples per topology: AZC 87 · DFCFC1 17 · IAC 99 · NGCC 104 · NMCNR 61 · SMC 169 · TCFC 97 (§IV-C) | `circuit_database/<CKT>/result.csv`, rows whose ` solution path` ≠ `STALE` | ✅ all seven match exactly |
| Topology-prediction training set = 634 samples | `circuit_database/result_all.csv` — 634 rows | ✅ |
| P2C Net training set = 378 SMC samples (§IV-D) | `circuit_database/SMC/result.csv` — 378 rows | ✅ |
| **Fig. 7**: 117 samples (50 Pareto) → 204 (99) after 20 BFS rounds | **IAC**: `result_20250521-232905_allweights.csv` (117/50) → `result_20250522-005729_allweights_nsga2.csv` (204/99) | ✅ *(note: these are IAC, not SMC)* |
| **Table I**: six classifiers, Acc / Acc Std / F1-macro / fit & score time | `notebooks/05_topology_prediction.ipynb` | ✅ rerun 2026-08 — see [`reproduce.md`](reproduce.md) |
| **Table II**: P2C Net / TuRBO / P2C Net + TuRBO, 12 values | `notebooks/06_parameter_tuning.ipynb`; measured values traceable to the simulator logs of that run | ✅ all 12 match |
| P2C Net final `L1 = 0.0447` after 20 000 epochs | `circuit_database/SMC/P2C_model/P2C_Net_FD_SMC_20250522-161012_history.csv`, last row `l1_param = 0.0446971`; weights in the matching `.pt` | ✅ |
| Database coverage: gain 50–160 dB, power 3 µW – 40 mW (thesis §4.3.1) | measured across `circuit_database/*/result.csv`: **51.9–164.3 dB**, **0.003–40.05 mW** | ✅ |
| P2C Net architecture 256/512/256 (§III-C) | `state_dict` of the shipped checkpoint: `3→256`, `256→512`, `512→256`, `256→11`, plus `input_scaler` and `FromUnicube` bounds | ✅ verified by loading the weights |

> **Naming note.** The notebook labels the CART classifier `CRT Tree` (a typo carried over from the
> original experiments). It is the same `DecisionTreeClassifier` reported as *CART* in Table I; the
> label remains untouched so that the stored notebook outputs preserve the original run's evidence.

## 3. Things the paper mentions that are *not* in this repo

| Item | Why |
|---|---|
| Figures 1–5 (system / module block diagrams, P2C Net schematic) | Drawn in external tooling; the typeset paper is under IEEE copyright and is not redistributed here |
| Raw Spectre waveform dumps (`*.raw/`) | ~1.5 GB of binary transient/AC data. The scalar measurements they encode are already extracted into `circuit_database/**/*.csv` |
| CSMC 0.18 µm process models | Foundry NDA. The netlists reference them by `include`; see [`pdk_setup.md`](pdk_setup.md) |
