#!/usr/bin/env python3
"""Regenerate site/data/pareto.json from the shipped Pareto-front database.

The project page plots every simulated design straight from circuit_database/,
so the JSON it loads is derived, never hand-maintained. Run from the repo root:

    python scripts/build_site_data.py
"""
from __future__ import annotations

import json
import os
from glob import glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "site", "data", "pareto.json")
STALE_COLUMN = " solution path"


def main() -> None:
    import pandas as pd

    points = []
    for directory in sorted(glob(os.path.join(REPO_ROOT, "circuit_database", "*", ""))):
        topology = os.path.basename(directory.rstrip(os.sep))
        csv_path = os.path.join(directory, "result.csv")
        if not os.path.exists(csv_path):
            continue
        frame = pd.read_csv(csv_path)
        on_front = ~frame[STALE_COLUMN].astype(str).str.contains("STALE")
        for (_, row), pareto in zip(frame.iterrows(), on_front):
            points.append(
                {
                    "c": topology,
                    "g": round(float(row[" Gain"]), 3),          # DC gain, dB
                    "b": round(float(row["GBW"]) / 1e6, 5),      # gain-bandwidth product, MHz
                    "p": round(float(row[" Pdiss"]) * 1e3, 6),   # static power, mW
                    "o": int(pareto),                            # 1 if Pareto-optimal
                }
            )

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "note": "PARADIGM Pareto-front database. "
                        "g=DC gain (dB), b=GBW (MHz), p=Pdiss (mW), o=1 if Pareto-optimal",
                "points": points,
            },
            handle,
            separators=(",", ":"),
        )

    pareto = sum(point["o"] for point in points)
    print(f"{len(points)} designs ({pareto} Pareto-optimal) -> {os.path.relpath(OUT, REPO_ROOT)}")


if __name__ == "__main__":
    main()
