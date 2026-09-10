# -*- coding: utf-8 -*-
"""
East China Sea daytime sea fog annotation system

This program is used for multispectral interpretation, SLIC-assisted
delineation, binary mask production, and scene–mask overlay inspection.

Workflow boundary
-----------------
1. Candidate dates are determined outside this program using NMC sea fog
   bulletins.
2. Himawari-8/9 AHI Level-1 data are calibrated, georeferenced, cropped,
   and written as fixed 20-layer GeoTIFF files before being loaded here. The
   files contain 16 AHI spectral bands and four angular variables.
3. This program displays three AHI multispectral combinations and uses
   SLIC superpixels to assist expert annotation.
4. Temporally matched ERA5 fields may be examined separately by experts
   as environmental context. ERA5 data are not incorporated into the
   released GeoTIFF images or masks.
5. Coastal-station, ICOADS, and CALIOP observations are reserved for
   independent technical validation and are not loaded or displayed
   during mask production.

Dependencies
------------
numpy
rasterio
opencv-python
scikit-image
Pillow
"""

import glob
import json
import os
import re
import traceback
from typing import Optional

import cv2
import numpy as np
import rasterio
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont
from skimage.segmentation import mark_boundaries, slic
from tkinter import filedialog, messagebox


# =============================================================================
# 1. Path configuration
# =============================================================================

CONFIG = {
    # Preprocessed 20-layer Himawari GeoTIFF files
    "INPUT_TIF_DIR": "",

    # Temporary four-panel images used by the annotation interface
    "LABELME_IMAGE_DIR": "",

    # Accepted binary PNG masks
    "FINAL_MASK_DIR": "",

    # B05/B04/B03 images with accepted masks overlaid
    "OVERLAY_OUTPUT_DIR": "",
}

CONFIG_FILE = "path_config.json"


