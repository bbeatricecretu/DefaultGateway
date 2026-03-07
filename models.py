"""
models.py – AeroVision Core Data Models
========================================
Defines the primary domain objects used throughout the system:

    SystemMetrics   – Terminal-level KPIs shown at the top of the dashboard.
    Queue           – Passenger queue composed inside a Counter.
    Counter         – A single check-in counter (base entity, AI-data driven).
    Flight          – A flight whose check-in health is correlated with counters.
    Optimization    – A single actionable suggestion produced by the engine.

Design principles
-----------------
* Encapsulation  – each class owns its state and exposes clean accessors.
* Composition    – Counter *has-a* Queue (not inheritance).
* Serialisation  – every class provides ``to_dict()`` for JSON / API output.
* Validation     – invalid data raises ``ValueError`` at the point of entry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import (
    APP_VERSION,
    BOARDING_WINDOW_MINUTES,
    FORECAST_DELAY_THRESHOLD,
    LIVE_FEEDS_ACTIVE,
    QUEUE_HIGH_RISK_THRESHOLD,
    QUEUE_MEDIUM_RISK_THRESHOLD,
    SPECIAL_ITEM_PENALTY_MINUTES,
    SYSTEM_STATUS,
)


# ---------------------------------------------------------------------------
# SystemMetrics
# ---------------------------------------------------------------------------

class SystemMetrics:
    """
    Aggregated terminal-level KPIs rendered at the top of the dashboard.

    Attributes:
        throughput (int):              Total pax processed per hour across the terminal.
        throughput_change_pct (float): % change vs. historical average (+/- float).
        avg_clearance_time (str):      Human-readable average clearance time, e.g. "4m 12s".
        avg_clearance_delta (str):     Signed delta vs. baseline, e.g. "+45s" or "-12s".
        critical_bottlenecks (int):    Number of counters flagged "High" risk.
        flights_at_risk (int):         Number of flights whose boarding may be impacted.
        app_version (str):             Application version string.
        system_status (str):           Operational status label.
        timestamp (str):               Snapshot timestamp, e.g. "3/7/2026 02:02 PM".
        live_feeds_active (int):       Number of active AI video feeds.
        action_required (bool):        True when at least one counter or flight is critical.
    """

    def __init__(
        self,
        throughput: int = 0,
        throughput_change_pct: float = 0.0,
        avg_clearance_time: str = "0m 00s",
        avg_clearance_delta: str = "+0s",
        critical_bottlenecks: int = 0,
        flights_at_risk: int = 0,
        app_version: str = APP_VERSION,
        system_status: str = SYSTEM_STATUS,
        timestamp: str = "",
        live_feeds_active: int = LIVE_FEEDS_ACTIVE,
        action_required: bool = False,
    ) -> None:
        self.throughput: int = throughput
        self.throughput_change_pct: float = throughput_change_pct
        self.avg_clearance_time: str = avg_clearance_time
        self.avg_clearance_delta: str = avg_clearance_delta
        self.critical_bottlenecks: int = critical_bottlenecks
        self.flights_at_risk: int = flights_at_risk
        self.app_version: str = app_version
        self.system_status: str = system_status
        self.timestamp: str = timestamp
        self.live_feeds_active: int = live_feeds_active
        self.action_required: bool = action_required

    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a flat dictionary suitable for JSON output."""
        return {
            "throughput": self.throughput,
            "throughput_change_pct": self.throughput_change_pct,
            "avg_clearance_time": self.avg_clearance_time,
            "avg_clearance_delta": self.avg_clearance_delta,
            "critical_bottlenecks": self.critical_bottlenecks,
            "flights_at_risk": self.flights_at_risk,
            "app_version": self.app_version,
            "system_status": self.system_status,
            "timestamp": self.timestamp,
            "live_feeds_active": self.live_feeds_active,
            "action_required": self.action_required,
        }

    def __repr__(self) -> str:
        return (
            f"SystemMetrics(throughput={self.throughput} pax/hr, "
            f"bottlenecks={self.critical_bottlenecks}, "
            f"flights_at_risk={self.flights_at_risk})"
        )


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

