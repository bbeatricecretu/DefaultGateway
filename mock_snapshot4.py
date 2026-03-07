"""
mock_snapshot4.py – Snapshot4 Mock-Data Adapter
=================================================
Loads the real AI-measured data produced by the snapshots4#2 session and
exposes it in the exact shape the AeroVision Engine expects for
``_get_payloads()``.

Data sources
------------
snapshots4#2/snapshots4/kpis.jsonl
    One JSON record per line.  Each record represents one camera's KPIs
    at a given moment in the video.  Records sharing the same
    ``snapshot_num`` are collapsed into a single frame (last value per
    camera wins), giving 15 distinct frames.

message (1).txt
    AI-generated scene analysis (crowd density, risk, contributing
    factors, recommended solutions) for the session as a whole.

Field mapping  (kpis.jsonl → engine payload)
--------------------------------------------
    kpis field              engine payload field
    ──────────────────────  ────────────────────
    queue_size              queue_size
    flow_rate_per_min       flow_rate   (clamped to ≥ 0.1 so Queue never
                                         receives a non-positive rate)
    avg_baggage_per_pax     avg_baggage
    total_specials          special_items

Usage
-----
    from mock_snapshot4 import get_snapshot_payload, get_all_snapshots, SCENE_ANALYSIS

    # Cycling (advances automatically on each call)
    payload = get_snapshot_payload()

    # Pinned to a specific index (0-based)
    payload = get_snapshot_payload(index=3)

    # All frames
    frames = get_all_snapshots()

    # Scene-level metadata
    risk = SCENE_ANALYSIS.get("gateway_congestion_prediction", {})
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_KPIS_PATH = os.path.join(_HERE, "snapshots4#2", "snapshots4", "kpis.jsonl")
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
    Parse kpis.jsonl into an ordered list of per-frame payload dicts.

    Deduplicates by ``snapshot_num`` only: multiple timestamp entries for
    the same snapshot (common in snapshots4#2) are collapsed into one
    frame by keeping the last value seen per camera.  Frames that don't
    contain data for all 4 counters are discarded.

    Returns:
        Ordered list of dicts shaped as::

            {
              "Gate A":        {queue_size, flow_rate, avg_baggage, special_items},
              "Security":      {…},
              "Arrivals Hall": {…},
              "Departures":    {…},
            }
    """
    # Accumulate per snapshot_num; last record for each camera wins.
    per_snap: Dict[int, Dict[str, Dict[str, Any]]] = {}

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

            snap_num: int = int(rec["snapshot_num"])
            if snap_num not in per_snap:
                per_snap[snap_num] = {}

            # Flow rate must be > 0 for Queue not to raise ValueError
            flow = max(float(rec.get("flow_rate_per_min", 1.0)), 0.1)

            per_snap[snap_num][camera] = {
                "queue_size":    int(rec["queue_size"]),
                "flow_rate":     flow,
                "avg_baggage":   float(rec.get("avg_baggage_per_pax", 0.0)),
                "special_items": int(rec.get("total_specials", 0)),
            }

    # Return only complete frames, ordered by snapshot_num
    complete = [
        per_snap[k]
        for k in sorted(per_snap.keys())
        if COUNTER_CAMERAS.issubset(per_snap[k].keys())
    ]
    return complete


def _load_scene_analysis() -> Dict[str, Any]:
    """
    Load the AI scene analysis block from ``message (1).txt``.

    The file contains a JSON object followed by an optional ``======`` separator.

    Returns:
        Parsed dict, or an empty dict on any parse/IO error.
    """
    try:
        with open(_SCENE_PATH, "r") as fh:
            content = fh.read()
        # Strip the trailing ===... separator line if present
        json_block = content.split("=====")[0].strip()
        return json.loads(json_block)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Module-level singletons (loaded once at import time)
# ---------------------------------------------------------------------------

_FRAMES: List[Dict[str, Dict[str, Any]]] = _load_kpis()

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
               If ``None``, the next frame in the cycle is returned and the
               internal counter is advanced (wrap-around).

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
    """
    Return metadata + payload for every loaded frame.

    Each item in the returned list has the shape::

        {
          "index":    <int>,          # 0-based position in the cycle
          "counters": {               # counter-keyed payload
            "Gate A":        {…},
            "Security":      {…},
            "Arrivals Hall": {…},
            "Departures":    {…},
          }
        }
    """
    return [
        {"index": i, "counters": frame}
        for i, frame in enumerate(_FRAMES)
    ]


def get_scene_analysis() -> Dict[str, Any]:
    """Return the loaded AI scene analysis dict (may be empty if file missing)."""
    return SCENE_ANALYSIS