class PathConfigDialog:
    """Path configuration dialog."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("East China Sea sea fog annotation system")
        self.root.geometry("820x420")
        self.root.resizable(True, True)

        self.path_vars = {}
        self._load_config()
        self._build_ui()

    def _load_config(self):
        """Load only recognised configuration fields."""
        if not os.path.exists(CONFIG_FILE):
            return

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                saved_config = json.load(file)

            for key in CONFIG:
                if key in saved_config:
                    CONFIG[key] = saved_config[key]

        except Exception as exc:
            print(f"Failed to load configuration: {exc}")

    def _save_config(self):
        """Save current path configuration."""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as file:
                json.dump(CONFIG, file, ensure_ascii=False, indent=4)
        except Exception as exc:
            print(f"Failed to save configuration: {exc}")

    def _build_ui(self):
        title_label = tk.Label(
            self.root,
            text="East China Sea daytime sea fog annotation system",
            font=("Arial", 16, "bold"),
        )
        title_label.pack(pady=15)

        subtitle = tk.Label(
            self.root,
            text=(
                "AHI multispectral interpretation and SLIC-assisted annotation\n"
                "Independent validation observations are not displayed."
            ),
            font=("Arial", 10),
            fg="#555555",
        )
        subtitle.pack(pady=(0, 10))

        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=20)

        path_items = [
            ("INPUT_TIF_DIR", "20-layer GeoTIFF directory:"),
            ("LABELME_IMAGE_DIR", "Annotation-image directory:"),
            ("FINAL_MASK_DIR", "Accepted-mask directory:"),
            ("OVERLAY_OUTPUT_DIR", "Overlay-output directory:"),
        ]

        for row, (key, label_text) in enumerate(path_items):
            label = tk.Label(
                frame,
                text=label_text,
                width=25,
                anchor="e",
                font=("Arial", 10),
            )
            label.grid(row=row, column=0, padx=5, pady=9, sticky="e")

            path_var = tk.StringVar(value=CONFIG[key])
            self.path_vars[key] = path_var

            entry = tk.Entry(
                frame,
                textvariable=path_var,
                width=62,
                font=("Arial", 9),
            )
            entry.grid(row=row, column=1, padx=5, pady=9, sticky="ew")

            button = tk.Button(
                frame,
                text="Browse",
                width=9,
                command=lambda variable=path_var: self._browse_directory(variable),
            )
            button.grid(row=row, column=2, padx=5, pady=9)

        frame.columnconfigure(1, weight=1)

        note = tk.Label(
            self.root,
            text=(
                "Coastal-station, ICOADS, and CALIOP data are used only for "
                "independent validation and are intentionally excluded here."
            ),
            font=("Arial", 9),
            fg="#8A4B08",
            wraplength=740,
            justify="left",
        )
        note.pack(padx=25, pady=(0, 10), anchor="w")

        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=12)

        start_button = tk.Button(
            button_frame,
            text="Start",
            width=14,
            height=2,
            command=self._start_processing,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 11, "bold"),
        )
        start_button.pack(side="left", padx=10)

        cancel_button = tk.Button(
            button_frame,
            text="Cancel",
            width=14,
            height=2,
            command=self.root.destroy,
            bg="#F44336",
            fg="white",
            font=("Arial", 11, "bold"),
        )
        cancel_button.pack(side="left", padx=10)

    @staticmethod
    def _browse_directory(path_var):
        directory = filedialog.askdirectory(initialdir=path_var.get())
        if directory:
            path_var.set(directory)

    def _start_processing(self):
        for key, path_var in self.path_vars.items():
            CONFIG[key] = path_var.get().strip()

        missing_fields = [
            key for key, value in CONFIG.items()
            if not value
        ]
        if missing_fields:
            messagebox.showerror(
                "Missing path",
                "Please configure all required directories.",
            )
            return

        if not os.path.isdir(CONFIG["INPUT_TIF_DIR"]):
            messagebox.showerror(
                "Invalid input directory",
                "The configured GeoTIFF input directory does not exist.",
            )
            return

        self._save_config()
        self.root.destroy()

        for key in (
            "LABELME_IMAGE_DIR",
            "FINAL_MASK_DIR",
            "OVERLAY_OUTPUT_DIR",
        ):
            os.makedirs(CONFIG[key], exist_ok=True)

        run_application()

    def run(self):
        self.root.mainloop()


# =============================================================================
# 2. Dataset and display parameters
# =============================================================================

# Rasterio uses one-based band indexing.
BANDS_B05_B04_B03 = (5, 4, 3)
BANDS_B03_B04_B14 = (3, 4, 14)

# IR microphysics display:
# red = B15 - B13
# green = B13 - B07
# blue = B13
BANDS_IR_MICROPHYSICS = (15, 13, 7)

REQUIRED_LAYER_COUNT = 20
EXPECTED_HEIGHT = 450
EXPECTED_WIDTH = 450

# The same stretch is used for each displayed component.
DISPLAY_PERCENTILE_LOW = 2.0
DISPLAY_PERCENTILE_HIGH = 98.0

SLIC_N_SEGMENTS = 1000
SLIC_COMPACTNESS = 20
SLIC_SIGMA = 1

MASK_BACKGROUND_VALUE = 0
MASK_FOG_VALUE = 255

OVERLAY_COLOR_BGR = (0, 0, 255)
OVERLAY_ALPHA = 0.40
SUPERPIXEL_BOUNDARY_RGB = (1.0, 0.65, 0.0)

WINDOW_NAME = "AHI multispectral interpretation and SLIC annotation"
STATUS_BAR_HEIGHT = 135


# =============================================================================
# 3. General helper functions
# =============================================================================

def cv2_img_add_text(
    image,
    text,
    left,
    top,
    text_color=(255, 255, 255),
    text_size=22,
):
    """Draw Unicode text on an OpenCV image using Pillow."""
    if image is None:
        return image

    if image.ndim == 2:
        pil_image = Image.fromarray(image)
    else:
        pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    draw = ImageDraw.Draw(pil_image)

    font_candidates = [
        "arial.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
    ]

    font = None
    for font_path in font_candidates:
        try:
            font = ImageFont.truetype(font_path, text_size)
            break
        except OSError:
            continue

    if font is None:
        font = ImageFont.load_default()

    draw.text(
        (left, top),
        text,
        fill=tuple(int(value) for value in text_color),
        font=font,
    )

    result = np.asarray(pil_image)

    if image.ndim == 3:
        result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)

    return result


def to_uint8_stretch(
    array,
    lower_percentile=DISPLAY_PERCENTILE_LOW,
    upper_percentile=DISPLAY_PERCENTILE_HIGH,
):
    """
    Convert one component to uint8 using an independent percentile stretch.

    Non-finite values are excluded when the stretch limits are calculated.
    """
    array = np.asarray(array, dtype=np.float32)
    finite_mask = np.isfinite(array)

    if not np.any(finite_mask):
        return np.zeros(array.shape, dtype=np.uint8)

    finite_values = array[finite_mask]
    lower = np.percentile(finite_values, lower_percentile)
    upper = np.percentile(finite_values, upper_percentile)

    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        output = np.zeros(array.shape, dtype=np.uint8)
        output[finite_mask] = 0
        return output

    scaled = (array - lower) / (upper - lower)
    scaled = np.clip(scaled, 0.0, 1.0)
    scaled[~finite_mask] = 0.0

    return np.round(scaled * 255.0).astype(np.uint8)


def validate_source_raster(src, tif_path):
    """Check whether a GeoTIFF matches the released raster structure."""
    errors = []

    if src.count != REQUIRED_LAYER_COUNT:
        errors.append(
            f"expected {REQUIRED_LAYER_COUNT} layers, found {src.count}"
        )

    if src.height != EXPECTED_HEIGHT or src.width != EXPECTED_WIDTH:
        errors.append(
            "expected "
            f"{EXPECTED_WIDTH} × {EXPECTED_HEIGHT} pixels, found "
            f"{src.width} × {src.height}"
        )

    maximum_required_band = max(
        BANDS_B05_B04_B03
        + BANDS_B03_B04_B14
        + BANDS_IR_MICROPHYSICS
    )
    if src.count < maximum_required_band:
        errors.append(
            f"band {maximum_required_band} is required for visualisation"
        )

    if errors:
        print(f"Skipped {os.path.basename(tif_path)}: {'; '.join(errors)}")
        return False

    return True


def create_rgb_stack(src, band_indices):
    """
    Construct a three-channel display image.

    Each band is independently stretched between its 2nd and 98th
    percentiles, as described in the manuscript.
    """
    channels = []

    for band_index in band_indices:
        band = src.read(band_index)
        channels.append(to_uint8_stretch(band))

    return np.dstack(channels)


def create_ir_microphysics_stack(src):
    """
    Construct the daytime IR-microphysics display.

    R = B15 - B13
    G = B13 - B07
    B = B13
    """
    band_15 = src.read(15).astype(np.float32)
    band_13 = src.read(13).astype(np.float32)
    band_07 = src.read(7).astype(np.float32)

    red = to_uint8_stretch(band_15 - band_13)
    green = to_uint8_stretch(band_13 - band_07)
    blue = to_uint8_stretch(band_13)

    return np.dstack([red, green, blue])


def list_tif_files(directory):
    """Return sorted .tif and .tiff files without duplicates."""
    tif_files = glob.glob(os.path.join(directory, "*.tif"))
    tif_files.extend(glob.glob(os.path.join(directory, "*.tiff")))
    return sorted(set(tif_files))


def safe_remove(path):
    """Remove a temporary file if it exists."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        print(f"Could not remove temporary file {path}: {exc}")


