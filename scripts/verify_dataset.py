#!/usr/bin/env python3
"""Verify metadata consistency and optionally inspect extracted dataset files.

The script checks the frozen 681-row manifest, annual pair counts, unique scene
identifiers, deterministic image-mask pairing, raster metadata, PNG values and
date-level catalogue totals. When ``--dataset-root`` is supplied, it also opens
the released files and can recalculate their SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


EXPECTED_ANNUAL_COUNTS = {2020: 158, 2021: 141, 2022: 244, 2023: 138}
EXPECTED_TOTAL = 681
EXPECTED_WIDTH = 450
EXPECTED_HEIGHT = 450
EXPECTED_BANDS = 20
EXPECTED_EPSG = 4326
EXPECTED_PIXEL_SIZE = 0.02
EXPECTED_MASK_VALUES = {0, 255}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mask_stem(path_text: str) -> str:
    name = Path(path_text).stem
    return name[:-5] if name.endswith("_mask") else name


def resolve_relative_file(root: Path, year: int, relative_path: str) -> Path | None:
    """Support both all-years and single-archive extraction layouts."""
    relative = Path(relative_path.replace("\\", "/"))
    candidates = [root / str(year) / relative, root / relative]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def nearly_equal(left: float, right: float, tolerance: float = 1e-8) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def validate_manifest(
    rows: list[dict[str, str]],
    catalogue_rows: list[dict[str, str]],
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    scene_ids = [row.get("scene_id", "").strip() for row in rows]
    annual_counts = Counter(int(row["year"]) for row in rows)

    if len(rows) != EXPECTED_TOTAL:
        errors.append(f"manifest row count is {len(rows)}, expected {EXPECTED_TOTAL}")
    if len(set(scene_ids)) != len(scene_ids):
        duplicates = sorted(
            scene for scene, count in Counter(scene_ids).items() if count > 1
        )
        errors.append(f"duplicate scene_id values: {duplicates[:10]}")
    if dict(sorted(annual_counts.items())) != EXPECTED_ANNUAL_COUNTS:
        errors.append(
            f"annual manifest counts are {dict(sorted(annual_counts.items()))}, "
            f"expected {EXPECTED_ANNUAL_COUNTS}"
        )

    image_paths = [row.get("image_relative_path", "").strip() for row in rows]
    mask_paths = [row.get("mask_relative_path", "").strip() for row in rows]
    if len(set(image_paths)) != len(image_paths):
        errors.append("duplicate image_relative_path values found")
    if len(set(mask_paths)) != len(mask_paths):
        errors.append("duplicate mask_relative_path values found")

    for line_number, row in enumerate(rows, start=2):
        scene_id = row.get("scene_id", "").strip()
        image_stem = Path(row.get("image_relative_path", "")).stem
        paired_mask_stem = mask_stem(row.get("mask_relative_path", ""))
        if not scene_id or image_stem != scene_id or paired_mask_stem != scene_id:
            errors.append(f"manifest line {line_number}: inconsistent scene stems")

        expected_fields = {
            "width": EXPECTED_WIDTH,
            "height": EXPECTED_HEIGHT,
            "band_count": EXPECTED_BANDS,
            "mask_width": EXPECTED_WIDTH,
            "mask_height": EXPECTED_HEIGHT,
            "epsg": EXPECTED_EPSG,
        }
        for field, expected in expected_fields.items():
            if int(row[field]) != expected:
                errors.append(
                    f"manifest line {line_number}: {field}={row[field]}, expected {expected}"
                )

        if row.get("dtype", "").lower() != "float32":
            errors.append(f"manifest line {line_number}: GeoTIFF dtype is not float32")
        if row.get("compression", "").upper() != "LZW":
            errors.append(f"manifest line {line_number}: compression is not LZW")
        if row.get("pair_status", "").lower() != "paired":
            errors.append(f"manifest line {line_number}: pair_status is not paired")
        if row.get("mask_unique_values", "") != "0;255":
            errors.append(f"manifest line {line_number}: mask values are not 0;255")
        if not row.get("image_sha256", "").strip() or not row.get("mask_sha256", "").strip():
            errors.append(f"manifest line {line_number}: missing SHA-256 value")
        if not nearly_equal(float(row["pixel_size_x_deg"]), EXPECTED_PIXEL_SIZE):
            errors.append(f"manifest line {line_number}: unexpected x pixel size")
        if not nearly_equal(float(row["pixel_size_y_deg"]), EXPECTED_PIXEL_SIZE):
            errors.append(f"manifest line {line_number}: unexpected y pixel size")

    catalogue_counts: dict[int, int] = defaultdict(int)
    for row in catalogue_rows:
        catalogue_counts[int(row["year"])] += int(row["retained_mask_count"])
    if dict(sorted(catalogue_counts.items())) != EXPECTED_ANNUAL_COUNTS:
        errors.append(
            f"catalogue retained-mask totals are {dict(sorted(catalogue_counts.items()))}, "
            f"expected {EXPECTED_ANNUAL_COUNTS}"
        )

    summary = {
        "manifest_rows": len(rows),
        "unique_scene_ids": len(set(scene_ids)),
        "annual_manifest_counts": dict(sorted(annual_counts.items())),
        "catalogue_rows": len(catalogue_rows),
        "annual_catalogue_retained_mask_counts": dict(sorted(catalogue_counts.items())),
    }
    return errors, summary


def inspect_files(
    rows: list[dict[str, str]],
    dataset_root: Path,
    verify_hashes: bool,
) -> tuple[list[dict[str, str]], list[str]]:
    try:
        import numpy as np
        import rasterio
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "File inspection requires numpy, rasterio and Pillow. "
            "Install requirements.txt first."
        ) from exc

    audit_rows: list[dict[str, str]] = []
    errors: list[str] = []

    for row in rows:
        year = int(row["year"])
        scene_id = row["scene_id"]
        image_path = resolve_relative_file(
            dataset_root, year, row["image_relative_path"]
        )
        mask_path = resolve_relative_file(
            dataset_root, year, row["mask_relative_path"]
        )
        problems: list[str] = []

        if image_path is None:
            problems.append("image missing")
        if mask_path is None:
            problems.append("mask missing")

        if image_path is not None:
            try:
                with rasterio.open(image_path) as source:
                    if source.width != EXPECTED_WIDTH or source.height != EXPECTED_HEIGHT:
                        problems.append("unexpected GeoTIFF dimensions")
                    if source.count != EXPECTED_BANDS:
                        problems.append("unexpected GeoTIFF band count")
                    if set(source.dtypes) != {"float32"}:
                        problems.append("unexpected GeoTIFF dtype")
                    epsg = source.crs.to_epsg() if source.crs else None
                    if epsg != EXPECTED_EPSG:
                        problems.append("unexpected or missing GeoTIFF CRS")
                    if not nearly_equal(abs(source.transform.a), EXPECTED_PIXEL_SIZE):
                        problems.append("unexpected GeoTIFF x pixel size")
                    if not nearly_equal(abs(source.transform.e), EXPECTED_PIXEL_SIZE):
                        problems.append("unexpected GeoTIFF y pixel size")
                    compression = source.profile.get("compress")
                    if str(compression).lower() != "lzw":
                        problems.append("unexpected GeoTIFF compression")
            except Exception as exc:
                problems.append(f"GeoTIFF unreadable: {exc}")

        if mask_path is not None:
            try:
                with Image.open(mask_path) as image:
                    array = np.asarray(image)
                    if image.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
                        problems.append("unexpected PNG dimensions")
                    if array.ndim != 2:
                        problems.append("PNG mask is not single-channel")
                    values = set(int(value) for value in np.unique(array))
                    if not values.issubset(EXPECTED_MASK_VALUES):
                        problems.append(f"unexpected PNG values: {sorted(values)}")
            except Exception as exc:
                problems.append(f"PNG unreadable: {exc}")

        if verify_hashes and image_path is not None:
            if sha256(image_path).lower() != row["image_sha256"].lower():
                problems.append("image SHA-256 mismatch")
        if verify_hashes and mask_path is not None:
            if sha256(mask_path).lower() != row["mask_sha256"].lower():
                problems.append("mask SHA-256 mismatch")

        status = "pass" if not problems else "fail"
        audit_rows.append(
            {
                "year": str(year),
                "scene_id": scene_id,
                "image_path": str(image_path or ""),
                "mask_path": str(mask_path or ""),
                "status": status,
                "problems": "; ".join(problems),
            }
        )
        if problems:
            errors.append(f"{scene_id}: {'; '.join(problems)}")

    return audit_rows, errors


def write_audit_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["year", "scene_id", "image_path", "mask_path", "status", "problems"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--verify-hashes", action="store_true")
    parser.add_argument("--audit-csv", type=Path, default=Path("dataset_audit.csv"))
    parser.add_argument("--summary-json", type=Path, default=Path("dataset_audit.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_rows = read_csv(args.manifest)
    catalogue_rows = read_csv(args.catalogue)
    errors, summary = validate_manifest(manifest_rows, catalogue_rows)

    if args.dataset_root:
        if not args.dataset_root.is_dir():
            errors.append(f"dataset root does not exist: {args.dataset_root}")
        else:
            audit_rows, file_errors = inspect_files(
                manifest_rows, args.dataset_root, args.verify_hashes
            )
            write_audit_csv(args.audit_csv, audit_rows)
            summary["files_checked"] = len(audit_rows)
            summary["file_checks_passed"] = sum(
                row["status"] == "pass" for row in audit_rows
            )
            errors.extend(file_errors)

    summary["status"] = "pass" if not errors else "fail"
    summary["error_count"] = len(errors)
    summary["errors"] = errors
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

