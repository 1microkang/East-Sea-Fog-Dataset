"""Compatibility entry point for the sea-fog annotation interface.

The maintained implementation is ``scripts/annotate_sea_fog.py``. This file
is retained so that links to the earlier repository filename continue to work.
"""

from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "scripts" / "annotate_sea_fog.py"),
        run_name="__main__",
    )