# =============================================================================
# 4. Stage 1: generate multispectral annotation images
# =============================================================================

def step1_generate_annotation_images():
    """
    Generate a four-panel image for each eligible 20-layer GeoTIFF.

    Upper left:
        B05/B04/B03 composite
    Upper right:
        IR-microphysics composite
    Lower left:
        B03/B04/B14 composite
    Lower right:
        B03/B04/B14 composite used for SLIC-assisted delineation

    No coastal-station, ICOADS, CALIOP, or visibility observations are
    read or displayed.
    """
    tif_files = list_tif_files(CONFIG["INPUT_TIF_DIR"])
    os.makedirs(CONFIG["LABELME_IMAGE_DIR"], exist_ok=True)

    print("\n[Stage 1/3] Generating multispectral annotation images")
    print(f"GeoTIFF scenes found: {len(tif_files)}")

    generated_count = 0
    skipped_count = 0

    for index, tif_path in enumerate(tif_files, start=1):
        filename = os.path.basename(tif_path)
        base_name = os.path.splitext(filename)[0]
        output_path = os.path.join(
            CONFIG["LABELME_IMAGE_DIR"],
            f"{base_name}.png",
        )

        if os.path.exists(output_path):
            print(f"[{index}/{len(tif_files)}] Existing: {filename}")
            continue

        try:
            with rasterio.open(tif_path) as src:
                if not validate_source_raster(src, tif_path):
                    skipped_count += 1
                    continue

                upper_left_rgb = create_rgb_stack(
                    src,
                    BANDS_B05_B04_B03,
                )
                upper_right_rgb = create_ir_microphysics_stack(src)
                lower_left_rgb = create_rgb_stack(
                    src,
                    BANDS_B03_B04_B14,
                )
                lower_right_rgb = lower_left_rgb.copy()

            height, width = upper_left_rgb.shape[:2]
            panel_image_rgb = np.zeros(
                (height * 2, width * 2, 3),
                dtype=np.uint8,
            )

            panel_image_rgb[0:height, 0:width] = upper_left_rgb
            panel_image_rgb[0:height, width:width * 2] = upper_right_rgb
            panel_image_rgb[height:height * 2, 0:width] = lower_left_rgb
            panel_image_rgb[
                height:height * 2,
                width:width * 2,
            ] = lower_right_rgb

            # OpenCV expects BGR order when saving.
            panel_image_bgr = cv2.cvtColor(
                panel_image_rgb,
                cv2.COLOR_RGB2BGR,
            )

            if not cv2.imwrite(output_path, panel_image_bgr):
                raise IOError(f"Failed to write {output_path}")

            generated_count += 1
            print(f"[{index}/{len(tif_files)}] Generated: {filename}")

        except Exception as exc:
            skipped_count += 1
            print(f"Failed to process {filename}: {exc}")
            traceback.print_exc()

    print(
        "Stage 1 completed: "
        f"{generated_count} generated, {skipped_count} skipped."
    )


