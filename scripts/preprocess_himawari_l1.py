#!/usr/bin/env python3
"""Convert JAXA P-Tree Himawari L1 gridded NetCDF scenes to GeoTIFF.

The output follows the 20-layer structure described in the accompanying Data
Descriptor. The first 16 layers contain AHI spectral-band data, and the final
four layers contain angular variables. The script is intended for the
0.02-degree full-disk Level-1 gridded product used for the 2020-2023 dataset.

The NetCDF packed values are decoded explicitly. For albedo_01-albedo_06,
the JAXA correction factor and correction offset are applied after the NetCDF
scale factor and add offset. Thermal bands and geometry variables use their
NetCDF scale factor and add offset. No solar-zenith division is performed:
the released visible/near-infrared quantity is the P-Tree source-product
albedo, defined by the provider as top-of-atmosphere reflectance multiplied
by cos(SOZ).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from netCDF4 import Dataset
from rasterio.transform import from_origin


ALBEDO_VARIABLES = [f"albedo_{band:02d}" for band in range(1, 7)]
TBB_VARIABLES = [f"tbb_{band:02d}" for band in range(7, 17)]
GEOMETRY_VARIABLES = ["SAA", "SAZ", "SOA", "SOZ"]
OUTPUT_VARIABLES = ALBEDO_VARIABLES + TBB_VARIABLES + GEOMETRY_VARIABLES

LAYER_DESCRIPTIONS = [
    *(f"AHI B{band:02d} source-product albedo" for band in range(1, 7)),
    *(f"AHI B{band:02d} brightness temperature (K)" for band in range(7, 17)),
    "Satellite azimuth angle (degree)",
    "Satellite zenith angle (degree)",
    "Solar azimuth angle (degree)",
    "Solar zenith angle (degree)",
]

WEST = 119.0
EAST = 128.0
SOUTH = 27.0
NORTH = 36.0
GRID_SIZE = 0.02
EXPECTED_WIDTH = 450
EXPECTED_HEIGHT = 450


def scalar_attribute(variable, name: str, default: float) -> float:
    """Return a scalar NetCDF attribute with a documented default."""
    if name not in variable.ncattrs():
        return float(default)
    value = np.asarray(variable.getncattr(name)).reshape(-1)
    if value.size != 1:
        raise ValueError(
            f"{variable.name}.{name} must be scalar, found shape {value.shape}"
        )
    return float(value[0])


def read_packed_window(variable, row_slice: slice, col_slice: slice) -> np.ndarray:
    """Read the final two dimensions without automatic NetCDF scaling."""
    variable.set_auto_maskandscale(False)
    if variable.ndim < 2:
        raise ValueError(f"Variable {variable.name} has fewer than two dimensions")

    leading = (0,) * (variable.ndim - 2)
    raw = np.asarray(variable[leading + (row_slice, col_slice)])
    invalid = np.zeros(raw.shape, dtype=bool)

    for attribute_name in ("_FillValue", "missing_value"):
        if attribute_name in variable.ncattrs():
            fill_values = np.asarray(variable.getncattr(attribute_name)).reshape(-1)
            for fill_value in fill_values:
                invalid |= raw == fill_value

    scale_factor = scalar_attribute(variable, "scale_factor", 1.0)
    add_offset = scalar_attribute(variable, "add_offset", 0.0)
    decoded = raw.astype(np.float64) * scale_factor + add_offset

    if variable.name in ALBEDO_VARIABLES:
        correction_factor = scalar_attribute(variable, "correction_factor", 1.0)
        correction_offset = scalar_attribute(variable, "correction_offset", 0.0)
        decoded = decoded * correction_factor + correction_offset

    decoded = decoded.astype(np.float32)
    decoded[invalid] = np.nan
    return decoded


def crop_slices(
    source_west: float,
    source_north: float,
    pixel_size: float,
) -> tuple[slice, slice]:
    """Calculate the 450 x 450 East China Sea crop used in the release."""
    col_start = int(round((WEST - source_west) / pixel_size))
    col_stop = int(round((EAST - source_west) / pixel_size))
    row_start = int(round((source_north - NORTH) / pixel_size))
    row_stop = int(round((source_north - SOUTH) / pixel_size))

    if col_stop - col_start != EXPECTED_WIDTH:
        raise ValueError("Longitude bounds do not produce 450 output columns")
    if row_stop - row_start != EXPECTED_HEIGHT:
        raise ValueError("Latitude bounds do not produce 450 output rows")

    return slice(row_start, row_stop), slice(col_start, col_stop)


def convert_scene(
    input_path: Path,
    output_path: Path,
    source_west: float,
    source_north: float,
    pixel_size: float,
    overwrite: bool,
) -> str:
    """Convert one P-Tree NetCDF scene and return a status message."""
    if output_path.exists() and not overwrite:
        return f"existing: {output_path.name}"

    row_slice, col_slice = crop_slices(source_west, source_north, pixel_size)

    with Dataset(input_path, "r") as dataset:
        missing = [name for name in OUTPUT_VARIABLES if name not in dataset.variables]
        if missing:
            raise KeyError(f"Missing required variables: {', '.join(missing)}")

        layers = [
            read_packed_window(dataset.variables[name], row_slice, col_slice)
            for name in OUTPUT_VARIABLES
        ]

    stack = np.stack(layers, axis=0)
    if stack.shape != (20, EXPECTED_HEIGHT, EXPECTED_WIDTH):
        raise ValueError(f"Unexpected output shape: {stack.shape}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": EXPECTED_WIDTH,
        "height": EXPECTED_HEIGHT,
        "count": 20,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(WEST, NORTH, GRID_SIZE, GRID_SIZE),
        "compress": "LZW",
        "predictor": 3,
        "nodata": None,
    }

    with rasterio.open(output_path, "w", **profile) as destination:
        destination.write(stack)
        for index, description in enumerate(LAYER_DESCRIPTIONS, start=1):
            destination.set_band_description(index, description)

    return f"written: {output_path.name}"


def discover_netcdf_files(directory: Path, recursive: bool) -> Iterable[Path]:
    pattern = "**/*.nc" if recursive else "*.nc"
    return sorted(directory.glob(pattern))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument(
        "--source-west",
        type=float,
        default=80.0,
        help="western grid origin of the 2020-2023 full-disk product (default: 80)",
    )
    parser.add_argument(
        "--source-north",
        type=float,
        default=60.0,
        help="northern grid origin of the full-disk product (default: 60)",
    )
    parser.add_argument("--pixel-size", type=float, default=0.02)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input_directory.is_dir():
        raise SystemExit(f"Input directory does not exist: {args.input_directory}")

    input_files = list(discover_netcdf_files(args.input_directory, args.recursive))
    if not input_files:
        raise SystemExit(f"No .nc files found in {args.input_directory}")

    failures = 0
    for position, input_path in enumerate(input_files, start=1):
        output_name = f"{input_path.stem}_clipped.tif"
        output_path = args.output_directory / output_name
        try:
            status = convert_scene(
                input_path=input_path,
                output_path=output_path,
                source_west=args.source_west,
                source_north=args.source_north,
                pixel_size=args.pixel_size,
                overwrite=args.overwrite,
            )
            print(f"[{position}/{len(input_files)}] {status}")
        except Exception as exc:
            failures += 1
            print(f"[{position}/{len(input_files)}] failed: {input_path.name}: {exc}")

    print(f"Completed with {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
