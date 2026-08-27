# Bringing Your Own PDK

PARADIGM was developed against **CSMC 0.18 µm** with **Cadence Spectre 18.1.0.077**.
Neither the process design kit nor the simulator can be redistributed, so every netlist in
this repository ships with a placeholder `include` line that you must point at your own PDK.

## 1. What to change

Every `.scs` netlist under `circuits/` and `circuit_database/` contains:

```spectre
; NOTE: replace with your own PDK model file. Original: CSMC 0.18um, sm1816m50v13_usage.scs, section=tt_lib
include "/path/to/your/pdk/model.scs" section=tt_lib
```

Replace the path with your own model file. To rewrite them all at once:

```bash
grep -rl '/path/to/your/pdk/model.scs' circuits circuit_database \
  | xargs sed -i 's|/path/to/your/pdk/model.scs|/opt/pdk/your_process/models.scs|g'
```

Only the netlists under `circuits/` are used when you run anything; the ones under
`circuit_database/` are historical per-sample records kept for provenance.

## 2. What the netlists expect from your PDK

The netlists are written against a small, explicit interface. Your PDK must provide:

| Requirement | Value used in the paper | What to do if yours differs |
|---|---|---|
| NMOS model name | `mn18` | Either alias it in your models file, or `sed` the netlists |
| PMOS model name | `mp18` | Same |
| Typical-corner section | `tt_lib` | Change `section=` on the `include` line |
| Supply voltage | 1.8 V | Edit `VDD` in `circuits/design_space.json` and the `vsource dc=` lines |
| Minimum channel length | 500 nm (`lmin`) | Edit `circuits/design_space.json` |

A device instance looks like this — plain SPICE, nothing vendor-specific beyond the model name:

```spectre
NM0 (net27 VINN net26 VSS) mn18 w=2e-07 l=5e-07   //// Input transistor, 1st stage
PM0 (net28 net27 VDD VDD) mp18 w=2e-07 l=5e-07    //// Load transistor, 1st stage
```

## 3. Design-space bounds

`circuits/design_space.json` defines the search space the optimiser is allowed to explore:

```json
{
  "lmin": 500e-9,   "lmax": 2e-6,     // channel length bounds
  "wmin": 200e-9,   "wmax": 1000e-6,  // total channel width bounds
  "VDD": 1.8,
  "step_sub": 1e-9, // W/L quantisation step
  "wsub": 2e-5,     // max width per finger; wider devices are split into fingers
  "avoid": {}       // sizes some PDKs choke on; empty for the 180 nm node used here
}
```

Retune `lmin` / `lmax` / `wmin` / `wmax` / `VDD` for your node before running anything —
the bounds are what the TuRBO trust regions are normalised against.

## 4. Simulator invocation

Performance is measured through MDL testbenches, one `.mdl` per analysis:

```bash
cd <run_path> && spectremdl -batch <name>.mdl -design <name>.scs +mt=3
```

Results are read back from the generated `<name>.measure`. Two testbenches per circuit:

- `<CKT>_da.{scs,mdl}` — DC + AC/stability: `DC_gain`, `GBW_VOUT`, `PM_VOUT`, `GM_VOUT`, `UGB`, `Pdiss`
- `<CKT>_tran.{scs,mdl}` — transient: `SR_N`, `SR_P`

If you use a different simulator, the only thing you need to reproduce is that contract:
**take a netlist plus a testbench, return those named scalars.** Swap the body of
`read_performance` / `read_multiple_performances` in `paradigm/netlist_utils.py` and the
rest of the framework is unchanged.

## 5. What you can run without any of this

The Pareto-front database is shipped with the repository, so the topology-prediction results
(Table I) and every data figure reproduce with **no simulator and no PDK at all**.
See [`reproduce.md`](reproduce.md).
