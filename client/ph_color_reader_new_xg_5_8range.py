# ph_grid_color_reader.py
# Callable pH estimation module (no CLI)
import os
from pathlib import Path
import cv2
import numpy as np
from dotenv import load_dotenv

# =========================
# USER CONFIGURATION
# =========================
load_dotenv()
if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
# Default crop settings (edit here to change behavior)
crop_cfg = {
    'enabled': True,      # Set to True to crop outputs by default
    'padding_top': 400,
    'padding_bottom': 200,
    'padding_left': 900,
    'padding_right': 300,
}

STRIP_ROI = (180, 950, 120, 260)   # (x, y, w, h)  ← you may fine-tune

# ---- color card layout (IN CROPPED IMAGE COORDS)
CARD_ORIGIN = (1150, 1100)          # top-left of pH=1 block
CELL_W = 150
CELL_H = 180
COL_GAP = 200
# Allow a different column gap for the second row
COL_GAP_ROW2 = 200  # <-- Set this to the actual gap for the second row
ROW_GAP = 300

PH_VALUES = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])  # 12 values, 6 per row

# =========================
# UTILS
# =========================

def crop_image(img, crop_cfg):
    h, w = img.shape[:2]
    x1 = max(0, crop_cfg["padding_left"])
    x2 = min(w, w - crop_cfg["padding_right"])
    y1 = max(0, crop_cfg["padding_top"])
    y2 = min(h, h - crop_cfg["padding_bottom"])
    return img[y1:y2, x1:x2]


def mean_bgr(img, roi):
    x, y, w, h = roi
    patch = img[y:y+h, x:x+w]
    return patch.mean(axis=(0, 1))


def bgr_to_lab(bgr):
    bgr = np.uint8([[bgr]])
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    return lab[0, 0].astype(float)


def delta_e(lab1, lab2):
    return np.linalg.norm(lab1 - lab2)


# =========================
# REFERENCE GRID
# =========================

def generate_reference_rois():
    rois = []
    x0, y0 = CARD_ORIGIN


    # First row: 0.0 to 2.5 (6 columns)
    for col in range(6):
        x = x0 + col * (CELL_W + COL_GAP)
        y = y0
        rois.append((x, y, CELL_W, CELL_H))

    # Second row can use a different spacing if calibration requires it.
    for col in range(6):
        x = x0 + col * (CELL_W + COL_GAP_ROW2)
        y = y0 + (CELL_H + ROW_GAP)
        rois.append((x, y, CELL_W, CELL_H))

    return rois


# =========================
# CORE FUNCTION (PUBLIC API)
# =========================

def ph_from_image(image_path, output_dir, original_filename=None):
    img_full = cv2.imread(str(image_path))
    if img_full is None:
        raise RuntimeError("Image load failed")

    # ---- crop first
    img = crop_image(img_full, crop_cfg)

    ref_rois = generate_reference_rois()


    # ---- extract LAB colors
    strip_lab = bgr_to_lab(mean_bgr(img, STRIP_ROI))
    ref_labs = np.array([
        bgr_to_lab(mean_bgr(img, roi))
        for roi in ref_rois
    ])

    # ---- normalize using white region above color card
    # Typical ROI: above the color blocks, e.g., (x, y, w, h) = (CARD_ORIGIN[0], CARD_ORIGIN[1] - 80, 200, 60)
    WHITE_ROI = (970,870,100,100)
    white_lab = bgr_to_lab(mean_bgr(img, WHITE_ROI))
    strip_lab -= white_lab
    ref_labs -= white_lab

    # # ---- normalize using pH 7 (index 6) (previous method)
    # ref7 = ref_labs[6]
    # strip_lab -= ref7
    # ref_labs -= ref7

    # ---- compute distances
    distances = np.array([
        delta_e(strip_lab, lab) for lab in ref_labs
    ])

    # ---- interpolate using closest and its closest neighbor
    i1 = np.argmin(distances)  # index of minimum distance
    # Find neighbor: left or right, whichever has smaller distance
    if i1 == 0:
        i2 = 1
    elif i1 == len(distances) - 1:
        i2 = len(distances) - 2
    else:
        left = distances[i1 - 1]
        right = distances[i1 + 1]
        i2 = i1 - 1 if left < right else i1 + 1
    d1, d2 = distances[i1], distances[i2]
    pH1, pH2 = PH_VALUES[i1], PH_VALUES[i2]

    ph_est = (pH1 * d2 + pH2 * d1) / (d1 + d2) if (d1 + d2) > 0 else float(pH1)

    # Print the estimated pH value to the terminal
    print(f"Estimated pH: {ph_est:.1f}")

    # =========================
    # OUTPUT
    # =========================

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base = original_filename or Path(image_path).stem
    img_out = output_dir / f"{Path(base).stem}_annotated.jpg"
    txt_out = output_dir / f"{Path(base).stem}_result.txt"

    # ---- draw reference ROIs
    for i, roi in enumerate(ref_rois):
        x, y, w, h = roi
        cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(
            img, f"{PH_VALUES[i]}",
            (x+10, y-10),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.3,
            (0, 255, 0),
            3
        )

    # ---- draw white normalization ROI like other color cards
    xw, yw, ww, hw = WHITE_ROI
    cv2.rectangle(img, (xw, yw), (xw+ww, yw+hw), (0, 255, 0), 2)
    cv2.putText(
        img,
        "white",
        (xw+10, yw-10),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.3,
        (0, 255, 0),
        3
    )

    # ---- draw strip ROI
    x, y, w, h = STRIP_ROI
    cv2.rectangle(img, (x, y), (x+w, y+h), (0, 0, 255), 2)

    cv2.putText(
        img,
        f"pH = {ph_est:.1f}",
        (400, 1000),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.5,
        (0, 0, 255),
        5
    )

    cv2.imwrite(str(img_out), img)

    # Calculate mean RGB for each color block
    ref_rgbs = [mean_bgr(img, roi) for roi in ref_rois]

    with open(txt_out, "w") as f:
        # Write estimated pH with one digit after decimal
        f.write(f"Estimated pH: {ph_est:.1f}\n\n")
        for pH, d, rgb in zip(PH_VALUES, distances, ref_rgbs):
            rgb_str = f"({rgb[2]:.0f}, {rgb[1]:.0f}, {rgb[0]:.0f})"  # Convert BGR to RGB order
            f.write(f"pH {pH:>2}: dE = {d:.2f}, RGB = {rgb_str}\n")

    return {
        "ph": float(ph_est),
        # "distances": distances.tolist(),
        # "annotated_image": str(img_out),
        # "result_file": str(txt_out),
    }