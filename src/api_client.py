"""
api_client.py – Remote API Client for AeroVision
==================================================
Polls the remote airport-monitor snapshot API (http://<HOST>:8000/latest)
and transforms responses into the payload format the AeroVision engine expects.

The client runs a background polling thread that continuously checks for new
frames and notifies the application via a callback when valid data arrives.

Usage
-----
    from src.api_client import RemoteAPIClient

    def on_new_frame(payload, alerts, image_url, raw):
        print("New frame:", payload)

    client = RemoteAPIClient(
        base_url="http://192.168.1.42:8000",
        on_new_frame=on_new_frame,
    )
    client.start()
    # ... later ...
    client.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_POLL_INTERVAL = 3  # seconds between polls
NO_DATA_MARKERS = ("no data", "no_data", "empty", "unavailable")


class RemoteAPIClient:
    """
    Background thread that continuously polls GET /latest on the remote
    airport-monitor API and calls `on_new_frame` whenever a real frame
    arrives (i.e. the payload does NOT carry the 'no data' sentinel).

    Attributes
    ----------
    base_url : str
        Base URL of the remote API (e.g. "http://192.168.1.42:8000")
    poll_interval : float
        Seconds between poll attempts
    """

    def __init__(
        self,
        base_url: str,
        on_new_frame: Callable[[Dict[str, Any], List[Dict], Optional[str], Dict], None],
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        """
        Parameters
        ----------
        base_url
            Remote API root, e.g. "http://192.168.1.42:8000"
        on_new_frame
            Callback(payload, alerts, image_url, raw_response) called when
            a valid frame arrives. `payload` is the counter dict ready for
            engine.run(); `alerts` is a list of alert dicts; `image_url` is
            the absolute URL to the snapshot image; `raw` is the full API
            response for debugging.
        poll_interval
            Seconds between polls (default: 3)
        """
        self.base_url = base_url.rstrip("/")
        self.on_new_frame = on_new_frame
        self.poll_interval = poll_interval

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_seen_ts: Optional[str] = None
        self._last_seen_snapshot: Optional[str] = None
        self._lock = threading.Lock()

        # Track connection health
        self._consecutive_errors = 0
        self._is_connected = False

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("RemoteAPIClient: already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="RemoteAPIPoller"
        )
        logger.info(
            "RemoteAPIClient: starting poller → %s (every %.1fs)",
            self.base_url,
            self.poll_interval,
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the background polling thread."""
        logger.info("RemoteAPIClient: stopping poller...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._is_connected = False

    def is_alive(self) -> bool:
        """Return True if the polling thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def is_connected(self) -> bool:
        """Return True if the last poll succeeded."""
        return self._is_connected

    def health_check(self) -> Dict[str, Any]:
        """
        Perform a synchronous health check against the remote API.

        Returns a dict with "status" ("ok" / "error") and optional details.
        """
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def fetch_latest_sync(self) -> Optional[Dict[str, Any]]:
        """
        Synchronously fetch /latest and return the raw response or None on error.
        Useful for one-off tests outside the polling loop.
        """
        try:
            resp = requests.get(f"{self.base_url}/latest", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("RemoteAPIClient: fetch_latest_sync failed: %s", exc)
            return None

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Main polling loop — runs in background thread."""
        while not self._stop_event.is_set():
            try:
                self._fetch_and_dispatch()
                self._consecutive_errors = 0
                self._is_connected = True
            except Exception as exc:
                self._consecutive_errors += 1
                self._is_connected = False
                # Exponential backoff on repeated errors (capped at 30s)
                backoff = min(30, self.poll_interval * (2 ** min(self._consecutive_errors - 1, 4)))
                logger.warning(
                    "RemoteAPIClient: poll error (%d consecutive): %s  [backoff %.1fs]",
                    self._consecutive_errors,
                    exc,
                    backoff,
                )
                self._stop_event.wait(backoff)
                continue

            self._stop_event.wait(self.poll_interval)

    def _fetch_and_dispatch(self) -> None:
        """Fetch /latest and dispatch to callback if it's new valid data."""
        url = f"{self.base_url}/latest"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        # ── Guard: remote signals "no data" ─────────────────────────────
        if self._is_no_data(data):
            logger.debug("RemoteAPIClient: received 'no data' — skipping")
            return

        # ── Guard: deduplicate by timestamp / snapshot_id ───────────────
        ts = data.get("timestamp") or data.get("ts")
        snap = data.get("snapshot_id") or data.get("snap_id") or data.get("image_url")

        with self._lock:
            if ts and ts == self._last_seen_ts and snap == self._last_seen_snapshot:
                logger.debug("RemoteAPIClient: duplicate frame ts=%s — skipping", ts)
                return
            self._last_seen_ts = ts
            self._last_seen_snapshot = snap

        logger.info("RemoteAPIClient: new frame  ts=%s  snap=%s", ts, snap)

        # ── Transform to engine payload ─────────────────────────────────
        payload = self._extract_payload(data)
        alerts = data.get("alerts", [])
        image_url = data.get("image_url")

        # Make image_url absolute if needed
        if image_url and not image_url.startswith("http"):
            image_url = self.base_url + image_url

        # ── Fire callback ───────────────────────────────────────────────
        try:
            self.on_new_frame(payload, alerts, image_url, data)
        except Exception as exc:
            logger.exception("RemoteAPIClient: on_new_frame callback error: %s", exc)

    def _is_no_data(self, data: Dict[str, Any]) -> bool:
        """Return True when the API signals that no frame is available."""
        # Check common sentinel fields
        for field in ("data", "status", "message"):
            val = data.get(field)
            if isinstance(val, str):
                low = val.lower()
                if any(marker in low for marker in NO_DATA_MARKERS):
                    return True

        # If detections AND alerts are both absent/empty AND there's a sentinel
        if not data.get("detections") and not data.get("alerts"):
            if data.get("no_data") or data.get("empty"):
                return True

        return False

    def _extract_payload(self, data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Transform the raw /latest response into the counter-keyed payload
        dict that engine.run() expects.

        The remote API may provide data in several formats; this method
        normalizes them all.
        """
        # Case 1: already has 'counters' dict keyed by camera name
        if "counters" in data and isinstance(data["counters"], dict):
            return data["counters"]

        # Case 2: 'detections' list with per-camera entries
        detections = data.get("detections", [])
        if detections:
            return self._detections_to_payload(detections)

        # Case 3: flat payload with camera keys at top level (Gate A, Security, etc.)
        camera_names = {"Gate A", "Security", "Arrivals Hall", "Departures"}
        if any(cam in data for cam in camera_names):
            return {k: v for k, v in data.items() if k in camera_names and isinstance(v, dict)}

        # Fallback: return empty — the engine will handle missing counters
        logger.warning("RemoteAPIClient: could not extract payload from response")
        return {}

    def _detections_to_payload(
        self, detections: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Convert a list of detection records to the engine payload format.

        Expected detection shape:
            {
                "camera": "Gate A",
                "queue_size": 12,
                "flow_rate": 1.5,
                "avg_baggage": 2.0,
                "special_items": 2
            }
        """
        payload: Dict[str, Dict[str, Any]] = {}
        for det in detections:
            camera = det.get("camera") or det.get("zone") or det.get("location")
            if not camera:
                continue

            # Normalize camera name
            camera_key = self._normalize_camera_name(camera)
            if not camera_key:
                continue

            payload[camera_key] = {
                "queue_size": det.get("queue_size", det.get("person_count", 0)),
                "flow_rate": det.get("flow_rate", det.get("flow_rate_per_min", 1.0)),
                "avg_baggage": det.get("avg_baggage", det.get("avg_baggage_per_pax", 1.0)),
                "special_items": det.get("special_items", det.get("total_specials", 0)),
            }

        return payload

    @staticmethod
    def _normalize_camera_name(name: str) -> Optional[str]:
        """Map various camera name formats to canonical counter names."""
        mappings = {
            "gate_a": "Gate A",
            "gate a": "Gate A",
            "gatea": "Gate A",
            "security": "Security",
            "arrivals_hall": "Arrivals Hall",
            "arrivals hall": "Arrivals Hall",
            "arrivalshall": "Arrivals Hall",
            "arrivals": "Arrivals Hall",
            "departures": "Departures",
        }
        key = name.lower().strip()
        return mappings.get(key, name if name in {"Gate A", "Security", "Arrivals Hall", "Departures"} else None)


# ---------------------------------------------------------------------------
# Module-level convenience: shared client instance
# ---------------------------------------------------------------------------

_shared_client: Optional[RemoteAPIClient] = None


def get_shared_client() -> Optional[RemoteAPIClient]:
    """Return the shared RemoteAPIClient instance (if started)."""
    return _shared_client


def start_shared_client(
    base_url: str,
    on_new_frame: Callable[[Dict[str, Any], List[Dict], Optional[str], Dict], None],
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> RemoteAPIClient:
    """
    Create and start a module-level shared client.

    If one is already running, it is stopped first.
    """
    global _shared_client
    if _shared_client and _shared_client.is_alive():
        _shared_client.stop()

    _shared_client = RemoteAPIClient(
        base_url=base_url,
        on_new_frame=on_new_frame,
        poll_interval=poll_interval,
    )
    _shared_client.start()
    return _shared_client


def stop_shared_client() -> None:
    """Stop the shared client if running."""
    global _shared_client
    if _shared_client:
        _shared_client.stop()
        _shared_client = None