class Queue:
    """
    Models the passenger queue at a single check-in counter.

    Composed *inside* :class:`Counter` — not used standalone.

    Attributes:
        size (int):       Number of passengers currently waiting.
        flow_rate (float): Clearance rate in passengers per minute.
    """

    def __init__(self, size: int = 0, flow_rate: float = 1.0) -> None:
        """
        Initialise a Queue.

        Args:
            size:      Number of passengers in the queue (must be ≥ 0).
            flow_rate: Rate at which passengers are processed (must be > 0).

        Raises:
            ValueError: If ``size`` is negative or ``flow_rate`` is not positive.
        """
        if size < 0:
            raise ValueError(f"Queue size cannot be negative; received {size!r}.")
        if flow_rate <= 0.0:
            raise ValueError(
                f"Flow rate must be strictly positive; received {flow_rate!r}."
            )
        self.size: int = size
        self.flow_rate: float = flow_rate

    # ------------------------------------------------------------------

    def estimate_clearance_minutes(self, special_item_count: int = 0) -> float:
        """
        Estimate how long (in minutes) the queue will take to fully clear.

        Formula::

            clearance = (queue_size / flow_rate)
                      + (special_item_count × SPECIAL_ITEM_PENALTY_MINUTES)

        Args:
            special_item_count: Number of special items (strollers, wheelchairs,
                                unaccompanied minors, oversized baggage, …).

        Returns:
            Estimated clearance time in fractional minutes.
        """
        base_time: float = self.size / self.flow_rate
        penalty: float = special_item_count * SPECIAL_ITEM_PENALTY_MINUTES
        return base_time + penalty

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to dictionary."""
        return {"size": self.size, "flow_rate": self.flow_rate}

    def __repr__(self) -> str:
        return f"Queue(size={self.size}, flow_rate={self.flow_rate}/min)"


# ---------------------------------------------------------------------------
# Counter
# ---------------------------------------------------------------------------

class Counter:
    """
    Represents a single airport check-in counter.

    Composes a :class:`Queue` and stores all AI-derived per-counter metrics.
    After every :meth:`update_from_ai_data` call the forecast is recomputed
    automatically.

    Attributes:
        id (str):             Counter identifier, e.g. ``"03"``, ``"04"``.
        type (str):           Counter category, e.g. ``"Int'l"``, ``"Domestic"``.
        queue (Queue):        Composed queue object.
        avg_baggage (float):  Average checked-bag count per passenger.
        special_items (int):  Detected special items (strollers, wheelchairs, …).
        forecast (str):       Latest human-readable clearance forecast.
    """

    def __init__(self, counter_id: str, counter_type: str) -> None:
        """
        Initialise a Counter with identity fields; metrics start at zero.

        Args:
            counter_id:   Unique counter identifier string.
            counter_type: Descriptive type label.
        """
        if not counter_id or not counter_id.strip():
            raise ValueError("counter_id must be a non-empty string.")
        if not counter_type or not counter_type.strip():
            raise ValueError("counter_type must be a non-empty string.")

        self.id: str = counter_id.strip()
        self.type: str = counter_type.strip()
        self.queue: Queue = Queue(size=0, flow_rate=1.0)
        self.avg_baggage: float = 0.0
        self.special_items: int = 0
        self.forecast: str = ""
        self._clearance_minutes: float = 0.0  # cached after compute_forecast()

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def queue_size(self) -> int:
        """Current number of passengers in queue (read-only alias)."""
        return self.queue.size

    @property
    def flow_rate(self) -> float:
        """Current queue flow rate in pax/min (read-only alias)."""
        return self.queue.flow_rate

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def update_from_ai_data(self, data: Dict[str, Any]) -> None:
        """
        Ingest a raw AI vision payload and update this counter's state.

        Expected payload keys (all required)::

            {
                "queue_size":    int   – number of detected passengers,
                "flow_rate":     float – pax/min clearance rate,
                "avg_baggage":   float – average bags per passenger,
                "special_items": int   – strollers / wheelchairs / kids detected
            }

        Automatically calls :meth:`compute_forecast` after updating state.

        Args:
            data: Dict payload from the upstream AI system.

        Raises:
            ValueError: If required keys are absent or values are out of range.
            TypeError:  If a value cannot be converted to the expected type.
        """
        required = {"queue_size", "flow_rate", "avg_baggage", "special_items"}
        missing = required - set(data.keys())
        if missing:
            raise ValueError(
                f"Counter {self.id}: AI payload missing required keys: "
                f"{sorted(missing)}"
            )

        # Cast & validate
        try:
            queue_size = int(data["queue_size"])
            flow_rate = float(data["flow_rate"])
            avg_baggage = float(data["avg_baggage"])
            special_items = int(data["special_items"])
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"Counter {self.id}: Type conversion failed in AI payload – {exc}"
            ) from exc

        if queue_size < 0:
            raise ValueError(
                f"Counter {self.id}: 'queue_size' must be ≥ 0, got {queue_size}."
            )
        if flow_rate <= 0.0:
            raise ValueError(
                f"Counter {self.id}: 'flow_rate' must be > 0, got {flow_rate}."
            )
        if avg_baggage < 0.0:
            raise ValueError(
                f"Counter {self.id}: 'avg_baggage' must be ≥ 0, got {avg_baggage}."
            )
        if special_items < 0:
            raise ValueError(
                f"Counter {self.id}: 'special_items' must be ≥ 0, got {special_items}."
            )

        # Commit state
        self.queue = Queue(size=queue_size, flow_rate=flow_rate)
        self.avg_baggage = avg_baggage
        self.special_items = special_items

        # Refresh derived metrics
        self.compute_forecast()

    def compute_forecast(self) -> str:
        """
        Derive a human-readable clearance forecast and cache the clearance time.

        Logic::

            clearance = queue.estimate_clearance_minutes(special_items)

            if clearance > FORECAST_DELAY_THRESHOLD:
                warn about delay; report excess over threshold as impact
            elif clearance > 5:
                report moderate queue with exact time
            else:
                on track; report exact time

        Returns:
            The forecast string (also stored in ``self.forecast``).
        """
        clearance = self.queue.estimate_clearance_minutes(self.special_items)
        self._clearance_minutes = clearance

        if clearance > FORECAST_DELAY_THRESHOLD:
            impact = int(round(clearance - FORECAST_DELAY_THRESHOLD))
            self.forecast = (
                f"Queue clearance delayed. "
                f"Est. +{impact}m impact on boarding."
            )
        elif clearance > 5.0:
            mins = int(clearance)
            secs = int((clearance - mins) * 60)
            self.forecast = (
                f"Moderate queue. Est. {mins}m {secs:02d}s to clear."
            )
        else:
            mins = int(clearance)
            secs = int((clearance - mins) * 60)
            self.forecast = f"Queue on track. Est. {mins}m {secs:02d}s to clear."

        return self.forecast

    def get_risk_level(self) -> str:
        """
        Classify this counter's risk based on queue size.

        Thresholds (from ``config.py``)::

            queue_size >= QUEUE_HIGH_RISK_THRESHOLD   → "High"
            queue_size >= QUEUE_MEDIUM_RISK_THRESHOLD → "Medium"
            otherwise                                 → "Low"

        Returns:
            One of ``"High"``, ``"Medium"``, or ``"Low"``.
        """
        if self.queue.size >= QUEUE_HIGH_RISK_THRESHOLD:
            return "High"
        if self.queue.size >= QUEUE_MEDIUM_RISK_THRESHOLD:
            return "Medium"
        return "Low"

    def get_clearance_minutes(self) -> float:
        """Return the most recently computed clearance time in minutes."""
        return self._clearance_minutes

    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialise the counter to a flat dictionary for JSON/API output.

        Includes all dashboard-relevant fields.
        """
        return {
            "id": self.id,
            "type": self.type,
            "queue_size": self.queue.size,
            "flow_rate": self.queue.flow_rate,
            "avg_baggage": self.avg_baggage,
            "special_items": self.special_items,
            "forecast": self.forecast,
            "risk_level": self.get_risk_level(),
            "clearance_minutes": round(self._clearance_minutes, 2),
        }

    def __repr__(self) -> str:
        return (
            f"Counter(id={self.id!r}, type={self.type!r}, "
            f"queue={self.queue.size} pax, risk={self.get_risk_level()})"
        )


