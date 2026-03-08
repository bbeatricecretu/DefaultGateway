"""
mock_snapshot4.py – Snapshot4 Mock-Data Adapter
=================================================
Loads ALL available AI-measured data from snapshots4#2 and exposes it in
the exact shape the AeroVision Engine expects for ``_get_payloads()``.

Data sources (combined, ordered chronologically)
-------------------------------------------------
Detection CSVs – sessions 16:42, 17:55, 20:42  (20 frames)
    Per-snapshot person/bag counts per camera.  Flow rate is estimated
    from inter-frame queue deltas within the same session.

snapshots4#2/snapshots4/kpis.jsonl – session 21:10  (32 frames)
    Full KPI records keyed by (snapshot_num, timestamp_s).  Each unique
    pair is a separate frame, preserving all intra-snapshot measurements.

Total: 52 frames across four recording sessions.

Field mapping  (kpis.jsonl → engine payload)
--------------------------------------------
    kpis field              engine payload field
    ──────────────────────  ────────────────────
    queue_size              queue_size
    flow_rate_per_min       flow_rate   (clamped >= 0.1)
    avg_baggage_per_pax     avg_baggage
    total_specials          special_items

    CSV-derived frames use:
    person count            queue_size
    inter-frame delta/dt    flow_rate   (clamped >= 0.1)
    bags / persons          avg_baggage
    special_type count      special_items

Usage
-----
    from mock_snapshot4 import get_snapshot_payload, get_all_snapshots, SCENE_ANALYSIS

    payload = get_snapshot_payload()          # cycling
    payload = get_snapshot_payload(index=3)   # pinned
    frames  = get_all_snapshots()
"""

from __future__ import annotations

import csv
import glob
import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE       = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR   = os.path.join(_HERE, "snapshots4#2", "snapshots4")
_KPIS_PATH  = os.path.join(_DATA_DIR, "kpis.jsonl")
_SCENE_PATH = os.path.join(_HERE, "message (1).txt")
_ALERTS_PATH = os.path.join(_HERE, "ALERTS.txt")

# Cameras that map to individual counters (TERMINAL is the aggregate, skip it)
COUNTER_CAMERAS: frozenset = frozenset(
    {"Gate A", "Security", "Arrivals Hall", "Departures"}
)

