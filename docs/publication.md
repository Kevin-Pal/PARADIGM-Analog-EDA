# Published Paper

Anlan Peng, Chengjie Liu, Yuan Du, and Li Du, **“PARADIGM: Pareto-Optimized Analog Design
via Intelligent Database-Guided Methodology,”** in *2026 International Symposium of
Electronics Design Automation (ISEDA)*, IEEE, 2026, pp. 229–235.

- [IEEE Xplore record and paper access](https://ieeexplore.ieee.org/document/11751433)
- [DOI: 10.1109/ISEDA70083.2026.11751433](https://doi.org/10.1109/ISEDA70083.2026.11751433)
- Conference: May 8–10, 2026, Singapore, Singapore
- Added to IEEE Xplore: October 30, 2026
- Citation files: [`CITATION.bib`](../CITATION.bib) and [`CITATION.cff`](../CITATION.cff)

The bibliographic details were checked against the IEEE Xplore record and its BibTeX export
on November 2, 2026. The full published PDF and publisher figures are not redistributed here;
use IEEE Xplore for access. The code's Apache-2.0 license does not cover the published article.

## How the repository supports the paper

PARADIGM builds a reusable database with cascaded TuRBO and NSGA-II exploration, then uses
it for topology recommendation and P2C Net initialization followed by TuRBO refinement.
See the [paper-to-code map](paper_to_code.md) for the implementation and stored evidence,
and the [reproduction guide](reproduce.md) for execution instructions.

The evaluation covers seven operational-amplifier topologies at the CSMC 180-nm node.
The 1,818 retained designs include 634 samples non-dominated within their own topology;
they are not an exhaustive record of every simulator evaluation. The 94.93% random-forest
accuracy is five-fold cross-validation on those 634 topology-labelled samples. It measures
classification under that protocol; the suggested topology still needs sizing and simulation
for a new specification.

Table II is one SMC sizing example. Its warm start uses 91 simulations and 80 seconds,
compared with 1,088 and 946 seconds for the cold start, reaching the experiment's stopping
criterion. These ratios describe that comparison, rather than a speed guarantee for other
topologies, targets, simulators, or technology nodes.

Database analysis, plotting, and classifier reruns use the shipped data. New exploration and
closed-loop sizing require a licensed simulator and compatible PDK. The model files and
historical outputs are provided, while the PDK and raw waveform dumps are excluded.
