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

from flask import Flask, jsonify, Response
from flask_cors import CORS

from engine import Engine
from models import Counter, Flight
from scheduler import ScheduleManager

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

    # ---- Counters -----------------------------------------------------------
    engine.add_counter(Counter(counter_id="03", counter_type="Int'l"))
    engine.add_counter(Counter(counter_id="04", counter_type="Domestic"))

    # ---- Flights ------------------------------------------------------------
    dl789 = Flight(
        flight_id="DL789",
        status="DEPARTS 45M",
        minutes_to_departure=45.0,
        expectation=(
            "High inbound transfer volume detected. "
            "Expecting +30 pax at Counter 04 in 15 mins."
        ),
    )
    ua456 = Flight(
        flight_id="UA456",
        status="LANDED",
        minutes_to_departure=None,
        expectation=(
            "Inbound UA456 passengers expected to join Counter 04 queue "
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
        counter_ids=["03"],
        start_time=now - timedelta(hours=2),
        end_time=now + timedelta(minutes=20),
    )

    # UA456: check-in closed 1 h ago → EXPIRED
    scheduler.register(
        flight_id="UA456",
        counter_ids=["04"],
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
            "03": {
                "queue_size":    18,
                "flow_rate":     1.2,
                "avg_baggage":   2.8,
                "special_items": 4,
            },
            "04": {
                "queue_size":    2,
                "flow_rate":     3.5,
                "avg_baggage":   1.1,
                "special_items": 0,
            },
        }

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
        "Valid options: 'mock', 'http'."
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
