# Data Format

`circuit_database/` is the core artifact of this work: a Pareto-front database for seven
operational-amplifier topologies at a 180 nm node.

## Layout

```text
circuit_database/
├── result_all.csv                    all seven topologies, STALE rows dropped (634 rows)
├── result_all_20250522-085704.csv    the same file, timestamped (byte-identical)
└── <CKT>/                            CKT ∈ {SMC, NGCC, DFCFC1, TCFC, IAC, NMCNR, AZC}
    ├── result.csv                    final database for this topology
    ├── result_1_1_1_<ts>.csv         cumulative state after depth-first search, weights [1,1,1]
    ├── result_1_0_-1_<ts>.csv        … weights [1,0,-1]
    ├── result_0_-1_1_<ts>.csv        … weights [0,-1,1]
    ├── result_-1_1_0_<ts>.csv        … weights [-1,1,0]
    ├── result_<ts>_allweights.csv    after all four depth-first passes
    ├── result_<ts>_allweights_nsga2.csv   after breadth-first expansion
    ├── raw/                          netlist + MDL snapshot for this topology
    └── result_folder/<ts>/           per-sample evidence: result, TurBO_da.scs, TurBO_tran.scs
```

**These snapshots are cumulative**, so the paper's "before → after" figures are simply two
adjacent files from this chain.

## Columns

Header (note the **leading space on every column name except the first**):

```
GBW, Gain, Pdiss, Fitness, time, performance weight, solution vector, solution path
```

`result_all.csv` prepends one more column, `circuit name` — the topology label, i.e. the
target variable for topology prediction.

| Column | Unit | Meaning |
|---|---|---|
| `GBW` | **Hz** | Gain–bandwidth product, e.g. `29067700.0` = 29.07 MHz |
| ` Gain` | **dB** | DC open-loop gain |
| ` Pdiss` | **W** | Static power, e.g. `0.00139515` = 1.395 mW |
| ` Fitness` | — | Value of the scalarized objective (paper Eq. 3) at admission time. Comparable only *within* one weight vector |
| ` time` | — | Timestamp such as `2025-0521-122240`; also the sub-directory name under `result_folder/` |
| ` performance weight` | — | Depth-first weight vector, e.g. `[1, 1, 1]`. `1` → identity, `0` → square root, `-1` → log10 |
| ` solution vector` | SI | All device parameters for this design (W/L, capacitors, resistors, bias current), serialised as a NumPy array — **may span several physical lines**, so parse with a real CSV reader |
| ` solution path` | — | Relative path to the evidence directory, **or the literal string `STALE`** |

### The `STALE` convention

**`STALE` is not a column — it is written *into* the ` solution path` column.**

The database only admits Pareto-optimal samples. When a new sample strictly dominates an
existing record, the old record is *not* deleted: its ` solution path` is overwritten with
`STALE` and its evidence directory is removed from disk
(see `add_datapoint2database` in `paradigm/netlist_utils.py`).

```python
import pandas as pd
df = pd.read_csv("circuit_database/SMC/result.csv")
pareto = df[~df[" solution path"].astype(str).str.contains("STALE")]
# len(df)     == 378   all samples          -> P2C Net training set
# len(pareto) == 169   Pareto-optimal only  -> topology-prediction training set
```

Keeping stale rows is deliberate: they are still *valid* designs (they passed the phase- and
gain-margin screen), so they enrich the P2C Net training distribution even though they no
longer sit on the front. The paper trains P2C Net on all 378 SMC samples, not just the 169.

## Size and coverage

| Topology | Samples | Pareto-optimal | Params | Gain (dB) | GBW (MHz) | Pdiss (mW) |
|---|---:|---:|---:|---|---|---|
| SMC | 378 | **169** | 11 | 51.9 – 100.7 | 1.31 – 172.30 | 0.068 – 6.82 |
| NGCC | 434 | **104** | 30 | 137.0 – 146.9 | 7.27 – 60.59 | 0.743 – 10.29 |
| IAC | 204 | **99** | 24 | 130.6 – 159.8 | 0.50 – 30.28 | 0.015 – 7.91 |
| TCFC | 206 | **97** | 26 | 124.1 – 164.3 | 0.24 – 47.75 | 0.011 – 15.56 |
| AZC | 274 | **87** | 30 | 60.9 – 117.7 | 0.0018 – 2.15 | 0.265 – 18.02 |
| NMCNR | 267 | **61** | 27 | 67.2 – 144.9 | 0.06 – 66.42 | 0.003 – 40.05 |
| DFCFC1 | 55 | **17** | 24 | 109.6 – 141.9 | 3.07 – 2174.26 | 0.676 – 10.15 |
| **Total** | **1818** | **634** | | **51.9 – 164.3** | | **0.003 – 40.05** |

Per-topology Pareto counts match the paper (§IV-C) exactly; the total of 634 is the row count
of `result_all.csv`.

## Trained P2C Net weights

`circuit_database/SMC/P2C_model/` holds 15 checkpoints (`*.pt`) with matching per-epoch loss
histories (`*_history.csv`). The one used in the paper is
**`P2C_Net_FD_SMC_20250522-161012`** — 20 000 epochs, final `l1_param = 0.0446971`, reported
as `L1 = 0.0447`.

Its `state_dict` maps one-to-one onto the architecture in §III-C:

```
input_scaler.p_mean / p_scale   (3,)      per-metric mean and std
core_network.0     3   → 256              hidden layer 1
core_network.3     256 → 512              hidden layer 2
core_network.6     512 → 256              hidden layer 3
core_network.9     256 → 11               output: SMC's 11 device parameters
core_network.11    lb / ub  (11,)         FromUnicube: maps sigmoid output back to SI units
```

The stride of 3 between layer indices is `Linear → ReLU → Dropout(0.2)`.
