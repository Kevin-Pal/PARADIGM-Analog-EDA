# PARADIGM

**Pareto-Optimized Analog Design via Intelligent Database-Guided Methodology**

Official implementation and reproducibility package for the forthcoming ISEDA 2026 paper.

PARADIGM turns analog circuit design into a database problem. It first spends compute *once*
per topology to map out that topology's Pareto front, then reuses the resulting database to
answer new design requests: pick the right topology, and warm-start the sizing so the
optimizer converges in tens of simulations instead of thousands.

---

## What is here

Seven operational-amplifier topologies, explored at a 180 nm node, distilled into a
**Pareto-front database of 1,818 simulated designs (634 of them Pareto-optimal)** — plus the
code that built it and the two models that consume it.

| Module | What it does | Paper |
|---|---|---|
| **DSE** — design-space exploration | Cascades TuRBO (depth-first, scalarized) into NSGA-II (breadth-first, Pareto-dominance) to map a topology's achievable performance envelope | §III-A |
| **TP** — topology prediction | Treats "which topology for these specs?" as multi-class classification over Pareto-optimal samples | §III-B |
| **PT** — parameter tuning | P2C Net (an MLP from performance metrics to device sizes) supplies a simulation-free initial point; TuRBO refines it | §III-C |

Headline results, all reproducible from this repository:

- Design-space exploration converges within **tens of minutes** per topology.
- Topology prediction reaches **94.9 % accuracy** (random forest, five-fold CV).
- Warm-started sizing hits the target in **9 iterations / 91 simulations / 80 s**, versus
  **100 / 1088 / 946 s** cold — roughly a **10×** reduction
  (reproduced with `scripts/run_sizing_warmstart.py` and `scripts/run_sizing.py`).

## Quickstart

```bash
git clone https://github.com/Kevin-Pal/PARADIGM-Analog-EDA.git
cd PARADIGM-Analog-EDA
conda env create -f environment.yml
conda activate paradigm
pip install -e .
jupyter lab notebooks/
```

**You do not need a simulator to get started.** The database ships with the repository, so
`05_topology_prediction.ipynb` (Table I) and `04_plot_pareto_fronts.ipynb` (Figs. 6–7) run
out of the box. Only building a database for a *new* topology, and the closed-loop parameter
tuning of Table II, call the simulator.

## Requirements

- **Python ≥ 3.10** and the packages in `requirements.txt` (developed on 3.10.13,
  re-verified on 3.10.21)
- **Cadence Spectre** — commercial simulator, bring your own license.
  Developed against 18.1.0.077
- **A 180 nm CMOS PDK** — this work used CSMC 0.18 µm, which is under NDA and is not
  redistributed here. The netlists reference it through a single `include` line;
  see [`docs/pdk_setup.md`](docs/pdk_setup.md) for the interface your PDK must satisfy
- A GPU is optional — P2C Net is small enough to train on CPU

## Repository layout

```text
paradigm/                  library code
├── netlist_utils.py         simulator interface, fitness functions, Pareto bookkeeping
└── turbo/                   TuRBO, extended with warm starts and stopping criteria
notebooks/                 the paper's experiments, in execution order
├── 01_dse_depth_first_turbo.ipynb     §III-A  depth-first search (TuRBO-5)
├── 02_dse_breadth_first_nsga2.ipynb   §III-A  breadth-first expansion (NSGA-II)
├── 03_build_database.ipynb            builds result_all.csv
├── 04_plot_pareto_fronts.ipynb        Fig. 6 / Fig. 7
├── 05_topology_prediction.ipynb       §III-B  Table I
└── 06_parameter_tuning.ipynb          §III-C  Table II
site/                      project page (GitHub Pages) with an interactive browser
                           over all 1,818 simulated designs
scripts/                   command-line drivers and utilities
├── run_sizing.py            TuRBO from a cold start
├── run_sizing_warmstart.py  TuRBO initialized from a P2C Net prediction
└── build_site_data.py       regenerates site/data/pareto.json from the database
circuits/                  netlists + MDL testbenches for the seven topologies
├── <CKT>/                   <CKT>_da.{scs,mdl}, <CKT>_tran.{scs,mdl}
├── SMC_{da,tran}.{scs,mdl}  top-level copies of the SMC testbenches
├── extra/                   six further topologies, not used in the paper
└── design_space.json        device-size and supply bounds
circuit_database/          ★ the Pareto-front database
├── result_all.csv           634 Pareto-optimal samples across all seven topologies
├── <CKT>/result.csv         per-topology database
└── SMC/P2C_model/           trained P2C Net checkpoints + loss histories
docs/
├── reproduce.md             how to re-derive each table and figure
├── data_format.md           CSV schema, units, and the STALE convention
├── pdk_setup.md             bringing your own PDK
├── environment.md           environment details
└── paper_to_code.md         every paper claim → the file that produces it
```

## The seven topologies

| | Topology | Reference |
|---|---|---|
| SMC | Single Miller Compensation | Allen & Holberg |
| NGCC | Nested G<sub>m</sub>-C Compensation | You et al., JSSC 1997 |
| DFCFC1 | Damping-Factor-Control Frequency Compensation | Leung et al., ISSCC 1999 |
| TCFC | Transconductance with Capacitor Feedback Compensation | Peng & Sansen, JSSC 2005 |
| IAC | Impedance Adapting Compensation | Peng et al., JSSC 2010 |
| NMCNR | Nested Miller Compensation with Nulling Resistor | Leung & Mok, TCAS-I 2001 |
| AZC | Active Zero Compensation | Yan et al., JSSC 2013 |

## Documentation

Start with [`docs/paper_to_code.md`](docs/paper_to_code.md) if you are reading this alongside
the paper — it maps every algorithm, table, and number to the file that produces it.
Read [`docs/data_format.md`](docs/data_format.md) before touching the CSVs; the
Pareto-staleness flag lives *inside* the ` solution path` column rather than in a column of
its own, which surprises everyone the first time.

## Citation

```bibtex
@inproceedings{peng2026paradigm,
  title     = {{PARADIGM}: Pareto-Optimized Analog Design via Intelligent
               Database-Guided Methodology},
  author    = {Peng, Anlan and Liu, Chengjie and Du, Yuan and Du, Li},
  booktitle = {2026 International Symposium of Electronics Design Automation (ISEDA)},
  year      = {2026},
  note      = {To appear}
}
```

The proceedings are not yet indexed on IEEE Xplore; the citation will be updated after the
official bibliographic record is available.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).

The TuRBO implementation under `paradigm/turbo/` derives from
[uber-research/TuRBO](https://github.com/uber-research/TuRBO); modifications for this work are
marked `*NEW FEATURE*` in the source.
