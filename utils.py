"""
utils.py – AeroVision Utility / Helper Functions
=================================================
Pure functions for time formatting, risk scoring, throughput calculations,
payload validation, and other reusable logic consumed by the rest of the
backend.  No classes live here; no side-effects on global state.
"""

from datetime import datetime
from typing import Dict, List, Tuple

from config import (
    DEFAULT_CLEARANCE_AVG_SECONDS,
    DEFAULT_THROUGHPUT_AVG,
    QUEUE_HIGH_RISK_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Time / formatting helpers
# ---------------------------------------------------------------------------

def format_minutes_to_str(total_minutes: float) -> str:
    """
    Convert a floating-point minutes value to a human-readable string.

    Args:
        total_minutes: Duration in minutes (may be fractional).

    Returns:
        Formatted string, e.g. ``"4m 12s"``.

    Examples::

        >>> format_minutes_to_str(4.2)
        '4m 12s'
        >>> format_minutes_to_str(0.0)
        '0m 00s'
    """
    total_seconds = int(round(total_minutes * 60))
    mins, secs = divmod(abs(total_seconds), 60)
    return f"{mins}m {secs:02d}s"


def format_delta_seconds(delta_seconds: int) -> str:
    """
    Format a signed seconds value as a delta string for dashboard display.

    Args:
        delta_seconds: Positive means slower than baseline, negative means faster.

    Returns:
        String like ``"+45s"`` or ``"-12s"``.

    Examples::

        >>> format_delta_seconds(45)
        '+45s'
        >>> format_delta_seconds(-12)
        '-12s'
    """
    sign = "+" if delta_seconds >= 0 else ""
    return f"{sign}{delta_seconds}s"


def format_timestamp(dt: datetime) -> str:
    """
    Format a :class:`datetime` object for dashboard display.

    Args:
        dt: The datetime to format.

    Returns:
        String like ``"3/7/2026 02:02 PM"``.
    """
    return f"{dt.month}/{dt.day}/{dt.year} {dt.strftime('%I:%M %p')}"


def get_current_timestamp() -> str:
    """
    Return the **current system time** formatted for dashboard display.

    Returns:
        Timestamp string, e.g. ``"3/7/2026 02:15 PM"``.
    """
    return format_timestamp(datetime.now())


# ---------------------------------------------------------------------------
# Throughput helpers
# ---------------------------------------------------------------------------

def compute_throughput(counters_data: List[Dict]) -> int:
    """
    Compute overall terminal throughput in passengers per hour.

    Formula: ``throughput = Σ(flow_rate_i) × 60``

    Each counter's ``flow_rate`` (pax/min) is summed, then scaled to pax/hr.

    Args:
        counters_data: List of dicts, each containing at least a ``"flow_rate"``
                       key (float, pax/min).

    Returns:
        Terminal throughput rounded to the nearest integer (pax/hr).

    Raises:
        TypeError: If ``counters_data`` is not iterable.
    """
    total_per_min: float = sum(
        float(c.get("flow_rate", 0.0)) for c in counters_data
    )
    return int(round(total_per_min * 60.0))


def compute_throughput_change_pct(
    current: int,
    baseline: int = DEFAULT_THROUGHPUT_AVG,
) -> float:
    """
    Compute the percentage change of current throughput from a baseline.

    Args:
        current:  Measured throughput (pax/hr).
        baseline: Reference average throughput (pax/hr).

    Returns:
        Signed percentage change rounded to one decimal place,
        e.g. ``+1.2`` means 1.2 % above baseline.
        Returns ``0.0`` when baseline is zero.
    """
    if baseline == 0:
        return 0.0
    return round(((current - baseline) / baseline) * 100.0, 1)


# ---------------------------------------------------------------------------
# Clearance-time helpers
# ---------------------------------------------------------------------------

def compute_avg_clearance(clearance_times: List[float]) -> float:
    """
    Compute the mean clearance time across a set of counters.

    Args:
        clearance_times: Per-counter estimated clearance times in minutes.

    Returns:
        Average clearance time in minutes, or ``0.0`` for an empty list.
    """
    if not clearance_times:
        return 0.0
    return sum(clearance_times) / len(clearance_times)


def compute_clearance_delta_seconds(
    avg_minutes: float,
    baseline_seconds: float = DEFAULT_CLEARANCE_AVG_SECONDS,
) -> int:
    """
    Compute the signed delta (in seconds) between the current average clearance
    time and the historical baseline.

    Args:
        avg_minutes:      Current average clearance time in minutes.
        baseline_seconds: Baseline clearance time in seconds (default ≈ 3m 27s).

    Returns:
        Signed integer difference in seconds.  Positive ⇒ slower than baseline.
    """
    current_seconds = avg_minutes * 60.0
    return int(round(current_seconds - baseline_seconds))


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

def compute_risk_score(
    queue_size: int,
    special_items: int,
    flow_rate: float,
) -> float:
    """
    Compute a normalised risk score in the range **[0.0, 1.0]**.

    Formula::

        base      = min(queue_size / HIGH_RISK_THRESHOLD, 1.0)
        penalty_s = min(special_items × 0.05, 0.20)      # ≤ 20 pp
        penalty_f = max(0, (1.5 − flow_rate) × 0.10)     # slow-flow penalty
        score     = clamp(base + penalty_s + penalty_f, 0, 1)

    Args:
        queue_size:    Number of passengers in the queue.
        special_items: Count of special items (strollers, wheelchairs, …).
        flow_rate:     Processing rate in pax/min.

    Returns:
        Risk score float between 0.0 (no risk) and 1.0 (maximum risk).
    """
    base_score: float = min(queue_size / QUEUE_HIGH_RISK_THRESHOLD, 1.0)
    special_penalty: float = min(special_items * 0.05, 0.20)
    flow_penalty: float = max(0.0, (1.5 - flow_rate) * 0.10)
    return round(min(base_score + special_penalty + flow_penalty, 1.0), 4)


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

def validate_ai_payload(
    data: Dict,
    required_keys: set,
) -> Tuple[bool, str]:
    """
    Validate that an incoming AI vision payload contains the expected keys
    and that numeric fields hold valid values.

    Checked numeric rules:
    * ``queue_size``  – must be a non-negative integer-compatible number.
    * ``flow_rate``   – must be a strictly positive number.
    * ``avg_baggage`` – must be a non-negative number.
    * ``special_items`` – must be a non-negative integer-compatible number.

    Args:
        data:          Raw dict payload from the AI system.
        required_keys: Set of key names that must be present.

    Returns:
        ``(True, "")`` if valid.
        ``(False, "<reason>")`` if a problem is detected.
    """
    # --- Presence check ---------------------------------------------------
    missing = required_keys - set(data.keys())
    if missing:
        return False, f"Missing required keys: {sorted(missing)}"

    # --- Type / value checks for known numeric fields ---------------------
    numeric_rules: Dict[str, Dict] = {
        "queue_size":    {"type": (int, float), "min": 0,    "strict": False},
        "flow_rate":     {"type": (int, float), "min": 0,    "strict": True},
        "avg_baggage":   {"type": (int, float), "min": 0,    "strict": False},
        "special_items": {"type": (int, float), "min": 0,    "strict": False},
    }

    for key, rules in numeric_rules.items():
        if key not in required_keys:
            continue
        val = data.get(key)
        try:
            num = float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False, f"'{key}' must be numeric, got {type(val).__name__!r}"

        if rules["strict"] and num <= rules["min"]:
            return False, f"'{key}' must be > {rules['min']}, got {num}"
        if not rules["strict"] and num < rules["min"]:
            return False, f"'{key}' must be >= {rules['min']}, got {num}"

    return True, ""
