# Independent validation records

`validation_confusion_counts.csv` contains the frozen confusion-matrix counts reported in the manuscript. `validation_metrics.csv` contains ACC, PRE, REC and CSI recalculated from those counts.

For each source:

- `H` is a hit: both the independent reference and mask indicate sea fog.
- `M` is a miss: the reference indicates sea fog but the mask indicates non-fog.
- `F` is a false alarm: the reference indicates non-fog but the mask indicates sea fog.
- `C` is a correct rejection: both sources indicate non-fog.

The original coastal-station, ICOADS and CALIOP observations are third-party data and are not redistributed in this repository. Users must obtain them from the providers cited in the manuscript. The surface-observation counts are the effective counts obtained after the manuscript's spatiotemporal matching, weather screening, quality control and effective-count procedure. CALIOP results are a separate profile-level secondary validation and are not pooled with surface observations.
