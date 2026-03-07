"""
main.py – AeroVision Entry Point
==================================
Bootstraps the full AeroVision backend pipeline.

DATA SOURCE MODES
-----------------
The engine itself is completely data-source agnostic.  ``main.py`` selects
the source via the ``DATA_SOURCE`` constant:

    "mock"      – hardcoded payloads for local testing (current default).
    "http"      – pulls a single JSON snapshot from a REST endpoint exposed
                  by the AI surveillance system (ready to enable).
    "websocket" – receives a continuous stream of frames; each message is
                  processed immediately and the output is forwarded to a
                  downstream consumer (ready to enable).

To switch source, change ``DATA_SOURCE`` below and supply the appropriate
environment variables (``AI_VISION_URL`` etc.).

Running this file produces:
1. A full JSON blob (stdout) containing all dashboard-ready fields.
2. A human-readable summary table printed below the JSON.

Usage::

    python main.py
    DATA_SOURCE=http AI_VISION_URL=http://localhost:8080/snapshot python main.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

from engine import Engine
from models import Counter, Flight
from scheduler import ScheduleManager
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Select data source (override via env var for easy CI / production switching)
# ---------------------------------------------------------------------------
DATA_SOURCE: str = os.getenv("DATA_SOURCE", "mock")   # "mock" | "http" | "websocket"

# AI surveillance system endpoint (used when DATA_SOURCE != "mock")
AI_VISION_URL: str = os.getenv("AI_VISION_URL", "http://localhost:8080/snapshot")


# ===========================================================================
# DATA ADAPTERS
# ---------------------------------------------------------------------------
# Each adapter must return a dict shaped exactly like MOCK_AI_PAYLOADS:
#
#   { "<counter_id>": { "queue_size": int, "flow_rate": float,
#                       "avg_baggage": float, "special_items": int }, … }
#
# The engine never touches these functions — it only consumes the resulting
# dict via engine.run(payloads).  Swap adapters freely without changing any
# downstream logic.
# ===========================================================================

def _fetch_http_snapshot() -> Dict[str, Dict[str, Any]]:
    """
    Pull a single JSON snapshot from the AI surveillance system's REST endpoint.

    The AI system is expected to POST or expose GET at ``AI_VISION_URL`` a
    JSON body with this structure::

        {
          "counters": {
            "03": {"queue_size": 18, "flow_rate": 1.2,
                   "avg_baggage": 2.8, "special_items": 4},
            "04": {"queue_size": 2,  "flow_rate": 3.5,
                   "avg_baggage": 1.1, "special_items": 0}
          }
        }

    Enable by setting ``DATA_SOURCE=http`` (and optionally ``AI_VISION_URL``).

    Returns:
        Counter-keyed payload dict ready for ``engine.run()``.

    Raises:
        RuntimeError: If the HTTP request fails or the response is malformed.
    """
    try:
        import urllib.request

        with urllib.request.urlopen(AI_VISION_URL, timeout=5) as resp:
            body = json.loads(resp.read().decode())

        payloads: Dict[str, Dict[str, Any]] = body.get("counters", {})
        if not payloads:
            raise ValueError(
                f"AI vision snapshot at {AI_VISION_URL!r} returned no counter data."
            )
        return payloads

    except Exception as exc:
        raise RuntimeError(
            f"HTTP adapter failed to fetch from {AI_VISION_URL!r}: {exc}"
        ) from exc


def _stream_websocket(engine: Engine) -> None:
    """
    Receive a continuous stream of AI vision frames over WebSocket and process
    each frame through the engine immediately.

    Each message must be a JSON string with the same ``counters`` structure as
    :func:`_fetch_http_snapshot`.

    Enable by setting ``DATA_SOURCE=websocket`` (and ``AI_VISION_URL`` pointing
    to a ``ws://`` or ``wss://`` URI).

    This function **blocks** until the connection closes or an error occurs.
    In a production deployment, run it in a dedicated thread or async task.

    Args:
        engine: A fully configured :class:`~engine.Engine` instance whose
                registered counters and flights will be updated on every frame.

    Note:
        Requires the third-party ``websockets`` package (``pip install websockets``).
        The import is deferred so the rest of the system works without it.
    """
    try:
        import asyncio
        import websockets  # type: ignore[import]

        async def _loop() -> None:
            ws_url = AI_VISION_URL.replace("http://", "ws://").replace(
                "https://", "wss://"
            )
            print(f"[WebSocket] Connecting to {ws_url} …", file=sys.stderr)
            async with websockets.connect(ws_url) as ws:
                async for raw_message in ws:
                    try:
                        body = json.loads(raw_message)
                        payloads = body.get("counters", {})
                        if not payloads:
                            continue
                        output = engine.run(payloads)
                        # Forward dashboard-ready output to stdout for a
                        # downstream consumer (e.g. Flask SSE, Streamlit, Redis)
                        print(json.dumps(output))
                        sys.stdout.flush()
                    except (json.JSONDecodeError, Exception) as frame_err:
                        print(
                            f"[WebSocket] Frame error: {frame_err}", file=sys.stderr
                        )

        asyncio.run(_loop())

    except ImportError:
        raise RuntimeError(
            "WebSocket adapter requires 'websockets': pip install websockets"
        )


def get_ai_payloads(engine: Engine) -> Dict[str, Dict[str, Any]]:
    """
    Route to the correct data adapter based on ``DATA_SOURCE``.

    Args:
        engine: Needed only when ``DATA_SOURCE == "websocket"`` (streaming mode
                drives the engine directly from inside the adapter).

    Returns:
        Counter-keyed payload dict when ``DATA_SOURCE`` is ``"mock"`` or
        ``"http"``.  Returns an empty dict when ``DATA_SOURCE`` is
        ``"websocket"`` because that mode blocks and drives the engine itself.

    Raises:
        ValueError:  If ``DATA_SOURCE`` is set to an unknown value.
        RuntimeError: If the selected adapter fails (e.g. network error).
    """
    if DATA_SOURCE == "mock":
        return MOCK_AI_PAYLOADS

    if DATA_SOURCE == "http":
        print(
            f"[HTTP adapter] Fetching snapshot from {AI_VISION_URL} …",
            file=sys.stderr,
        )
        return _fetch_http_snapshot()

    if DATA_SOURCE == "websocket":
        _stream_websocket(engine)   # blocks; drives engine internally
        return {}

    raise ValueError(
        f"Unknown DATA_SOURCE {DATA_SOURCE!r}. "
        "Valid options: 'mock', 'http', 'websocket'."
    )


# ===========================================================================
# Mock AI vision system payloads  (DATA_SOURCE == "mock")
# ---------------------------------------------------------------------------
# In production these dicts arrive as JSON from the upstream AI vision
# service (real-time video analysis).  Each dict corresponds to a single
# counter and represents the latest snapshot extracted from the camera feed.
# ===========================================================================

MOCK_AI_PAYLOADS: Dict[str, Dict[str, Any]] = {
    # ------------------------------------------------------------------
    # Counter 03 – International check-in (heavily loaded)
    # ------------------------------------------------------------------
    "03": {
        "queue_size":    18,    # 18 passengers detected in the queue lane
        "flow_rate":     1.2,   # 1.2 pax/min – agent is slow due to complex docs
        "avg_baggage":   2.8,   # 2.8 bags per passenger on average
        "special_items": 4,     # 4 special items: 2 strollers + 2 wheelchair pax
    },
    # ------------------------------------------------------------------
    # Counter 04 – Domestic check-in (lightly loaded)
    # ------------------------------------------------------------------
    "04": {
        "queue_size":    2,     # Almost empty: 2 passengers
        "flow_rate":     3.5,   # 3.5 pax/min – fast, simple domestic check-in
        "avg_baggage":   1.1,   # Light travellers
        "special_items": 0,     # No special items
    },
}

# ===========================================================================
# Mock flight data
# ---------------------------------------------------------------------------
# In production flight schedules are fetched from a Departure Control System
# (DCS) or airline ops API.  Here they are hardcoded for testing.
# ===========================================================================

def _build_flights() -> list:
    """Construct the two mocked Flight objects WITHOUT any counter assignments.

    Counter assignments are now managed exclusively by the ``ScheduleManager``
    registered on the engine.  The ``associated_counters`` list on each flight
    starts empty and is populated dynamically at the start of every
    ``engine.run()`` call.
    """

    # DL789 – departing soon; counter assignment driven by schedule window
    dl789 = Flight(
        flight_id="DL789",
        status="DEPARTS 45M",
        minutes_to_departure=45.0,
        expectation=(
            "High inbound transfer volume detected. "
            "Expecting +30 pax at Counter 04 in 15 mins."
        ),
    )

    # UA456 – already landed; check-in window closed, no counter assigned
    ua456 = Flight(
        flight_id="UA456",
        status="LANDED",
        minutes_to_departure=None,
        expectation=(
            "Inbound UA456 passengers expected to join Counter 04 queue "
            "in approximately 20 minutes."
        ),
    )

    return [dl789, ua456]


# ===========================================================================
# Engine bootstrap
# ===========================================================================

def build_engine() -> Engine:
    """
    Instantiate and configure the :class:`~engine.Engine` with all counters,
    flights, and a :class:`~scheduler.ScheduleManager`.

    Schedule windows (relative to current wall-clock time)
    -------------------------------------------------------
    DL789 (departs in 45 min)
        Check-in opened 2 h ago and closes in 20 min → **window active**.
        Counter 03 (Int’l) is assigned.

    UA456 (already landed)
        Check-in opened 5 h ago and closed 1 h ago → **window expired**.
        ``associated_counters`` is cleared to ``[]``.

    Returns:
        A ready-to-run Engine instance.
    """
    engine = Engine()

    # Register counters
    engine.add_counter(Counter(counter_id="03", counter_type="Int'l"))
    engine.add_counter(Counter(counter_id="04", counter_type="Domestic"))

    # Register flights (associated_counters left empty – scheduler fills them)
    for flight in _build_flights():
        engine.add_flight(flight)

    # ------------------------------------------------------------------
    # Build the ScheduleManager with mocked check-in windows.
    # In production these entries come from a DCS / airline ops API.
    # ------------------------------------------------------------------
    now = datetime.now()
    scheduler = ScheduleManager()

    # DL789: check-in open from 2 h ago, closes in 20 min → currently ACTIVE
    scheduler.register(
        flight_id="DL789",
        counter_ids=["03"],
        start_time=now - timedelta(hours=2),
        end_time=now + timedelta(minutes=20),
    )

    # UA456: check-in was open from 5 h ago, closed 1 h ago → EXPIRED
    scheduler.register(
        flight_id="UA456",
        counter_ids=["04"],
        start_time=now - timedelta(hours=5),
        end_time=now - timedelta(hours=1),
    )

    engine.set_scheduler(scheduler)

    return engine


# ===========================================================================
# Pretty-print helpers
# ===========================================================================

_SEP = "=" * 68
_SEP_THIN = "-" * 68


def _print_summary(output: Dict[str, Any]) -> None:
    """
    Print a concise human-readable summary of the pipeline output to stdout.

    Args:
        output: Full output dict from :meth:`~engine.Engine.get_full_output`.
    """
    sm = output["system_metrics"]

    print()
    print(_SEP)
    print(
        f"  ✈  AeroVision  {sm['app_version']}   │   {sm['system_status']}"
    )
    print(f"     Timestamp : {sm['timestamp']}")
    print(_SEP_THIN)

    # ---- Overall KPIs -------------------------------------------------------
    print("  SYSTEM METRICS")
    print(
        f"    Throughput        : {sm['throughput']} pax/hr  "
        f"({sm['throughput_change_pct']:+.1f}% vs avg)"
    )
    print(
        f"    Avg Clearance     : {sm['avg_clearance_time']}  "
        f"(delta {sm['avg_clearance_delta']})"
    )
    print(f"    Critical Bottlenecks : {sm['critical_bottlenecks']}")
    print(f"    Flights at Risk      : {sm['flights_at_risk']}")
    print(f"    Live Feeds Active    : {sm['live_feeds_active']}")
    print(
        f"    Action Required      : "
        f"{'⚠ YES' if sm['action_required'] else 'NO'}"
    )

    # ---- Per-counter metrics ------------------------------------------------
    print(_SEP_THIN)
    print("  COUNTERS")
    for c in output["counters"]:
        risk_icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(
            c["risk_level"], "⚪"
        )
        print(
            f"    {risk_icon} Counter {c['id']} ({c['type']})"
            f"  |  Queue: {c['queue_size']} pax"
            f"  |  Flow: {c['flow_rate']:.1f}/min"
            f"  |  AvgBag: {c['avg_baggage']:.1f}"
            f"  |  SpecialItems: {c['special_items']}"
        )
        print(f"       Forecast : {c['forecast']}")
        print(
            f"       Clearance: {c['clearance_minutes']:.1f} min  "
            f"  Risk: {c['risk_level']}"
        )

    # ---- Flight correlations ------------------------------------------------
    print(_SEP_THIN)
    print("  FLIGHT CORRELATIONS")
    for f in output["flights"]:
        at_risk_label = "⚠ AT RISK" if f["at_risk"] else "✓ OK"
        print(
            f"    {f['id']} [{f['status']}]  →  {at_risk_label}"
        )
        if f["issue"]:
            print(f"       {f['issue']}")
        if f["description"]:
            print(f"       {f['description']}")
        if f["expectation"]:
            print(f"       ℹ {f['expectation']}")

    # ---- Optimisations ------------------------------------------------------
    print(_SEP_THIN)
    print("  SUGGESTED OPTIMIZATIONS")
    if not output["optimizations"]:
        print("    No optimizations required at this time.")
    for idx, o in enumerate(output["optimizations"], 1):
        actionable_label = "✅ ACTIONABLE" if o["actionable"] else "ℹ INFO"
        print(f"    [{idx}] {o['action']}  ({actionable_label})")
        print(f"        {o['details']}")
        print(f"        Est. impact: {o['estimated_impact']:.0f}% delay reduction")

    # ---- Processing errors --------------------------------------------------
    if output["processing_errors"]:
        print(_SEP_THIN)
        print("  ⚠  PROCESSING ERRORS")
        for err in output["processing_errors"]:
            print(f"    {err}")
    # ---- Schedule snapshot --------------------------------------------------
    if output.get("schedule"):
        print(_SEP_THIN)
        print("  SCHEDULE ASSIGNMENTS (at run time)")
        for fid, entry in output["schedule"].items():
            active_label = "\u2705 ACTIVE" if entry.get("active") else "\u23f9 EXPIRED/PENDING"
            counters_label = (
                ", ".join(f"Counter {c}" for c in entry["counter_ids"])
                if entry["counter_ids"]
                else "(none)"
            )
            print(
                f"    {fid:8s}  {active_label:18s}"
                f"  Counters: {counters_label}"
            )
            print(
                f"             window: {entry['start_time'][:16]} – "
                f"{entry['end_time'][:16]}"
            )
    print(_SEP)
    print()


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    """
    Entry point: build engine, fetch payloads from the selected data source,
    run the pipeline, and print results.

    DATA_SOURCE selects the adapter:
        "mock"      → MOCK_AI_PAYLOADS (default, no external dependencies)
        "http"      → single REST snapshot from AI_VISION_URL
        "websocket" → continuous stream; this call blocks until disconnected
    """
    engine = build_engine()

    # -------------------------------------------------------------------
    # Fetch payloads from the configured data source.
    # In websocket mode, get_ai_payloads() blocks and drives the engine
    # internally — no further code in this function runs.
    # -------------------------------------------------------------------
    try:
        payloads = get_ai_payloads(engine)
    except (RuntimeError, ValueError) as exc:
        print(f"[ERROR] Data source error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Websocket mode drives itself; nothing left to do.
    if DATA_SOURCE == "websocket":
        return

    # Run the full pipeline
    output = engine.run(payloads)

    # ---- 1. Full JSON output (for API / Streamlit / Flask consumers) ----
    print(json.dumps(output, indent=2))

    # ---- 2. Human-readable summary table --------------------------------
    _print_summary(output)


if __name__ == "__main__":
    main()