# ---------------------------------------------------------------------------
# Flight
# ---------------------------------------------------------------------------

class Flight:
    """
    Represents a scheduled or arrived flight whose check-in health is tracked.

    Correlates departure timing against the current state of associated
    check-in counters to determine boarding risk.

    Attributes:
        id (str):                     IATA-style flight identifier, e.g. ``"DL789"``.
        status (str):                 Display status, e.g. ``"DEPARTS 45M"`` / ``"LANDED"``.
        minutes_to_departure (float): Minutes until wheels-up (``None`` if already departed
                                      or landed).
        associated_counters (list):   List of counter IDs handling this flight's pax.
        risk_description (str):       Generated description of boarding risk, if any.
        issue (str):                  Short issue label, e.g. ``"ISSUE: BOARDING HOLD"``.
        expectation (str):            Forward-looking transfer/inbound expectation text.
        at_risk (bool):               ``True`` when at least one counter is predicted to miss
                                      the boarding window.
    """

    def __init__(
        self,
        flight_id: str,
        status: str,
        minutes_to_departure: Optional[float] = None,
        expectation: str = "",
    ) -> None:
        """
        Initialise a Flight.

        Args:
            flight_id:             Unique flight code.
            status:                Human-readable status string.
            minutes_to_departure:  Minutes until departure; ``None`` for landed flights.
            expectation:           Optional forward-looking expectation narrative.

        Raises:
            ValueError: If ``flight_id`` is empty, or ``minutes_to_departure`` is
                        provided but negative.
        """
        if not flight_id or not flight_id.strip():
            raise ValueError("flight_id must be a non-empty string.")
        if minutes_to_departure is not None and minutes_to_departure < 0:
            raise ValueError(
                f"minutes_to_departure cannot be negative; got {minutes_to_departure}."
            )

        self.id: str = flight_id.strip()
        self.status: str = status
        self.minutes_to_departure: Optional[float] = minutes_to_departure
        self.associated_counters: List[str] = []
        self.risk_description: str = ""
        self.issue: str = ""
        self.expectation: str = expectation
        self.at_risk: bool = False

    # ------------------------------------------------------------------

    def correlate_with_counters(self, counters: List[Counter]) -> None:
        """
        Update this flight's risk state by comparing counter clearance forecasts
        against the remaining boarding window.

        Boarding window = ``minutes_to_departure − BOARDING_WINDOW_MINUTES``
        (passengers must clear check-in before boarding closes).

        If any associated counter's estimated clearance time exceeds the
        boarding window, the flight is flagged at risk.

        Args:
            counters: All :class:`Counter` objects managed by the engine.
                      Only those whose ``id`` appears in
                      ``self.associated_counters`` are evaluated.
        """
        self.at_risk = False
        risk_parts: List[str] = []

        for counter in counters:
            if counter.id not in self.associated_counters:
                continue

            clearance = counter.get_clearance_minutes()

            if self.minutes_to_departure is None:
                # Flight already landed / no departure window to evaluate
                continue

            boarding_window = self.minutes_to_departure - BOARDING_WINDOW_MINUTES

            if clearance > boarding_window:
                self.at_risk = True
                risk_parts.append(
                    f"{counter.queue.size} passengers for {self.id} stuck in "
                    f"Counter {counter.id} queue. "
                    f"Forecasted clearance exceeds boarding window."
                )

        if self.at_risk:
            self.risk_description = " ".join(risk_parts)
            self.issue = "ISSUE: BOARDING HOLD"
        else:
            self.risk_description = ""
            self.issue = ""

    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialise this flight to a dictionary for JSON/API output.

        The ``"description"`` key mirrors ``"risk_description"`` to match
        the dashboard's field naming convention.
        """
        return {
            "id": self.id,
            "status": self.status,
            "associated_counters": self.associated_counters,
            "description": self.risk_description,
            "issue": self.issue,
            "expectation": self.expectation,
            "at_risk": self.at_risk,
            "minutes_to_departure": self.minutes_to_departure,
        }

    def __repr__(self) -> str:
        return (
            f"Flight(id={self.id!r}, status={self.status!r}, "
            f"at_risk={self.at_risk})"
        )


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------

class Optimization:
    """
    Encapsulates a single rule-based operational optimisation suggestion.

    Attributes:
        action (str):            Short action label shown as the card title,
                                 e.g. ``"Reallocate Staff"``.
        details (str):           Full description of what should be done and
                                 the expected benefit.
        estimated_impact (float): Estimated delay reduction as a percentage,
                                  e.g. ``40.0`` means ~40 % reduction.
        actionable (bool):       ``True`` when the action can be executed
                                 immediately (maps to the dashboard's
                                 *Execute* button state).
    """

    def __init__(
        self,
        action: str,
        details: str,
        estimated_impact: float,
        actionable: bool = True,
    ) -> None:
        """
        Initialise an Optimization.

        Args:
            action:           Short action label.
            details:          Full descriptive text.
            estimated_impact: Delay-reduction percentage (0–100).
            actionable:       Whether the action is immediately executable.

        Raises:
            ValueError: If ``estimated_impact`` is outside [0, 100].
        """
        if not 0.0 <= estimated_impact <= 100.0:
            raise ValueError(
                f"estimated_impact must be between 0 and 100; "
                f"got {estimated_impact}."
            )

        self.action: str = action
        self.details: str = details
        self.estimated_impact: float = estimated_impact
        self.actionable: bool = actionable

    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to dictionary for JSON/API output."""
        return {
            "action": self.action,
            "details": self.details,
            "estimated_impact": self.estimated_impact,
            "actionable": self.actionable,
        }

    def __repr__(self) -> str:
        return (
            f"Optimization(action={self.action!r}, "
            f"impact={self.estimated_impact:.1f}%, "
            f"actionable={self.actionable})"
        )
