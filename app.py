import os
import time
from pathlib import Path

from flask import Flask, render_template, jsonify, request, url_for
from werkzeug.utils import secure_filename
import requests

import numpy as np
import cv2
from ultralytics import YOLO

# ---------------------------
# Flask app setup
# ---------------------------
app = Flask(__name__)

# Folders
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# File validation
ALLOWED_EXTS = {"jpg", "jpeg", "png", "bmp"}
ALLOWED_MIME_TO_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/bmp": "bmp"}
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024  # 5 MB cap

# ---------------------------
# Model load (once, at startup)
# ---------------------------
MODEL_PATH = MODELS_DIR / "best.pt"
CLASSES_PATH = MODELS_DIR / "classes.txt"

assert MODEL_PATH.exists(), f"Model file not found: {MODEL_PATH}"
model = YOLO(str(MODEL_PATH))

# Load class names if provided (one per line). YOLO also has names internally,
# but we’ll prefer your classes.txt if present.
if CLASSES_PATH.exists():
    with open(CLASSES_PATH, "r", encoding="utf-8") as f:
        CUSTOM_NAMES = [line.strip() for line in f if line.strip()]
else:
    CUSTOM_NAMES = None  # fallback to model.names

# ---------------------------
# Helpers
# ---------------------------
def allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTS

def unique_name(base: str, ext: str) -> str:
    return f"{base}_{int(time.time())}{ext}"

def run_yolo(image_path: Path, conf: float = 0.25, iou: float = 0.45):
    """
    Run YOLO on the given image path.
    Returns: detections (list of dicts) and path to an annotated image.
    """
    results = model.predict(
        source=str(image_path),
        conf=conf,
        iou=iou,
        verbose=False
    )

    # Use the first result
    res = results[0]

    # Build a plain list of detections
    names = CUSTOM_NAMES if CUSTOM_NAMES else res.names
    dets = []
    if res.boxes is not None and len(res.boxes) > 0:
        for b in res.boxes:
            cls_id = int(b.cls[0])
            conf_v = float(b.conf[0])
            x1, y1, x2, y2 = map(lambda x: float(x), b.xyxy[0])
            dets.append({
                "class_id": cls_id,
                "class_name": names[cls_id] if names and cls_id < len(names) else str(cls_id),
                "confidence": round(conf_v, 4),
                "box_xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]
            })

    # Get an annotated image as a NumPy array (BGR) from Ultralytics
    annotated_bgr = res.plot()  # already BGR, ready for cv2.imwrite

    # Save alongside the original with a suffix
    orig_name = image_path.stem
    ext = image_path.suffix  # includes dot
    annotated_name = f"{orig_name}_annotated{ext}"
    annotated_path = image_path.parent / annotated_name

    cv2.imwrite(str(annotated_path), annotated_bgr)

    return dets, annotated_path

# ---------------------------
# Routes
# ---------------------------
@app.get("/health")
def health():
    return jsonify(status="ok", version="v1")

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/predict")
def predict():
    """
    Accept either:
      - a file upload via <input type="file" name="image">
      - an image URL via <input type="url" name="image_url">
    Save image to static/uploads, run YOLO, save annotated image, and render.
    """
    file = request.files.get("image")
    image_url_field = (request.form.get("image_url") or "").strip()

    # ---------- A) File upload path ----------
    if file and file.filename:
        if not allowed(file.filename):
            return render_template("index.html", detections=[{"error": "Unsupported file type"}], image_url=None)

        fname = secure_filename(file.filename)
        base, ext = os.path.splitext(fname)
        unique = unique_name(base, ext)
        upload_path = UPLOAD_DIR / unique
        file.save(str(upload_path))

        # Run YOLO
        detections, annotated_path = run_yolo(upload_path)

        # Return annotated image
        img_url = url_for("static", filename=f"uploads/{annotated_path.name}")
        return render_template("index.html", detections=detections, image_url=img_url)

    # ---------- B) URL paste path ----------
    if image_url_field:
        if not (image_url_field.startswith("http://") or image_url_field.startswith("https://")):
            return render_template("index.html", detections=[{"error": "Only http/https URLs are allowed"}], image_url=None)
        try:
            with requests.get(image_url_field, stream=True, timeout=6) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if ctype not in ALLOWED_MIME_TO_EXT:
                    return render_template("index.html", detections=[{"error": f"URL is not an image (got {ctype})"}], image_url=None)

                ext = "." + ALLOWED_MIME_TO_EXT[ctype]
                unique = unique_name("url", ext)
                upload_path = UPLOAD_DIR / unique

                total = 0
                with open(upload_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            f.close()
                            os.remove(upload_path)
                            return render_template("index.html", detections=[{"error": "Image too large (>5MB)"}], image_url=None)
                        f.write(chunk)

                # Run YOLO
                detections, annotated_path = run_yolo(upload_path)

                img_url = url_for("static", filename=f"uploads/{annotated_path.name}")
                return render_template("index.html", detections=detections, image_url=img_url)

        except requests.exceptions.RequestException as e:
            return render_template("index.html", detections=[{"error": f"Failed to fetch URL: {str(e)}"}], image_url=None)

    # ---------- C) Neither file nor URL provided ----------
    return render_template("index.html", detections=[{"error": "Please upload a file or provide an image URL"}], image_url=None)

# ---------------------------
# Dev server entrypoint
# ---------------------------
if __name__ == "__main__":
    # Use port 8080 now so Docker uses the same later
    app.run(host="0.0.0.0", port=8080, debug=True)
