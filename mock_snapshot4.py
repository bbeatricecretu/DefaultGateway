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

def _load_kpis() -> List[Dict[str, Dict[str, Any]]]:
    """
    Parse kpis.jsonl into frames keyed by (snapshot_num, timestamp_s).

    Every unique (snapshot_num, timestamp_s) pair is treated as a
    separate frame, preserving all 32 distinct AI measurements instead
    of collapsing them to 15 by snapshot_num alone.

    Returns:
        List of counter-keyed payload dicts, ordered by
        (snapshot_num, timestamp_s).
    """
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

    return [
        groups[k]
        for k in sorted(groups.keys())
        if COUNTER_CAMERAS.issubset(groups[k].keys())
    ]


def _load_csv_frames() -> List[Dict[str, Dict[str, Any]]]:
    """
    Derive payload frames from detection CSVs for sessions that pre-date
    kpis.jsonl (16:42, 17:55, 20:42 sessions – 20 files).

    queue_size   = person count per camera in that snapshot
    flow_rate    = |delta_queue| / delta_t_minutes between adjacent frames
                   in the same session; first frame of each session uses
                   queue_size * 0.5 pax/min (clamped >= 0.1)
    avg_baggage  = bag count / max(person count, 1)
    special_items = rows with a non-empty special_type field
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
            prev_ts = snapshot_ts
            prev_counts = {cam: by_cam[cam]["persons"] for cam in COUNTER_CAMERAS}

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
_FRAMES: List[Dict[str, Dict[str, Any]]] = _load_csv_frames() + _load_kpis()

# Total number of distinct frames available
SNAPSHOT_COUNT: int = len(_FRAMES)

# AI scene analysis (crowd density, risk level, recommendations, …)
SCENE_ANALYSIS: Dict[str, Any] = _load_scene_analysis()

# Cycling index – incremented each time get_snapshot_payload() is called
# without an explicit index argument.
_cycle_index: int = 0


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

    return dict(_FRAMES[idx])


def get_all_snapshots() -> List[Dict[str, Any]]:
    """Return metadata + payload for every loaded frame."""
    return [
        {"index": i, "counters": frame}
        for i, frame in enumerate(_FRAMES)
    ]


def get_scene_analysis() -> Dict[str, Any]:
    """Return the loaded AI scene analysis dict (may be empty if file missing)."""
    return SCENE_ANALYSIS
