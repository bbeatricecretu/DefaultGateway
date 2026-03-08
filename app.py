"""
app.py – AeroVision Flask REST API
====================================
Wraps the AeroVision engine in a lightweight Flask server so any frontend
(Streamlit, React, Vue, etc.) can poll the dashboard data over HTTP.

Endpoint
--------
GET /api/dashboard
    Runs the full engine pipeline and returns a JSON ``DashboardDTO``
    whose shape is defined by the TypeScript interfaces in the frontend.

Response shape
--------------
    {
      "system_metrics": { … },
      "counters":        [ … ],
      "flights":         [ … ],
      "optimizations":   [ … ],
      "processing_errors": [ … ],
      "schedule":        { … }
    }

Usage
-----
    python app.py                          # default: localhost:5000, mock data
    DATA_SOURCE=http AI_VISION_URL=http://cam-api/snapshot python app.py

Environment variables
---------------------
    PORT            TCP port to listen on (default: 5000)
    HOST            Bind address (default: 0.0.0.0)
    DATA_SOURCE     "mock" | "http" | "websocket"  (default: "mock")
    AI_VISION_URL   Base URL for the AI surveillance system REST endpoint
    FLASK_ENV       "development" enables auto-reload and debug tracebacks
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict

import json
import os
import time

from flask import Flask, jsonify, render_template, Response, send_from_directory, stream_with_context
from flask_cors import CORS

from engine import Engine
from models import Counter, Flight
from scheduler import ScheduleManager
import mock_snapshot4
from src.api_client import RemoteAPIClient, start_shared_client, get_shared_client, stop_shared_client

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Allow all origins by default; tighten to a specific origin in production:
#   CORS(app, resources={r"/api/*": {"origins": "https://your-frontend.com"}})
CORS(app, resources={r"/api/*": {"origins": "*"}})


# ---------------------------------------------------------------------------
# Engine initialisation
# ---------------------------------------------------------------------------
# The engine is built once at startup and reused on every request.
# Its registered counters, flights, and schedule entries are stable across
# calls; only the AI payload data changes per request.

def _build_engine() -> Engine:
    """
    Initialise the AeroVision engine with counters, flights, and a
    ``ScheduleManager``.

    This mirrors the logic from ``main.build_engine()`` and is intentionally
    kept as a plain function so it is easy to swap out during testing.

    Returns:
        A fully configured :class:`~engine.Engine` ready to accept payloads.
    """
    engine = Engine()

    # ---- Counters (keyed by camera name to match snapshot4 mock data) --------
    for cam, cam_type in mock_snapshot4.COUNTER_TYPES.items():
        engine.add_counter(Counter(counter_id=cam, counter_type=cam_type))

    # ---- Flights ------------------------------------------------------------
    dl789 = Flight(
        flight_id="DL789",
        status="DEPARTS 45M",
        minutes_to_departure=45.0,
        expectation=(
            "JFK→LHR via Gate A7. Boeing 767-300ER. "
            "Storm system approaching LHR — possible delay or cancellation."
        ),
    )
    ua456 = Flight(
        flight_id="UA456",
        status="LANDED",
        minutes_to_departure=None,
        expectation=(
            "ORD inbound. Passengers arriving at Arrivals Hall — "
            "weather-related bunching expected; queue to peak in ~18 min."
        ),
    )
    ba112 = Flight(
        flight_id="BA112",
        status="DEPARTS 65M",
        minutes_to_departure=65.0,
        expectation=(
            "LGW→CDG via Gate C3. Airbus A319. "
            "De-icing delays at CDG — possible hold of 20–35 min."
        ),
    )
    ek205 = Flight(
        flight_id="EK205",
        status="DEPARTS 105M",
        minutes_to_departure=105.0,
        expectation=(
            "DXB inbound/outbound via Gate A3. Boeing 777-300ER. "
            "Strong crosswinds forecast — departure may push 30–45 min."
        ),
    )
    fr9032 = Flight(
        flight_id="FR9032",
        status="DEPARTS 25M",
        minutes_to_departure=25.0,
        expectation=(
            "STN→BCN via Gate D9. Boeing 737 MAX 8. "
            "Thunderstorm over Pyrenees — diversion to Valencia possible."
        ),
    )
    engine.add_flight(dl789)
    engine.add_flight(ua456)
    engine.add_flight(ba112)
    engine.add_flight(ek205)
    engine.add_flight(fr9032)

    # ---- Schedule -----------------------------------------------------------
    now = datetime.now()
    scheduler = ScheduleManager()

    # DL789: check-in open from 2 h ago, closes in 20 min → ACTIVE
    scheduler.register(
        flight_id="DL789",
        counter_ids=["Gate A", "Departures"],
        start_time=now - timedelta(hours=2),
        end_time=now + timedelta(minutes=20),
    )

    # UA456: landed, check-in closed 1 h ago → EXPIRED
    scheduler.register(
        flight_id="UA456",
        counter_ids=["Arrivals Hall"],
        start_time=now - timedelta(hours=5),
        end_time=now - timedelta(hours=1),
    )

    # BA112: check-in open, departs in 65 min → ACTIVE
    scheduler.register(
        flight_id="BA112",
        counter_ids=["Departures"],
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(minutes=50),
    )

    # EK205: check-in open, departs in 105 min → ACTIVE
    scheduler.register(
        flight_id="EK205",
        counter_ids=["Gate A"],
        start_time=now - timedelta(minutes=30),
        end_time=now + timedelta(minutes=90),
    )

    # FR9032: check-in closing soon, departs in 25 min → ACTIVE (urgent)
    scheduler.register(
        flight_id="FR9032",
        counter_ids=["Departures", "Security"],
        start_time=now - timedelta(hours=3),
        end_time=now + timedelta(minutes=10),
    )

    engine.set_scheduler(scheduler)
    return engine


# Build the engine once at module load time.
_engine: Engine = _build_engine()


# ---------------------------------------------------------------------------
# Live API state (updated by background poller when DATA_SOURCE=live)
# ---------------------------------------------------------------------------
import threading

_live_state: Dict[str, Any] = {
    "payload": {},         # counter-keyed payload for engine.run()
    "alerts": [],          # alert list from remote API
    "image_url": None,     # absolute URL to snapshot image
    "raw": {},             # full raw response for debugging
    "timestamp": None,     # last update timestamp
    "frame_count": 0,      # total frames received since start
}
_live_lock = threading.Lock()
_live_update_event = threading.Event()  # signaled when new data arrives


def _on_live_frame(payload: Dict, alerts: list, image_url: str, raw: Dict):
    """Callback from RemoteAPIClient when a new valid frame arrives."""
    global _live_state
    with _live_lock:
        _live_state["payload"] = payload
        _live_state["alerts"] = alerts
        _live_state["image_url"] = image_url
        _live_state["raw"] = raw
        _live_state["timestamp"] = raw.get("timestamp") or raw.get("ts") or time.strftime("%Y-%m-%d %H:%M:%S")
        _live_state["frame_count"] += 1
    _live_update_event.set()  # signal waiting SSE streams


# ---------------------------------------------------------------------------
# Payload adapter
# ---------------------------------------------------------------------------

def _get_payloads() -> Dict[str, Dict[str, Any]]:
    """
    Return the current AI vision payloads using the configured data source.

    DATA_SOURCE is read from the environment at call-time so it can be
    changed between requests without restarting the server.

    Returns:
        Counter-keyed payload dict ready for ``engine.run()``.

    Raises:
        RuntimeError: If the HTTP adapter fails to reach the AI system.
        ValueError:   If ``DATA_SOURCE`` is set to an unknown value.
    """
    source = os.getenv("DATA_SOURCE", "mock")

    if source == "mock":
        return {
            "Gate A": {
                "queue_size":    18,
                "flow_rate":     1.2,
                "avg_baggage":   2.8,
                "special_items": 4,
            },
            "Security": {
                "queue_size":    12,
                "flow_rate":     2.1,
                "avg_baggage":   1.5,
                "special_items": 3,
            },
            "Arrivals Hall": {
                "queue_size":    2,
                "flow_rate":     3.5,
                "avg_baggage":   1.1,
                "special_items": 0,
            },
            "Departures": {
                "queue_size":    7,
                "flow_rate":     2.0,
                "avg_baggage":   2.0,
                "special_items": 1,
            },
        }

    if source == "snapshot4":
        return mock_snapshot4.get_snapshot_payload()  # cycles automatically

    if source == "http":
        import json
        import urllib.request

        url = os.getenv("AI_VISION_URL", "http://localhost:8080/snapshot")
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = json.loads(resp.read().decode())
            payloads = body.get("counters", {})
            if not payloads:
                raise ValueError("AI vision snapshot returned no counter data.")
            return payloads
        except Exception as exc:
            raise RuntimeError(f"HTTP adapter error: {exc}") from exc

    if source == "live":
        # Returns the latest cached payload from the remote API poller
        # If no data yet, returns empty dict which engine handles gracefully
        return _live_state.get("payload", {})

    raise ValueError(
        f"Unsupported DATA_SOURCE {source!r}. "
        "Valid options: 'mock', 'snapshot4', 'http', 'live'."
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
def dashboard() -> Response:
    """
    GET /api/dashboard

    Runs the full AeroVision pipeline and returns the dashboard data as JSON.

    Response body (``DashboardDTO``)::

        {
          "system_metrics": {
            "throughput": 282,
            "throughput_change_pct": 101.4,
            "avg_clearance_time": "11m 47s",
            "avg_clearance_delta": "+500s",
            "critical_bottlenecks": 1,
            "flights_at_risk": 1,
            "live_feeds_active": 2,
            "action_required": true,
            "timestamp": "3/7/2026 02:13 PM",
            "system_status": "SYSTEM ACTIVE",
            "app_version": "v1.0-alpha"
          },
          "counters":      [ { "id": "03", "type": "Int'l", … }, … ],
          "flights":       [ { "id": "DL789", "at_risk": true, … }, … ],
          "optimizations": [ { "action": "Reallocate Staff", … }, … ],
          "processing_errors": [],
          "schedule": {
            "DL789": { "counter_ids": ["03"], "start_time": "…",
                       "end_time": "…", "active": true }
          }
        }

    HTTP status codes:
        200  Success – JSON body contains dashboard data.
        500  Engine or data-source error – JSON body contains ``"error"`` key.
    """
    try:
        payloads = _get_payloads()
        output: Dict[str, Any] = _engine.run(payloads)
        return jsonify(output), 200

    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Live SSE stream  –  pushes one full dashboard update every 3 s,
# cycling through all snapshot4 frames in order.
# ---------------------------------------------------------------------------

@app.get("/api/stream")
def snapshot_stream() -> Response:
    """
    GET /api/stream  (Server-Sent Events)

    Streams a new dashboard snapshot every 3 seconds, cycling through all
    snapshot4 frames.  Each event is a full DashboardDTO JSON object with
    two extra fields injected by the server:

        ``_frame``  – 0-based index of the current frame
        ``_total``  – total number of available frames

    The browser dashboard connects to this endpoint via ``EventSource`` and
    updates itself on every message without a page reload.
    """
    def _generate():
        idx = 0
        while True:
            try:
                payload = mock_snapshot4.get_snapshot_payload(index=idx)
                output: Dict[str, Any] = _engine.run(payload)
                output["_frame"] = idx
                output["_total"] = mock_snapshot4.SNAPSHOT_COUNT
                output["_snapshot_image"]  = mock_snapshot4.get_frame_image(idx)
                output["_alerts"]          = mock_snapshot4.get_frame_alerts(idx)
                output["_heatmaps"]        = mock_snapshot4.get_frame_heatmaps(idx)
                yield f"data: {json.dumps(output)}\n\n"
            except Exception as exc:
                yield f"data: {{\"error\": \"{exc}\"}}\n\n"
            idx = (idx + 1) % mock_snapshot4.SNAPSHOT_COUNT
            time.sleep(3)

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Live SSE stream  –  streams data from remote API (DATA_SOURCE=live)
# ---------------------------------------------------------------------------

@app.get("/api/live")
def live_stream() -> Response:
    """
    GET /api/live  (Server-Sent Events)

    Streams dashboard updates from the remote airport-monitor API in real-time.
    Unlike /api/stream (which cycles through mock data), this endpoint:

    1. Polls the remote API at http://<REMOTE_API_URL>/latest
    2. Skips frames marked as "no data"
    3. Deduplicates by timestamp to avoid redundant updates
    4. Pushes only when new valid data arrives

    The remote API URL is configured via REMOTE_API_URL environment variable.
    Default: http://192.168.1.42:8000

    Events include:
        ``_frame``       – running frame count since connection started
        ``_live``        – always true (distinguishes from mock stream)
        ``_image_url``   – absolute URL to the snapshot image
        ``_alerts``      – alerts from the remote API
        ``_connected``   – true if remote API is reachable
    """
    def _generate():
        local_frame_count = 0
        last_seen_frame = 0

        while True:
            # Wait for new data or timeout after 3 seconds
            _live_update_event.wait(timeout=3.0)
            _live_update_event.clear()

            with _live_lock:
                current_frame = _live_state["frame_count"]
                # Skip if no new data
                if current_frame == last_seen_frame and current_frame > 0:
                    # Send heartbeat to keep connection alive
                    yield f": heartbeat\n\n"
                    continue

                last_seen_frame = current_frame
                payload = _live_state["payload"]
                alerts = _live_state["alerts"]
                image_url = _live_state["image_url"]
                timestamp = _live_state["timestamp"]

            # Skip empty payloads (no data yet)
            if not payload:
                yield f"data: {{\"_live\": true, \"_waiting\": true, \"_message\": \"Waiting for remote API data...\"}}\n\n"
                continue

            try:
                output: Dict[str, Any] = _engine.run(payload)
                output["_frame"] = local_frame_count
                output["_live"] = True
                output["_connected"] = True
                output["_image_url"] = image_url
                output["_alerts"] = alerts
                output["_timestamp"] = timestamp
                output["_total_frames"] = current_frame
                local_frame_count += 1
                yield f"data: {json.dumps(output)}\n\n"
            except Exception as exc:
                yield f"data: {{\"error\": \"{exc}\", \"_live\": true}}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/live/status")
def live_status() -> Response:
    """
    GET /api/live/status

    Returns the current status of the live API connection.
    """
    client = get_shared_client()
    with _live_lock:
        return jsonify({
            "connected": client.is_connected() if client else False,
            "polling": client.is_alive() if client else False,
            "frame_count": _live_state["frame_count"],
            "last_timestamp": _live_state["timestamp"],
            "has_data": bool(_live_state["payload"]),
        }), 200


@app.get("/api/live/latest")
def live_latest() -> Response:
    """
    GET /api/live/latest

    Returns the most recent frame from the remote API (non-streaming).
    Useful for one-off requests or polling fallback.
    """
    with _live_lock:
        if not _live_state["payload"]:
            return jsonify({"status": "no_data", "message": "No data received yet from remote API"}), 200

        try:
            output: Dict[str, Any] = _engine.run(_live_state["payload"])
            output["_live"] = True
            output["_image_url"] = _live_state["image_url"]
            output["_alerts"] = _live_state["alerts"]
            output["_timestamp"] = _live_state["timestamp"]
            output["_frame_count"] = _live_state["frame_count"]
            return jsonify(output), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Browser dashboard
# ---------------------------------------------------------------------------

@app.get("/")
def dashboard_ui() -> Response:
    """Serve the live HTML dashboard."""
    return render_template("dashboard.html")


@app.get("/static/<path:filename>")
def serve_static(filename: str) -> Response:
    """Serve files from the project-level static/ folder (floor plan, zones JSON)."""
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    return send_from_directory(static_dir, filename)


@app.get("/api/snapshot_image/<path:filename>")
def serve_snapshot_image(filename: str) -> Response:
    """Serve JPG snapshot images (and heatmaps) from the snapshots4 data folder."""
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "snapshots4#2", "snapshots4"
    )
    return send_from_directory(data_dir, filename)


@app.get("/api/heatmap_image/<path:filename>")
def serve_heatmap_image(filename: str) -> Response:
    """Serve per-camera heatmap images from the snapshots4/heatmaps/ folder."""
    heatmap_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "snapshots4#2", "snapshots4", "heatmaps"
    )
    return send_from_directory(heatmap_dir, filename)


# ---------------------------------------------------------------------------
# Per-zone camera images from the new cameras/ folder
# ---------------------------------------------------------------------------

_CAMERAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cameras")


@app.get("/api/camera_image/<zone>/<path:filename>")
def serve_camera_image(zone: str, filename: str) -> Response:
    """Serve a per-zone camera image from cameras/<zone>/<filename>."""
    zone_dir = os.path.join(_CAMERAS_DIR, zone)
    if not os.path.isdir(zone_dir):
        return jsonify({"error": f"Unknown camera zone: {zone}"}), 404
    return send_from_directory(zone_dir, filename)


@app.get("/api/camera_list/<zone>")
def list_camera_images(zone: str) -> Response:
    """Return a sorted list of image filenames for a camera zone."""
    zone_dir = os.path.join(_CAMERAS_DIR, zone)
    if not os.path.isdir(zone_dir):
        return jsonify({"error": f"Unknown camera zone: {zone}"}), 404
    files = sorted(
        f for f in os.listdir(zone_dir)
        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
    )
    return jsonify({"zone": zone, "total": len(files), "files": files}), 200


# ---------------------------------------------------------------------------
# Mock / snapshot4 browsing endpoints
# ---------------------------------------------------------------------------

@app.get("/api/mock/snapshots")
def list_snapshots() -> Response:
    """
    GET /api/mock/snapshots

    Returns all snapshot4 frames as a list, each containing an index and
    the 4-counter payload derived from the real AI measurements.

    Response shape::

        {
          "total": 12,
          "snapshots": [
            {"index": 0, "counters": {"Gate A": {…}, "Security": {…}, …}},
            …
          ]
        }
    """
    return jsonify({
        "total":     mock_snapshot4.SNAPSHOT_COUNT,
        "snapshots": mock_snapshot4.get_all_snapshots(),
    }), 200


@app.get("/api/mock/snapshot/<int:index>")
def single_snapshot(index: int) -> Response:
    """
    GET /api/mock/snapshot/<index>

    Run the full engine pipeline using one specific snapshot4 frame
    (0-based index, wraps around if out of range).

    Response body is identical to ``GET /api/dashboard`` so the frontend
    can replay any captured frame without polling.
    """
    try:
        payload = mock_snapshot4.get_snapshot_payload(index=index)
        output: Dict[str, Any] = _engine.run(payload)
        output["_snapshot_image"] = mock_snapshot4.get_frame_image(index)
        output["_alerts"]         = mock_snapshot4.get_frame_alerts(index)
        output["_heatmaps"]       = mock_snapshot4.get_frame_heatmaps(index)
        return jsonify(output), 200
    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/mock/scene")
def scene_analysis() -> Response:
    """
    GET /api/mock/scene

    Returns the AI scene analysis from ``message (1).txt``:
    crowd density, passenger flow, contributing factors, risk prediction,
    recommended solutions, and explainability notes.
    """
    return jsonify(mock_snapshot4.get_scene_analysis()), 200


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _start_live_poller():
    """Start the remote API polling client if DATA_SOURCE=live."""
    source = os.getenv("DATA_SOURCE", "mock")
    if source != "live":
        return None

    remote_url = os.getenv("REMOTE_API_URL", "http://192.168.1.42:8000")
    poll_interval = float(os.getenv("POLL_INTERVAL", "3"))

    print(f"  🔴 LIVE MODE    →  Polling {remote_url} every {poll_interval}s")

    client = start_shared_client(
        base_url=remote_url,
        on_new_frame=_on_live_frame,
        poll_interval=poll_interval,
    )
    return client


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    source = os.getenv("DATA_SOURCE", "mock")

    print(f"  AeroVision API  →  http://{host}:{port}/api/dashboard")
    print(f"  DATA_SOURCE     →  {source}")
    print(f"  Debug mode      →  {debug}")

    if source == "live":
        print(f"  REMOTE_API_URL  →  {os.getenv('REMOTE_API_URL', 'http://192.168.1.42:8000')}")
        print(f"  POLL_INTERVAL   →  {os.getenv('POLL_INTERVAL', '3')}s")
        print(f"  Live endpoints  →  /api/live (SSE), /api/live/latest, /api/live/status")
        _start_live_poller()

    app.run(host=host, port=port, debug=debug)

