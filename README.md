# A pixel-level annotated dataset for daytime sea fog segmentation over the East China Sea during 2020–2023

This repository contains the processing, annotation and quality-control code associated with the dataset **A pixel-level annotated dataset for daytime sea fog segmentation over the East China Sea during 2020–2023**. It also provides machine-readable metadata and frozen validation summaries. The dataset comprises 681 georeferenced daytime Advanced Himawari Imager (AHI) scenes and corresponding pixel-level binary masks delineating sea fog.

Scenes from 2020–2022 were acquired by Himawari-8, whereas the 2023 scenes were acquired by Himawari-9. Candidate dates were identified from operational sea fog bulletins issued by the National Meteorological Center of the China Meteorological Administration. The bulletins guided satellite-data retrieval but did not provide pixel labels. Daytime AHI observations were retrieved at nominal 30-min intervals within event-specific windows, and unavailable scenes were skipped.

![Dataset construction workflow](docs/construction_workflow.png)

## Data access

- Dataset record: [Zenodo](https://doi.org/10.5281/zenodo.21847718)
- Version: `1.0.0`
- Dataset licence: [Creative Commons Attribution–NonCommercial 4.0 International](https://creativecommons.org/licenses/by-nc/4.0/) (`CC BY-NC 4.0`)

The Zenodo record is currently an unpublished draft. The DOI will resolve when the record is published.

The original JAXA P-Tree Level-1 NetCDF files are not redistributed. The processed Himawari-8 and Himawari-9 AHI data included in the Zenodo deposit are redistributed with permission from the Japan Meteorological Agency and remain subject to the applicable terms of that permission. The released files are author-processed research products and are not official products of the Japan Aerospace Exploration Agency or the Japan Meteorological Agency.

## Dataset composition

| Year | Satellite | Scene–mask pairs | Archive | Approximate size |
|---|---|---:|---|---:|
| 2020 | Himawari-8 | 158 | `2020.zip` | 1.94 GB |
| 2021 | Himawari-8 | 141 | `2021.zip` | 1.77 GB |
| 2022 | Himawari-8 | 244 | `2022.zip` | 3.00 GB |
| 2023 | Himawari-9 | 138 | `2023.zip` | 1.69 GB |
| **Total** |  | **681** | Four annual archives | **8.40 GB** |

Each pair consists of one AHI scene and one spatially corresponding mask. The scene is stored as a 450 × 450-pixel, LZW-compressed, 32-bit floating-point GeoTIFF. Each GeoTIFF contains **16 AHI spectral bands and four angular variables in a fixed 20-layer structure**.

All layers are provided on a regular 0.02° latitude–longitude grid referenced to WGS 84 (`EPSG:4326`). The spatial extent is 119° E–128° E and 27° N–36° N. The released files retain the 0.02° grid of the downloaded Level-1 gridded product and were not spatially resampled by the authors. No explicit raster NoData value is declared.

## GeoTIFF layer structure

| GeoTIFF layer | Variable | Stored quantity | Unit |
|---:|---|---|---|
| 1–6 | AHI B01–B06 | Source-product albedo | Dimensionless |
| 7–16 | AHI B07–B16 | Brightness temperature | K |
| 17 | Satellite azimuth angle | Angular variable | Degrees |
| 18 | Satellite zenith angle | Angular variable | Degrees |
| 19 | Solar azimuth angle | Angular variable | Degrees |
| 20 | Solar zenith angle | Angular variable | Degrees |

Layers 1–16 contain the 16 AHI spectral bands. Layers 17–20 contain the four angular variables. For B01–B06, source-product albedo is the quantity supplied in the P-Tree product after the associated scale, offset and correction attributes are applied. The provider defines this quantity as top-of-atmosphere reflectance multiplied by the cosine of the solar zenith angle.

The complete layer order, nominal central wavelengths, instrument sampling characteristics, stored quantities and units are documented in [`metadata/band_dictionary.csv`](metadata/band_dictionary.csv).

## Mask format and file pairing

Each GeoTIFF is paired with a single-channel, 8-bit PNG mask of the same dimensions.

- `0` denotes non-fog.
- `255` denotes sea fog.

The PNG masks do not contain independent georeferencing metadata. Their spatial interpretation is inherited from the corresponding GeoTIFF through exact pixel-to-pixel alignment.

A scene and its mask share the same scene identifier:

```text
<scene_id>.tif
<scene_id>_mask.png
```

For example:

```text
NC_H08_20200121_0000_R21_FLDK.06001_06001_clipped.tif
NC_H08_20200121_0000_R21_FLDK.06001_06001_clipped_mask.png
```

`H08` and `H09` are filename identifiers for Himawari-8 and Himawari-9, respectively. `YYYYMMDD` and `HHMM` give the UTC acquisition date and time. The exact relative paths and SHA-256 checksums for all 681 pairs are provided in [`metadata/file_manifest_2020_2023.csv`](metadata/file_manifest_2020_2023.csv).

## Repository contents

```text
.
├── README.md
├── CITATION.cff
├── LICENSE_NOTICE.md
├── requirements.txt
├── H8_seafog_label.py
├── docs/
│   └── construction_workflow.png
├── scripts/
│   ├── preprocess_himawari_l1.py
│   ├── annotate_sea_fog.py
│   ├── verify_dataset.py
│   └── calculate_validation_metrics.py
├── metadata/
│   ├── archive_inventory.csv
│   ├── band_dictionary.csv
│   ├── event_catalogue_2020_2023.csv
│   ├── file_manifest_2020_2023.csv
│   ├── metadata_consistency_report.json
│   ├── SHA256SUMS_archives.txt
│   └── SHA256SUMS_images_masks.txt
└── validation/
    ├── README.md
    ├── validation_confusion_counts.csv
    └── validation_metrics.csv
```

- `archive_inventory.csv` records the annual archive names, satellites, pair counts and file sizes.
- `band_dictionary.csv` defines the fixed GeoTIFF layer order and the corresponding variables, quantities and units.
- `file_manifest_2020_2023.csv` contains one row for each released scene–mask pair. It records the scene identifier, acquisition time, relative file paths, raster structure, mask values and SHA-256 checksums.
- `event_catalogue_2020_2023.csv` is a date-level catalogue of retained scenes. Its rows should not be interpreted as statistically independent meteorological events.
- `metadata_consistency_report.json` records the frozen result of the metadata consistency check.
- The two checksum files support archive-level and scene-level integrity verification.

## Processing and annotation

The preprocessing workflow converts JAXA P-Tree Himawari Level-1 gridded NetCDF scenes to the fixed 20-layer GeoTIFF structure and extracts the East China Sea study area. Physical calibration is applied after download. Packed NetCDF values are decoded using the provider-supplied scale, offset and correction attributes. B01–B06 are stored as source-product albedo, whereas B07–B16 are stored as brightness temperature in kelvin. The four angular variables are retained with the spectral bands. The source grid is cropped without spatial resampling.

Experts interpreted three complementary AHI multispectral displays based on B05/B04/B03, B03/B04/B14 and an infrared microphysics composite. Each displayed component was stretched independently between its 2nd and 98th percentiles for visual interpretation only. Simple linear iterative clustering (SLIC) assisted boundary delineation. Temporally matched ERA5 fields provided environmental context.

Two meteorological experts independently reviewed each mask, and a third expert adjudicated disagreements. The annotation software supports candidate-mask production and visual inspection. The independent reviews and adjudication are controlled human-review stages and are not automated by the software.

Coastal-station observations, ICOADS marine surface observations and CALIOP profiles were not loaded or displayed during mask production. They were used exclusively for independent technical validation.

## Installation

Python 3.10 or later is recommended.

```bash
python -m pip install -r requirements.txt
```

The preprocessing workflow requires `netCDF4` and Rasterio. The annotation interface also requires a desktop environment with Tk support.

## Usage

### Preprocess Himawari Level-1 scenes

```bash
python scripts/preprocess_himawari_l1.py INPUT_NC_DIRECTORY OUTPUT_TIF_DIRECTORY
```

The input NetCDF files must be obtained separately from the data provider.

### Open the annotation interface

```bash
python scripts/annotate_sea_fog.py
```

### Verify metadata and extracted files

```bash
python scripts/verify_dataset.py \
  --manifest metadata/file_manifest_2020_2023.csv \
  --catalogue metadata/event_catalogue_2020_2023.csv
```

After extracting the annual archives, add `--dataset-root PATH --verify-hashes` to inspect the GeoTIFF and PNG files and verify their SHA-256 checksums.

### Recalculate validation metrics

```bash
python scripts/calculate_validation_metrics.py \
  validation/validation_confusion_counts.csv \
  validation/validation_metrics.csv
```

## Technical validation

All 681 scene–mask pairs passed file-integrity and structural checks. No damaged, missing or unmatched files were found.

The masks were independently compared with coastal-station and ICOADS observations. Each valid surface observation was matched to the temporally nearest daytime AHI scene within ±30 min. The mask value was extracted from the pixel containing the observation coordinates. For observations with horizontal visibility below 1 km, present-weather codes were used to exclude rain, snow, hail and thunderstorms. Duplicate observation–mask collocations were consolidated before the metrics were calculated.

CALIOP profiles provided a separate, spatially limited comparison. An ocean profile was classified as sea fog when its lowest cloud-classified vertical feature mask (VFM) bin occurred within two vertical bins of the expected ocean surface. This distance was no more than 60 m. A profile was also classified as sea fog when a surface or subsurface feature extended upward through at least two vertical bins. Each valid profile was matched to the mask for the temporally nearest daytime AHI scene within ±30 min. The mask value was extracted from the pixel containing the profile coordinates.

None of these validation observations was used at any stage of mask production. The repository provides the frozen confusion-matrix counts and the metrics calculated from those counts. It does not redistribute the original third-party validation observations.

| Source | H | M | F | C | n | ACC (%) | PRE (%) | REC (%) | CSI (%) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Coastal stations | 306 | 41 | 71 | 21,276 | 21,694 | 99.48 | 81.17 | 88.18 | 73.21 |
| ICOADS | 89 | 12 | 7 | 1,453 | 1,561 | 98.78 | 92.71 | 88.12 | 82.41 |
| CALIOP | 191 | 105 | 29 | 734 | 1,059 | 87.35 | 86.82 | 64.53 | 58.77 |

`H`, `M`, `F` and `C` denote hits, misses, false alarms and correct rejections, respectively. `ACC`, `PRE`, `REC` and `CSI` denote accuracy, precision, recall and the critical success index.

## Recommended uses

The dataset can support:

- development and evaluation of daytime sea fog segmentation methods;
- assessment of multispectral AHI inputs;
- transfer learning and domain adaptation;
- comparison of satellite-based sea fog segmentation algorithms; and
- reproducibility studies involving expert-labelled remote-sensing data.

When creating training, validation and test subsets, users should consider event-level separation to reduce temporal leakage among adjacent scenes from the same sea fog episode.

## Limitations

The dataset is event based and contains daytime scenes only. It is not a continuous record and should not be treated as a climatologically unbiased sample of sea fog occurrence. It should not be used directly to estimate sea fog frequency, duration or climatology without accounting for the event-guided sampling strategy.

The masks represent expert interpretation of satellite and meteorological information. They are reference annotations for segmentation research, not direct in situ measurements of fog boundaries.

## Licence and third-party rights

The Zenodo dataset is distributed under the [Creative Commons Attribution–NonCommercial 4.0 International licence](https://creativecommons.org/licenses/by-nc/4.0/) (`CC BY-NC 4.0`). This licence applies to the authors' original data selection, processing, annotations, masks, organisation and record metadata to the extent that the authors hold the relevant rights.

The processed Himawari-8 and Himawari-9 AHI data are redistributed with permission from the Japan Meteorological Agency and remain subject to the applicable terms of that permission. Underlying satellite observations remain subject to the rights and conditions of their providers.

The dataset licence does not automatically serve as a software licence for the source code in this repository. Unless an explicit software licence is added, the code is provided for transparency and reproducibility with copyright retained by the authors. See [`LICENSE_NOTICE.md`](LICENSE_NOTICE.md) for details.

## Funding

This work was supported by the Joint Fund of the Zhejiang Provincial Natural Science Foundation of China under Grant No. LZJMZ24D050002, the National Natural Science Foundation of China under Grant No. 42371331, the Public Welfare Science and Technology Project of Ningbo under Grant No. 202002N3104, and the Public Welfare Science and Technology Project of Ningbo under Grant No. 2025S093.

## Citation

Please cite the version of the dataset used in your work:

> Kang, X., Li, Y., Wu, N., Hu, L., Fu, R. & Jin, W. *A pixel-level annotated dataset for daytime sea fog segmentation over the East China Sea during 2020–2023*, version 1.0.0. Zenodo. <https://doi.org/10.5281/zenodo.21847718> (2026).

```bibtex
@dataset{kang2026east_china_sea_fog,
  author    = {Kang, Xiao and Li, Yuejun and Wu, Nan and Hu, Lijun and Fu, Randi and Jin, Wei},
  title     = {A pixel-level annotated dataset for daytime sea fog segmentation over the East China Sea during 2020--2023},
  year      = {2026},
  version   = {1.0.0},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.21847718},
  url       = {https://doi.org/10.5281/zenodo.21847718}
}
```

## Authors

The author order is Xiao Kang, Yuejun Li, Nan Wu, Lijun Hu, Randi Fu and Wei Jin. Xiao Kang and Yuejun Li contributed equally and are co-first authors. Randi Fu and Wei Jin are the corresponding authors.

Questions and reproducibility reports may be submitted through the GitHub issue tracker.
