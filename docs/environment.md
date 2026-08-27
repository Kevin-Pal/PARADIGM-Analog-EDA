# Environment

## Original environment (as used for the paper)

| | |
|---|---|
| OS | Linux |
| CPU | Intel® Core™ i7-12700 |
| Memory | 64 GB |
| GPU | NVIDIA® P104-100, CUDA 11.4 — used only for P2C Net |
| Python | 3.10.13 |
| Simulator | **Cadence Spectre® 18.1.0.077** |
| Process | **CSMC 0.18 µm** (`sm1816m50v13_usage.scs`, section `tt_lib`) |

## Verified environment (rebuilt 2026-08-27)

```bash
conda env create -f environment.yml     # or: pip install -r requirements.txt
conda activate paradigm
pip install -e .
```

| Package | Version |
|---|---|
| Python | 3.10.21 |
| numpy | 2.2.6 |
| pandas | 2.3.3 |
| scikit-learn | 1.7.2 |
| xgboost | 3.2.0 |
| matplotlib | 3.10.9 |
| seaborn | 0.13.2 |
| torch | 2.13.0+cpu |
| gpytorch | 1.15.2 |
| pymoo | 0.6.2 |

A GPU is optional. P2C Net has roughly 0.27 M parameters; 20 000 epochs finish in minutes on CPU.

## What needs the simulator

| Stage | Depends on | Runs without Spectre? |
|---|---|---|
| Design-space exploration, depth-first (TuRBO) | Spectre + PDK | no |
| Design-space exploration, breadth-first (NSGA-II) | Spectre + PDK | no |
| Aggregating `result_all.csv` | pandas | **yes** |
| Pareto-front figures (Figs. 6–7) | pandas, matplotlib | **yes** |
| **Topology prediction (Table I)** | scikit-learn, xgboost | **yes** |
| P2C Net, L1-only training | torch | **yes** |
| P2C Net L2/L3 losses and TuRBO refinement (Table II) | Spectre + PDK | no |

The Pareto-front database ships with this repository, so Table I and every data figure
reproduce with no simulator license at all.

## How the simulator is called

```bash
cd <run_path> && spectremdl -batch <name>.mdl -design <name>.scs +mt=3
```

Scalar results are read back from the generated `<name>.measure`. `run_path` defaults to
`./runs` and is created automatically (`os.makedirs` guarded by `try/except FileExistsError`),
so nothing needs to exist beforehand.

Batches are dispatched in parallel via `subprocess`; see `paradigm/netlist_utils.py`
(`read_multiple_performances`, `C2P_Simulator`).

PDK wiring and how to substitute your own is covered in [`pdk_setup.md`](pdk_setup.md).