# =============================================================================
# 5. Stage 2: interactive SLIC-assisted annotation
# =============================================================================

current_segments: Optional[np.ndarray] = None
current_selected_ids = set()
current_display_image: Optional[np.ndarray] = None
current_panel_base: Optional[np.ndarray] = None
current_height = 0
current_width = 0


def render_selected_regions():
    """Redraw the SLIC panel and highlight selected superpixels."""
    global current_display_image

    if (
        current_display_image is None
        or current_panel_base is None
        or current_segments is None
    ):
        return

    panel = current_panel_base.copy()

    if current_selected_ids:
        selected_mask = np.isin(
            current_segments,
            list(current_selected_ids),
        )

        colour_layer = np.zeros_like(panel)
        colour_layer[:] = OVERLAY_COLOR_BGR

        blended = cv2.addWeighted(
            panel,
            1.0 - OVERLAY_ALPHA,
            colour_layer,
            OVERLAY_ALPHA,
            0,
        )

        panel[selected_mask] = blended[selected_mask]

    current_display_image[
        current_height:current_height * 2,
        current_width:current_width * 2,
    ] = panel


def mouse_callback(event, x, y, flags, param):
    """
    Select or deselect an entire SLIC superpixel in the lower-right panel.
    """
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if current_segments is None:
        return

    if not (
        current_width <= x < current_width * 2
        and current_height <= y < current_height * 2
    ):
        return

    local_x = x - current_width
    local_y = y - current_height

    if not (
        0 <= local_y < current_segments.shape[0]
        and 0 <= local_x < current_segments.shape[1]
    ):
        return

    segment_id = int(current_segments[local_y, local_x])

    if segment_id in current_selected_ids:
        current_selected_ids.remove(segment_id)
    else:
        current_selected_ids.add(segment_id)

    render_selected_regions()


def build_status_bar(image_width, filename, message=None):
    """Create the status and instruction area below the annotation image."""
    status_bar = np.full(
        (STATUS_BAR_HEIGHT, image_width, 3),
        245,
        dtype=np.uint8,
    )

    status_bar = cv2_img_add_text(
        status_bar,
        f"Scene: {filename}",
        10,
        8,
        text_color=(30, 30, 30),
        text_size=20,
    )

    status_bar = cv2_img_add_text(
        status_bar,
        (
            "Lower-right panel: click a SLIC region to select/deselect it. "
            "Independent validation observations are not displayed."
        ),
        10,
        48,
        text_color=(40, 40, 40),
        text_size=18,
    )

    instruction = (
        "[S] Save accepted mask    "
        "[C] Clear selection    "
        "[Esc] Skip without saving    "
        "[Q] Quit"
    )

    if message:
        instruction = message

    status_bar = cv2_img_add_text(
        status_bar,
        instruction,
        10,
        88,
        text_color=(0, 0, 180) if message else (40, 40, 40),
        text_size=18,
    )

    return status_bar


def make_slic_boundary_panel(image_rgb, segments):
    """Draw thin SLIC boundaries over the lower-right source image."""
    boundary_image = mark_boundaries(
        image_rgb,
        segments,
        color=SUPERPIXEL_BOUNDARY_RGB,
        mode="outer",
    )

    boundary_image = np.clip(
        boundary_image * 255.0,
        0,
        255,
    ).astype(np.uint8)

    return cv2.cvtColor(boundary_image, cv2.COLOR_RGB2BGR)


