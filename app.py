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
    # Scene-level risk / recommendations from the AI analysis are used to
    # populate the expectation field so suggestions are grounded in real data.
    _scene = mock_snapshot4.get_scene_analysis()
    _risk  = _scene.get("gateway_congestion_prediction", {})
    _solutions = _scene.get("recommended_solutions", [])
    _solution_text = "; ".join(
        s.get("solution", "") for s in _solutions[:2]
    ) if _solutions else "monitor closely"

    dl789 = Flight(
        flight_id="DL789",
        status="DEPARTS 45M",
        minutes_to_departure=45.0,
        expectation=(
            f"Scene risk: {_risk.get('risk_level', 'unknown')} "
            f"(confidence: {_risk.get('confidence', 'unknown')}). "
            f"Suggested actions: {_solution_text}."
        ),
    )
    ua456 = Flight(
        flight_id="UA456",
        status="LANDED",
        minutes_to_departure=None,
        expectation=(
            "Inbound UA456 passengers expected to join Arrivals Hall queue "
            "in approximately 20 minutes."
        ),
    )
    engine.add_flight(dl789)
    engine.add_flight(ua456)

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

    engine.set_scheduler(scheduler)
    return engine


# Build the engine once at module load time.
_engine: Engine = _build_engine()


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

    raise ValueError(
        f"Unsupported DATA_SOURCE {source!r}. "
        "Valid options: 'mock', 'snapshot4', 'http'."
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

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_ENV", "production") == "development"

    print(f"  AeroVision API  →  http://{host}:{port}/api/dashboard")
    print(f"  DATA_SOURCE     →  {os.getenv('DATA_SOURCE', 'mock')}")
    print(f"  Debug mode      →  {debug}")

    app.run(host=host, port=port, debug=debug)
