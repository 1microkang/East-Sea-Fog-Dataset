#!/usr/bin/env python3
"""Calculate ACC, PRE, REC and CSI from frozen confusion-matrix counts."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        raise ZeroDivisionError("Metric denominator is zero")
    return 100.0 * numerator / denominator


def calculate(row: dict[str, str]) -> dict[str, str]:
    h, m, f, c = (int(row[key]) for key in ("H", "M", "F", "C"))
    n = h + m + f + c

    declared_n = int(row.get("n", n))
    if declared_n != n:
        raise ValueError(
            f"{row.get('source', 'unknown source')}: declared n={declared_n}, "
            f"but H+M+F+C={n}"
        )

    return {
        "source": row["source"],
        "H": str(h),
        "M": str(m),
        "F": str(f),
        "C": str(c),
        "n": str(n),
        "accuracy_percent": f"{percentage(h + c, n):.2f}",
        "precision_percent": f"{percentage(h, h + f):.2f}",
        "recall_percent": f"{percentage(h, h + m):.2f}",
        "csi_percent": f"{percentage(h, h + m + f):.2f}",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        input_rows = list(csv.DictReader(handle))

    output_rows = [calculate(row) for row in input_rows]
    fieldnames = [
        "source",
        "H",
        "M",
        "F",
        "C",
        "n",
        "accuracy_percent",
        "precision_percent",
        "recall_percent",
        "csi_percent",
    ]

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)

    for row in output_rows:
        print(
            f"{row['source']}: ACC={row['accuracy_percent']}%, "
            f"PRE={row['precision_percent']}%, "
            f"REC={row['recall_percent']}%, CSI={row['csi_percent']}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