def save_binary_mask(mask_path):
    """Save selected SLIC regions as a single-channel 0/255 PNG mask."""
    selected_mask = np.isin(
        current_segments,
        list(current_selected_ids),
    )

    output_mask = np.zeros(
        current_segments.shape,
        dtype=np.uint8,
    )
    output_mask[selected_mask] = MASK_FOG_VALUE

    unique_values = set(np.unique(output_mask).tolist())
    if not unique_values.issubset(
        {MASK_BACKGROUND_VALUE, MASK_FOG_VALUE}
    ):
        raise ValueError(
            f"Unexpected mask values: {sorted(unique_values)}"
        )

    if not cv2.imwrite(mask_path, output_mask):
        raise IOError(f"Failed to write mask: {mask_path}")


def step2_interactive_segmentation():
    """
    Interactively select SLIC superpixels representing sea fog.

    Only expert-accepted masks are saved. Pressing Escape skips the scene
    without writing an all-zero mask.
    """
    global current_segments
    global current_selected_ids
    global current_display_image
    global current_panel_base
    global current_height
    global current_width

    image_files = sorted(
        glob.glob(
            os.path.join(CONFIG["LABELME_IMAGE_DIR"], "*.png")
        )
    )
    os.makedirs(CONFIG["FINAL_MASK_DIR"], exist_ok=True)

    print("\n[Stage 2/3] SLIC-assisted expert annotation")
    print(f"Annotation images found: {len(image_files)}")

    stop_all = False

    for index, image_path in enumerate(image_files, start=1):
        filename = os.path.basename(image_path)
        base_name = os.path.splitext(filename)[0]
        output_mask_path = os.path.join(
            CONFIG["FINAL_MASK_DIR"],
            f"{base_name}_mask.png",
        )

        if os.path.exists(output_mask_path):
            print(
                f"[{index}/{len(image_files)}] "
                f"Accepted mask already exists: {filename}"
            )
            continue

        panel_image = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if panel_image is None:
            print(f"Could not read annotation image: {image_path}")
            continue

        total_height, total_width = panel_image.shape[:2]

        if total_height % 2 != 0 or total_width % 2 != 0:
            print(f"Invalid four-panel dimensions: {filename}")
            continue

        current_height = total_height // 2
        current_width = total_width // 2

        lower_right_bgr = panel_image[
            current_height:current_height * 2,
            current_width:current_width * 2,
        ].copy()

        lower_right_rgb = cv2.cvtColor(
            lower_right_bgr,
            cv2.COLOR_BGR2RGB,
        )

        try:
            current_segments = slic(
                lower_right_rgb,
                n_segments=SLIC_N_SEGMENTS,
                compactness=SLIC_COMPACTNESS,
                sigma=SLIC_SIGMA,
                start_label=1,
                channel_axis=-1,
                enforce_connectivity=True,
            )
        except Exception as exc:
            print(f"SLIC failed for {filename}: {exc}")
            traceback.print_exc()
            continue

        current_selected_ids = set()
        current_display_image = panel_image.copy()
        current_panel_base = make_slic_boundary_panel(
            lower_right_rgb,
            current_segments,
        )

        render_selected_regions()

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW_NAME, mouse_callback)

        screen_height = 900
        available_height = screen_height - 100
        total_display_height = total_height + STATUS_BAR_HEIGHT

        scale = min(
            1.0,
            available_height / max(total_display_height, 1),
        )

        cv2.resizeWindow(
            WINDOW_NAME,
            int(total_width * scale),
            int(total_display_height * scale),
        )

        print(
            f"[{index}/{len(image_files)}] Annotating: {filename}"
        )

        warning_message = None

        while True:
            status_bar = build_status_bar(
                total_width,
                filename,
                warning_message,
            )
            warning_message = None

            full_display = np.vstack(
                [current_display_image, status_bar]
            )
            cv2.imshow(WINDOW_NAME, full_display)

            key = cv2.waitKey(30) & 0xFF

            if key in (ord("s"), ord("S")):
                if not current_selected_ids:
                    warning_message = (
                        "No sea fog region selected. "
                        "The scene was not saved."
                    )
                    print(
                        f"No selected fog region; mask not saved: "
                        f"{filename}"
                    )
                    continue

                try:
                    save_binary_mask(output_mask_path)
                    print(f"Accepted mask saved: {output_mask_path}")
                except Exception as exc:
                    warning_message = f"Save failed: {exc}"
                    print(f"Failed to save mask: {exc}")
                    continue

                break

            if key in (ord("c"), ord("C")):
                current_selected_ids.clear()
                render_selected_regions()
                print(f"Selection cleared: {filename}")

            elif key == 27:
                print(
                    f"Scene skipped without saving a mask: {filename}"
                )
                break

            elif key in (ord("q"), ord("Q")):
                print("Annotation terminated by user.")
                stop_all = True
                break

        cv2.destroyWindow(WINDOW_NAME)

        # Remove the temporary four-panel image only after an accepted
        # mask has been saved. Skipped scenes remain available for review.
        if os.path.exists(output_mask_path):
            safe_remove(image_path)

        if stop_all:
            break

    cv2.destroyAllWindows()
    print("Stage 2 completed.")