# Human-readable counter types keyed by camera name
COUNTER_TYPES: Dict[str, str] = {
    "Gate A":        "Gate",
    "Security":      "Checkpoint",
    "Arrivals Hall": "Arrivals",
    "Departures":    "Departures",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_kpis() -> Tuple[List[Dict[str, Dict[str, Any]]], List[Optional[str]]]:
    """
    Parse kpis.jsonl into frames keyed by (snapshot_num, timestamp_s).

    Every unique (snapshot_num, timestamp_s) pair is treated as a
    separate frame, preserving all 32 distinct AI measurements instead
    of collapsing them to 15 by snapshot_num alone.

    Returns:
        Tuple of (frames, image_filenames), both ordered by
        (snapshot_num, timestamp_s).  image_filenames[i] is the
        corresponding JPG basename or None if no file found.
    """
    # Build snapshot_num → JPG filename for the 211 (21:10) session
    snap_images: Dict[int, str] = {}
    for fpath in glob.glob(os.path.join(_DATA_DIR, "*211*_????.jpg")):
        bn = os.path.basename(fpath)
        parts = bn.replace(".jpg", "").split("_")
        if len(parts) >= 4:
            try:
                snap_images[int(parts[3])] = bn
            except (ValueError, IndexError):
                pass

    groups: Dict[Tuple[int, float], Dict[str, Dict[str, Any]]] = {}

    with open(_KPIS_PATH, "r") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue

            camera = rec.get("camera", "")
            if camera not in COUNTER_CAMERAS:
                continue

            key: Tuple[int, float] = (
                int(rec["snapshot_num"]),
                round(float(rec["timestamp_s"]), 3),
            )
            if key not in groups:
                groups[key] = {}

            flow = max(float(rec.get("flow_rate_per_min", 1.0)), 0.1)
            groups[key][camera] = {
                "queue_size":    int(rec["queue_size"]),
                "flow_rate":     flow,
                "avg_baggage":   float(rec.get("avg_baggage_per_pax", 0.0)),
                "special_items": int(rec.get("total_specials", 0)),
            }

    sorted_keys = [
        k for k in sorted(groups.keys())
        if COUNTER_CAMERAS.issubset(groups[k].keys())
    ]
    frames = [groups[k] for k in sorted_keys]
    images: List[Optional[str]] = [snap_images.get(k[0]) for k in sorted_keys]
    return frames, images


def _load_csv_frames() -> Tuple[List[Dict[str, Dict[str, Any]]], List[Optional[str]]]:
    """
    Derive payload frames from detection CSVs for sessions that pre-date
    kpis.jsonl (16:42, 17:55, 20:42 sessions – 20 files).

    queue_size   = person count per camera in that snapshot
    flow_rate    = |delta_queue| / delta_t_minutes between adjacent frames
                   in the same session; first frame of each session uses
                   queue_size * 0.5 pax/min (clamped >= 0.1)
    avg_baggage  = bag count / max(person count, 1)
    special_items = rows with a non-empty special_type field

    Returns:
        Tuple of (frames, image_filenames).  image_filenames[i] is the
        JPG basename derived from the source CSV, or None if absent.
    """
    pattern = os.path.join(_DATA_DIR, "*_detections.csv")
    # Only sessions whose wall-clock hour prefix is NOT 211 (that's the kpis session)
    csv_files = sorted(
        f for f in glob.glob(pattern)
        if "_211" not in os.path.basename(f)
    )

    # Group by wall-clock session id (3rd underscore-split token, e.g. "164213")
    sessions: Dict[str, List[str]] = defaultdict(list)
    for path in csv_files:
        session_id = os.path.basename(path).split("_")[2]
        sessions[session_id].append(path)

    result: List[Dict[str, Dict[str, Any]]] = []
    images: List[Optional[str]] = []

    for session_id, paths in sorted(sessions.items()):
        prev_ts: Optional[float] = None
        prev_counts: Optional[Dict[str, int]] = None

        for path in sorted(paths):
            by_cam: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"persons": 0, "bags": 0, "specials": 0}
            )
            snapshot_ts: float = 0.0

            with open(path, newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    cam = row.get("camera", "").strip()
                    if cam not in COUNTER_CAMERAS:
                        continue
                    try:
                        snapshot_ts = float(row.get("timestamp_s", 0))
                    except ValueError:
                        pass
                    t = row.get("type", "").strip().lower()
                    if t == "person":
                        by_cam[cam]["persons"] += 1
                    elif t in ("bag", "luggage", "suitcase", "backpack"):
                        by_cam[cam]["bags"] += 1
                    if row.get("special_type", "").strip():
                        by_cam[cam]["specials"] += 1

            if not COUNTER_CAMERAS.issubset(by_cam.keys()):
                prev_ts = snapshot_ts
                prev_counts = None
                continue

            dt_min = ((snapshot_ts - prev_ts) / 60.0) if prev_ts is not None else None

            payload: Dict[str, Dict[str, Any]] = {}
            for cam in COUNTER_CAMERAS:
                d = by_cam[cam]
                q = d["persons"]

                if dt_min and dt_min > 0 and prev_counts is not None:
                    delta_q = abs(q - prev_counts.get(cam, q))
                    flow = max(delta_q / dt_min, 0.1)
                else:
                    flow = max(q * 0.5, 0.1)

                payload[cam] = {
                    "queue_size":    q,
                    "flow_rate":     round(flow, 2),
                    "avg_baggage":   round(d["bags"] / max(q, 1), 2),
                    "special_items": d["specials"],
                }

            result.append(payload)
            # Derive image filename: strip _detections.csv → .jpg
            img_base = os.path.basename(path).replace("_detections.csv", "")
            img_name = img_base + ".jpg"
            images.append(
                img_name
                if os.path.exists(os.path.join(_DATA_DIR, img_name))
                else None
            )
            prev_ts = snapshot_ts
            prev_counts = {cam: by_cam[cam]["persons"] for cam in COUNTER_CAMERAS}

    return result, images


def _load_alerts() -> List[List[Dict[str, Any]]]:
    """
    Load per-frame alert CSVs.

    Matches each frame to its corresponding ``*_alerts.csv`` using the same
    basename-to-image matching logic used for JPGs.  Frames without an alert
    file get an empty list.

    Alert record shape::

        {
          camera, severity, risk_score, queue_pressure, flow_degradation,
          clearance_delay, baggage_load, queue_trend, flow_trend,
          time_to_breach_s, top_action, explanation
        }
    """
    def _read_csv_alerts(base: str) -> List[Dict[str, Any]]:
        path = os.path.join(_DATA_DIR, base + "_alerts.csv")
        if not os.path.exists(path):
            return []
        out = []
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("camera", "").strip() in COUNTER_CAMERAS:
                    try:
                        out.append({
                            "camera":          row["camera"].strip(),
                            "severity":        row.get("severity", "").strip(),
                            "risk_score":      float(row.get("risk_score", 0) or 0),
                            "queue_pressure":  float(row.get("queue_pressure", 0) or 0),
                            "flow_degradation":float(row.get("flow_degradation", 0) or 0),
                            "time_to_breach_s":float(row.get("time_to_breach_s", 0) or 0),
                            "top_action":      row.get("top_action", "").strip(),
                            "explanation":     row.get("explanation", "").strip(),
                        })
                    except (ValueError, KeyError):
                        pass
        return out

    result: List[List[Dict[str, Any]]] = []
    for img in _FRAME_IMAGES:
        if img:
            base = img.replace(".jpg", "")
            result.append(_read_csv_alerts(base))
        else:
            result.append([])
    return result


# ---------------------------------------------------------------------------
# ALERTS.txt rich AI analysis loader
# ---------------------------------------------------------------------------

_PRIORITY_TO_SEVERITY = {"CRITICAL": "RED", "HIGH": "AMBER", "MEDIUM": "GREEN"}

_ALERT_TYPE_TO_CAMERA = {
    "security": "Security",
    "boarding": "Departures",
    "congestion": "Security",
    "staffing": "Gate A",
    "delay": "Security",
}

def _load_alerts_txt() -> List[List[Dict[str, Any]]]:
    """
    Load the rich AI analysis from ALERTS.txt and transform each frame's
    ``alerts`` list into the standard frontend format::

        { camera, severity, risk_score, explanation, top_action,
          queue_pressure, flow_degradation, time_to_breach_s }

    Also populates ``_ALERTS_TXT_OPTIMIZATIONS`` for use as mock optimizations.
    """
    global _ALERTS_TXT_OPTIMIZATIONS
    if not os.path.exists(_ALERTS_PATH):
        _ALERTS_TXT_OPTIMIZATIONS = []
        return []
    try:
        with open(_ALERTS_PATH, "r") as fh:
            raw = json.load(fh)
    except Exception:
        _ALERTS_TXT_OPTIMIZATIONS = []
        return []

    frames_alerts: List[List[Dict[str, Any]]] = []
    frames_opts: List[List[Dict[str, Any]]] = []

    for entry in raw:
        alerts = entry.get("alerts", [])
        frame: List[Dict[str, Any]] = []
        for a in alerts:
            sev = _PRIORITY_TO_SEVERITY.get(a.get("priority", ""), "GREEN")
            cam = _ALERT_TYPE_TO_CAMERA.get(a.get("type", ""), "Security")
            # Build risk_score from priority
            risk_map = {"CRITICAL": 85.0, "HIGH": 60.0, "MEDIUM": 35.0}
            risk = risk_map.get(a.get("priority", ""), 30.0)
            # Extract supporting KPI numbers for context
            kpis = a.get("supporting_kpis", {})
            qp = kpis.get("security_queue_size", 0) / 25.0 if kpis.get("security_queue_size") else 0
            fd = 0.3 if sev == "RED" else 0.15 if sev == "AMBER" else 0.0
            ttb = 600 if sev == "RED" else 1200 if sev == "AMBER" else 0

            affected = ", ".join(a.get("affected_flights", []))
            explanation = a.get("message", "")
            if affected:
                explanation += f" [Flights: {affected}]"

            frame.append({
                "camera":           cam,
                "severity":         sev,
                "risk_score":       risk,
                "queue_pressure":   qp,
                "flow_degradation": fd,
                "time_to_breach_s": ttb,
                "top_action":       a.get("recommended_action", ""),
                "explanation":      explanation,
            })
        frames_alerts.append(frame)

        # Build optimizations from resource_recommendations
        opts: List[Dict[str, Any]] = []
        recs = entry.get("resource_recommendations", {})
        for staff_rec in recs.get("staff_reallocation", []):
            opts.append({
                "action": "Reallocate Staff",
                "details": staff_rec,
                "estimated_impact": 25,
                "actionable": True,
            })
        for lane_rec in recs.get("lane_adjustments", []):
            opts.append({
                "action": "Open Relief Counter",
                "details": lane_rec,
                "estimated_impact": 30,
                "actionable": True,
            })
        frames_opts.append(opts)

    _ALERTS_TXT_OPTIMIZATIONS = frames_opts
    return frames_alerts


_ALERTS_TXT_DATA: List[List[Dict[str, Any]]] = []  # loaded at init
_ALERTS_TXT_OPTIMIZATIONS: List[List[Dict[str, Any]]] = []  # loaded at init


def _load_heatmap_index() -> List[Dict[str, str]]:
    """
    Build per-frame dict mapping camera name → heatmap JPG basename.

    Only frames whose image basename has a matching set of heatmaps in
    ``snapshots4/heatmaps/`` get a non-empty dict.
    """
    heatmap_dir = os.path.join(_DATA_DIR, "heatmaps")
    result: List[Dict[str, str]] = []
    for img in _FRAME_IMAGES:
        cams: Dict[str, str] = {}
        if img:
            base = img.replace(".jpg", "")
            for cam_key, cam_label in [
                ("Gate_A",       "Gate A"),
                ("Security",     "Security"),
                ("Arrivals_Hall","Arrivals Hall"),
                ("Departures",   "Departures"),
            ]:
                fname = f"{base}_heatmap_{cam_key}.jpg"
                if os.path.exists(os.path.join(heatmap_dir, fname)):
                    cams[cam_label] = fname
        result.append(cams)
    return result


def _load_scene_analysis() -> Dict[str, Any]:
    """
    Load the AI scene analysis block from ``message (1).txt``.

    Returns:
        Parsed dict, or an empty dict on any parse/IO error.
    """
    try:
        with open(_SCENE_PATH, "r") as fh:
            content = fh.read()
        json_block = content.split("=====")[0].strip()
        return json.loads(json_block)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Module-level singletons (loaded once at import time)
# ---------------------------------------------------------------------------

# CSV-derived frames first (chronologically earlier sessions), then kpis frames
_csv_frames, _csv_images     = _load_csv_frames()
_kpis_frames, _kpis_images   = _load_kpis()
_FRAMES: List[Dict[str, Dict[str, Any]]] = _csv_frames + _kpis_frames
_FRAME_IMAGES: List[Optional[str]]       = _csv_images + _kpis_images

# Per-frame alert records and heatmap filenames (built after _FRAME_IMAGES is ready)
_FRAME_ALERTS:   List[List[Dict[str, Any]]] = _load_alerts()
_FRAME_HEATMAPS: List[Dict[str, str]]       = _load_heatmap_index()

# Total number of distinct frames available
SNAPSHOT_COUNT: int = len(_FRAMES)

# AI scene analysis (crowd density, risk level, recommendations, …)
SCENE_ANALYSIS: Dict[str, Any] = _load_scene_analysis()

# Rich ALERTS.txt data (loaded after frames)
_ALERTS_TXT_DATA = _load_alerts_txt()

# Cycling index – incremented each time get_snapshot_payload() is called
# without an explicit index argument.
_cycle_index: int = 0


# ---------------------------------------------------------------------------
# Showcase overrides – high-disruption frames for demonstration purposes
# ---------------------------------------------------------------------------
# Frames 25, 26, 27 are patched with synthetic critical-disruption data
# (security meltdown + gate overload) to provide a compelling live demo.
# The engine still processes the raw counter data and will compute High risk.

_SHOWCASE_OVERRIDES: Dict[int, Dict[str, Any]] = {
    25: {
        "counters": {
            "Gate A":        {"queue_size": 28, "flow_rate": 0.30, "avg_baggage": 2.1, "special_items": 3},
            "Security":      {"queue_size": 35, "flow_rate": 0.20, "avg_baggage": 1.9, "special_items": 5},
            "Arrivals Hall": {"queue_size": 11, "flow_rate": 1.80, "avg_baggage": 1.4, "special_items": 1},
            "Departures":    {"queue_size": 22, "flow_rate": 0.50, "avg_baggage": 1.6, "special_items": 2},
        },
        "alerts": [
            {"camera": "Security",      "severity": "RED",   "risk_score": 91.0,
             "queue_pressure": 0.88, "flow_degradation": 0.83, "time_to_breach_s": 185,
             "top_action": "Deploy additional security officer and open all available lanes immediately.",
             "explanation": "Security checkpoint has reached critical queue density. Flow degradation is severe — queue is not clearing at a safe rate."},
            {"camera": "Gate A",        "severity": "RED",   "risk_score": 77.0,
             "queue_pressure": 0.73, "flow_degradation": 0.67, "time_to_breach_s": 425,
             "top_action": "Open relief gate and redirect overflow passengers via Gate A2.",
             "explanation": "Gate A boarding queue is critically overstuffed. Multiple departures are now at risk of missed windows."},
            {"camera": "Departures",    "severity": "AMBER", "risk_score": 53.0,
             "queue_pressure": 0.50, "flow_degradation": 0.44, "time_to_breach_s": 910,
             "top_action": "Open second check-in position at the departures hall.",
             "explanation": "Departures queue building steadily. Cascade into gate areas expected within 15 minutes if not addressed."},
            {"camera": "Arrivals Hall", "severity": "GREEN", "risk_score": 14.0,
             "queue_pressure": 0.12, "flow_degradation": 0.08, "time_to_breach_s": 9999,
             "top_action": "No action needed.",
             "explanation": "Arrivals Hall is operating within normal parameters. No intervention required."},
        ],
    },
    26: {
        "counters": {
            "Gate A":        {"queue_size": 34, "flow_rate": 0.18, "avg_baggage": 2.5, "special_items": 5},
            "Security":      {"queue_size": 41, "flow_rate": 0.12, "avg_baggage": 2.0, "special_items": 7},
            "Arrivals Hall": {"queue_size": 10, "flow_rate": 2.10, "avg_baggage": 1.3, "special_items": 0},
            "Departures":    {"queue_size": 29, "flow_rate": 0.30, "avg_baggage": 1.8, "special_items": 3},
        },
        "alerts": [
            {"camera": "Security",      "severity": "RED",   "risk_score": 97.0,
             "queue_pressure": 0.95, "flow_degradation": 0.91, "time_to_breach_s": 88,
             "top_action": "EVACUATE non-essential staff and open ALL lanes immediately. Supervisor to post at checkpoint entrance.",
             "explanation": "CRITICAL: Security checkpoint has exceeded maximum safe operating capacity. Breach of crowd safety limit is imminent."},
            {"camera": "Gate A",        "severity": "RED",   "risk_score": 84.0,
             "queue_pressure": 0.80, "flow_degradation": 0.75, "time_to_breach_s": 305,
             "top_action": "Emergency reallocation: redirect DL789 boarding to Gate B overflow area.",
             "explanation": "Gate A is at saturation. DL789 boarding cannot proceed safely. Two additional departures are at risk within 30 minutes."},
            {"camera": "Departures",    "severity": "RED",   "risk_score": 65.0,
             "queue_pressure": 0.62, "flow_degradation": 0.57, "time_to_breach_s": 605,
             "top_action": "Activate passive queue management — deploy lane dividers and call in two additional agents.",
             "explanation": "Departures hall has crossed the amber threshold. Crowd density is approaching the safety limit in zone B3."},
            {"camera": "Arrivals Hall", "severity": "GREEN", "risk_score": 17.0,
             "queue_pressure": 0.15, "flow_degradation": 0.11, "time_to_breach_s": 9999,
             "top_action": "No action needed.",
             "explanation": "Arrivals Hall operating within normal parameters. Clearance rate stable."},
        ],
    },
    27: {
        "counters": {
            "Gate A":        {"queue_size": 29, "flow_rate": 0.35, "avg_baggage": 2.2, "special_items": 3},
            "Security":      {"queue_size": 33, "flow_rate": 0.28, "avg_baggage": 1.85, "special_items": 5},
            "Arrivals Hall": {"queue_size": 14, "flow_rate": 1.50, "avg_baggage": 1.4,  "special_items": 1},
            "Departures":    {"queue_size": 24, "flow_rate": 0.60, "avg_baggage": 1.7,  "special_items": 2},
        },
        "alerts": [
            {"camera": "Security",      "severity": "RED",   "risk_score": 85.0,
             "queue_pressure": 0.82, "flow_degradation": 0.77, "time_to_breach_s": 245,
             "top_action": "Maintain all lanes open — supervisor to conduct 3-minute check cycles.",
             "explanation": "Security queue reducing but still in critical zone. Sustained intervention required — any relaxation risks a secondary surge."},
            {"camera": "Gate A",        "severity": "AMBER", "risk_score": 61.0,
             "queue_pressure": 0.58, "flow_degradation": 0.52, "time_to_breach_s": 545,
             "top_action": "Continue boarding prioritisation for special-assist passengers.",
             "explanation": "Gate A queue is improving. Boarding process has partially stabilised. Maintain elevated staffing for the next 20 minutes."},
            {"camera": "Departures",    "severity": "AMBER", "risk_score": 47.0,
             "queue_pressure": 0.44, "flow_degradation": 0.40, "time_to_breach_s": 1210,
             "top_action": "Monitor and report back in 10 minutes.",
             "explanation": "Departures recovering. Queue density reduced 17% from peak. Stand-down may be issued if positive trend continues."},
            {"camera": "Arrivals Hall", "severity": "GREEN", "risk_score": 20.0,
             "queue_pressure": 0.18, "flow_degradation": 0.13, "time_to_breach_s": 9999,
             "top_action": "No action needed.",
             "explanation": "Arrivals Hall continues to operate smoothly. No intervention needed."},
        ],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_snapshot_payload(index: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """
    Return a counter-keyed AI payload for one frame.

    Args:
        index: 0-based position into the sorted frame list.
               If ``None``, the next frame in the cycle is returned and
               the internal counter is advanced (wrap-around).

    Returns:
        ``{camera_name: {queue_size, flow_rate, avg_baggage, special_items}}``
        or an empty dict if no frames were loaded.
    """
    global _cycle_index

    if not _FRAMES:
        return {}

    if index is None:
        idx = _cycle_index % SNAPSHOT_COUNT
        _cycle_index += 1
    else:
        idx = int(index) % SNAPSHOT_COUNT

    override = _SHOWCASE_OVERRIDES.get(idx)
    if override:
        return dict(override["counters"])
    return dict(_FRAMES[idx])


def get_frame_image(index: int) -> Optional[str]:
    """
    Return the JPG basename for the given frame index, or None.

    The returned filename can be served via ``GET /api/snapshot_image/<filename>``.
    """
    if not _FRAME_IMAGES:
        return None
    return _FRAME_IMAGES[int(index) % len(_FRAME_IMAGES)]


def get_frame_alerts(index: int) -> List[Dict[str, Any]]:
    """Return the list of alert records for the given frame index (may be empty)."""
    idx = int(index) % SNAPSHOT_COUNT
    override = _SHOWCASE_OVERRIDES.get(idx)
    if override:
        return list(override["alerts"])
    if not _FRAME_ALERTS:
        pass  # fall through to ALERTS.txt
    else:
        csv_alerts = _FRAME_ALERTS[idx % len(_FRAME_ALERTS)]
        if csv_alerts:
            return csv_alerts
    # Fallback: cycle through ALERTS.txt entries
    if _ALERTS_TXT_DATA:
        return _ALERTS_TXT_DATA[idx % len(_ALERTS_TXT_DATA)]
    return []


def get_frame_optimizations(index: int) -> List[Dict[str, Any]]:
    """Return mock optimizations from ALERTS.txt for the given frame index."""
    if not _ALERTS_TXT_OPTIMIZATIONS:
        return []
    idx = int(index) % len(_ALERTS_TXT_OPTIMIZATIONS)
    return _ALERTS_TXT_OPTIMIZATIONS[idx]


def get_frame_heatmaps(index: int) -> Dict[str, str]:
    """Return {camera_name: heatmap_filename} for the given frame index."""
    if not _FRAME_HEATMAPS:
        return {}
    return _FRAME_HEATMAPS[int(index) % len(_FRAME_HEATMAPS)]


def get_all_snapshots() -> List[Dict[str, Any]]:
    """Return metadata + payload for every loaded frame."""
    return [
        {"index": i, "counters": frame}
        for i, frame in enumerate(_FRAMES)
    ]


def get_scene_analysis() -> Dict[str, Any]:
    """Return the loaded AI scene analysis dict (may be empty if file missing)."""
    return SCENE_ANALYSIS
