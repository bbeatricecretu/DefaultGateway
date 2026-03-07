"""
extract_zones.py – OpenCV color-zone extractor for the airport floor plan.

Usage:
    python extract_zones.py floor_plan.png
    python extract_zones.py          # auto-detects any PNG/JPG in current dir

Outputs:
    static/floor_plan.png   – copy of the image for the web app
    static/zones.json       – zone polygons normalised to [0,1] range
"""

import sys, os, json, shutil
import cv2
import numpy as np

# ── Color definitions (HSV ranges) ────────────────────────────────────────
# Each entry:  id, display_name, hex_color, lower_HSV, upper_HSV
ZONES = [
    {
        "id":    "green",
        "name":  "Gate A / Main Corridor",
        "color": "#22c55e",
        "lower": np.array([62,  70,  50]),
        "upper": np.array([78, 255, 255]),
    },
    {
        "id":    "blue",
        "name":  "Departures Lounge",
        "color": "#818cf8",
        "lower": np.array([110, 25,  50]),
        "upper": np.array([130, 255, 255]),
    },
    {
        "id":    "yellow",
        "name":  "Security / Check-in",
        "color": "#eab308",
        "lower": np.array([88,  60, 100]),
        "upper": np.array([102, 255, 255]),
    },
    {
        "id":    "orange",
        "name":  "Arrivals Hall",
        "color": "#f97316",
        "lower": np.array([0,   80, 150]),
        "upper": np.array([15,  255, 255]),
    },
    {
        "id":    "cyan",
        "name":  "Baggage / Transit",
        "color": "#38bdf8",
        "lower": np.array([20,  70, 150]),
        "upper": np.array([32,  255, 255]),
    },
]

# ── Simplification: target polygon vertex count ───────────────────────────
EPSILON_FACTOR = 0.008   # fraction of arc length → higher = fewer points


def find_image(arg):
    if arg and os.path.isfile(arg):
        return arg
    for f in os.listdir("."):
        if f.lower().endswith((".png", ".jpg", ".jpeg")) and "floor" in f.lower():
            return f
    for f in os.listdir("."):
        if f.lower().endswith((".png", ".jpg", ".jpeg")):
            return f
    raise FileNotFoundError("No floor plan image found. Pass path as argument.")


def extract(image_path: str) -> dict:
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    h, w = img.shape[:2]
    hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    out = {"image_w": w, "image_h": h, "zones": []}

    for zone in ZONES:
        mask = cv2.inRange(hsv, zone["lower"], zone["upper"])

        # Clean up small noise
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
        mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=2)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Keep only significant contours (> 0.05% of image area)
        min_area = w * h * 0.0005
        polys = []
        for cnt in contours:
            if cv2.contourArea(cnt) < min_area:
                continue
            eps  = EPSILON_FACTOR * cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, eps, True)
            # Normalise to [0,1]
            pts = [[round(p[0][0] / w, 5), round(p[0][1] / h, 5)]
                   for p in approx]
            polys.append({"points": pts, "area": round(cv2.contourArea(cnt) / (w * h), 6)})

        # Sort largest polygon first
        polys.sort(key=lambda x: x["area"], reverse=True)

        out["zones"].append({
            "id":       zone["id"],
            "name":     zone["name"],
            "color":    zone["color"],
            "polygons": polys,
        })
        pixel_count = int(np.sum(mask > 0))
        print(f"  {zone['id']:8s}  pixels={pixel_count:7d}  polygons={len(polys)}")

    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    image_path = find_image(arg)
    print(f"Processing: {image_path}")

    data = extract(image_path)

    # Copy image to static/
    os.makedirs("static", exist_ok=True)
    dest_img = os.path.join("static", "floor_plan.png")
    shutil.copy2(image_path, dest_img)
    print(f"\nImage   → {dest_img}")

    # Write zones JSON
    dest_json = os.path.join("static", "zones.json")
    with open(dest_json, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Zones   → {dest_json}")
    print(f"\nImage size: {data['image_w']} × {data['image_h']} px")
    total_polys = sum(len(z["polygons"]) for z in data["zones"])
    print(f"Total polygons extracted: {total_polys}")


if __name__ == "__main__":
    main()