# =============================================================================
# 6. Stage 3: create released scene–mask overlay previews
# =============================================================================

def step3_visualize_overlays():
    """
    Create visual checks using the B05/B04/B03 composite.

    The GeoTIFF retains the numerical multiband values. The overlay images
    are visual inspection products only and do not alter the released mask.
    """
    tif_files = list_tif_files(CONFIG["INPUT_TIF_DIR"])
    os.makedirs(CONFIG["OVERLAY_OUTPUT_DIR"], exist_ok=True)

    print("\n[Stage 3/3] Generating scene–mask overlay previews")

    generated_count = 0
    missing_mask_count = 0

    for index, tif_path in enumerate(tif_files, start=1):
        filename = os.path.basename(tif_path)
        base_name = os.path.splitext(filename)[0]

        mask_path = os.path.join(
            CONFIG["FINAL_MASK_DIR"],
            f"{base_name}_mask.png",
        )
        overlay_output_path = os.path.join(
            CONFIG["OVERLAY_OUTPUT_DIR"],
            f"{base_name}_overlay.png",
        )

        if not os.path.exists(mask_path):
            missing_mask_count += 1
            continue

        if os.path.exists(overlay_output_path):
            print(
                f"[{index}/{len(tif_files)}] "
                f"Overlay already exists: {filename}"
            )
            continue

        try:
            with rasterio.open(tif_path) as src:
                if not validate_source_raster(src, tif_path):
                    continue

                # Figure examples in the manuscript use B05/B04/B03.
                background_rgb = create_rgb_stack(
                    src,
                    BANDS_B05_B04_B03,
                )

            background_bgr = cv2.cvtColor(
                background_rgb,
                cv2.COLOR_RGB2BGR,
            )

            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            if mask is None:
                print(f"Could not read mask: {mask_path}")
                continue

            if mask.shape != background_bgr.shape[:2]:
                print(
                    f"Dimension mismatch for {filename}: "
                    f"image={background_bgr.shape[:2]}, "
                    f"mask={mask.shape}"
                )
                continue

            # Treat only the released fog value as sea fog.
            fog_pixels = mask == MASK_FOG_VALUE

            colour_layer = np.zeros_like(background_bgr)
            colour_layer[:] = OVERLAY_COLOR_BGR

            blended = cv2.addWeighted(
                background_bgr,
                1.0 - OVERLAY_ALPHA,
                colour_layer,
                OVERLAY_ALPHA,
                0,
            )

            overlay = background_bgr.copy()
            overlay[fog_pixels] = blended[fog_pixels]

            if not cv2.imwrite(overlay_output_path, overlay):
                raise IOError(
                    f"Failed to write overlay: {overlay_output_path}"
                )

            generated_count += 1
            print(
                f"[{index}/{len(tif_files)}] "
                f"Overlay generated: {filename}"
            )

        except Exception as exc:
            print(f"Overlay generation failed for {filename}: {exc}")
            traceback.print_exc()

    print(
        "Stage 3 completed: "
        f"{generated_count} overlays generated; "
        f"{missing_mask_count} scenes had no accepted mask."
    )


# =============================================================================
# 7. Main application
# =============================================================================

def run_application():
    try:
        step1_generate_annotation_images()
        step2_interactive_segmentation()
        step3_visualize_overlays()

        print("\nAll processing stages completed.")
        print(
            "Reminder: expert agreement review and third-expert "
            "adjudication must be conducted as separate controlled "
            "review stages before public release."
        )

    except Exception as exc:
        print(f"Program terminated because of an error: {exc}")
        traceback.print_exc()

    finally:
        try:
            input("\nPress Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    PathConfigDialog().run()
