"""
engine.py – AeroVision Correlation & Optimisation Engine
=========================================================
The ``Engine`` is the central orchestrator.  It owns the registry of
:class:`~models.Counter` and :class:`~models.Flight` objects, drives the
full processing pipeline, and produces a dashboard-ready output dict.

Pipeline (in order)
-------------------
0. :meth:`_refresh_assignments`  – ask the :class:`~scheduler.ScheduleManager`
   (if attached) to update every flight's ``associated_counters`` list based
   on the current time and registered schedule windows.
1. :meth:`process_inputs`        – push raw AI payloads into counters.
2. :meth:`generate_correlations` – correlate counter states with flights.
3. :meth:`suggest_optimizations` – apply rule-based optimisation logic.
4. :meth:`get_full_output`       – aggregate everything into one dict.

The convenience :meth:`run` method executes all five steps in sequence.

Optimisation rules implemented
-------------------------------
R1 – Staff reallocation:
    When the queue size difference between two counters exceeds
    ``QUEUE_REALLOCATION_THRESHOLD``, suggest moving an agent from the
    lighter counter to the busier one.

R2 – Special items lane:
    When a counter has more than ``SPECIAL_ITEMS_LANE_THRESHOLD`` special
    items, suggest opening a dedicated handling lane.

R3 – Additional agent for high-risk / low-flow counters:
    When a "High" risk counter's flow rate falls below
    ``FLOW_RATE_LOW_THRESHOLD``, suggest deploying an extra agent.

R4 – Flight deadline criticality:
    When a flight is flagged as ``at_risk`` (forecasted clearance exceeds the
    boarding window), suggest opening a dedicated relief counter so the
    affected passengers can clear check-in before the gate closes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from config import (
    FLOW_RATE_LOW_THRESHOLD,
    LIVE_FEEDS_ACTIVE,
    QUEUE_REALLOCATION_THRESHOLD,
    SPECIAL_ITEMS_LANE_THRESHOLD,
)
from models import Counter, Flight, Optimization, SystemMetrics
from processor import CounterProcessor
from scheduler import ScheduleManager
from utils import (
    compute_avg_clearance,
    compute_clearance_delta_seconds,
    compute_throughput,
    compute_throughput_change_pct,
    format_delta_seconds,
    format_minutes_to_str,
    get_current_timestamp,
)


class Engine:
    """
    Central orchestration engine for AeroVision.

    Attributes:
        counters (list[Counter]):        Registered check-in counters.
        flights (list[Flight]):          Registered flights under monitoring.
        optimizations (list[Optimization]): Latest set of generated suggestions.
        system_metrics (SystemMetrics):  Latest aggregated terminal KPIs.
    """

    def __init__(self) -> None:
        self.counters: List[Counter] = []
        self.flights: List[Flight] = []
        self.optimizations: List[Optimization] = []
        self.system_metrics: SystemMetrics = SystemMetrics()
        self._processor: CounterProcessor = CounterProcessor()
        self._scheduler: Optional[ScheduleManager] = None

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def add_counter(self, counter: Counter) -> None:
        """
        Register a :class:`~models.Counter` with the engine.

        Args:
            counter: Counter instance to track.

        Raises:
            TypeError:  If ``counter`` is not a ``Counter`` instance.
            ValueError: If a counter with the same ID is already registered.
        """
        if not isinstance(counter, Counter):
            raise TypeError(
                f"Expected a Counter instance, got {type(counter).__name__!r}."
            )
        existing_ids = {c.id for c in self.counters}
        if counter.id in existing_ids:
            raise ValueError(
                f"Counter with ID {counter.id!r} is already registered."
            )
        self.counters.append(counter)

    def add_flight(self, flight: Flight) -> None:
        """
        Register a :class:`~models.Flight` with the engine.

        Args:
            flight: Flight instance to track.

        Raises:
            TypeError:  If ``flight`` is not a ``Flight`` instance.
            ValueError: If a flight with the same ID is already registered.
        """
        if not isinstance(flight, Flight):
            raise TypeError(
                f"Expected a Flight instance, got {type(flight).__name__!r}."
            )
        existing_ids = {f.id for f in self.flights}
        if flight.id in existing_ids:
            raise ValueError(
                f"Flight with ID {flight.id!r} is already registered."
            )
        self.flights.append(flight)

    # ------------------------------------------------------------------
    # Scheduler attachment
    # ------------------------------------------------------------------

    def set_scheduler(self, scheduler: ScheduleManager) -> None:
        """
        Attach a :class:`~scheduler.ScheduleManager` to this engine.

        Once attached, the scheduler's
        :meth:`~scheduler.ScheduleManager.update_assignments` is invoked
        automatically at the start of every :meth:`run` call, ensuring
        that ``flight.associated_counters`` is always derived from the
        current time and registered schedule windows — never from
        hardcoded values.

        To detach, call ``engine.set_scheduler(None)`` or simply replace
        with a new instance.

        Args:
            scheduler: A configured :class:`~scheduler.ScheduleManager`
                       instance (or ``None`` to detach).

        Raises:
            TypeError: If *scheduler* is neither a ``ScheduleManager``
                       nor ``None``.
        """
        if scheduler is not None and not isinstance(scheduler, ScheduleManager):
            raise TypeError(
                f"Expected a ScheduleManager instance or None, "
                f"got {type(scheduler).__name__!r}."
            )
        self._scheduler = scheduler

    # ------------------------------------------------------------------
    # Pipeline step 0 – refresh schedule-based counter assignments
    # ------------------------------------------------------------------

    def _refresh_assignments(self, current_time: Optional[datetime] = None) -> Dict[str, List[str]]:
        """
        Ask the attached :class:`~scheduler.ScheduleManager` to re-evaluate
        every flight's check-in window and update ``associated_counters``
        accordingly.

        Called internally by :meth:`run` before any other pipeline step so
        that correlations and optimisations always operate on up-to-date
        counter assignments.

        Args:
            current_time: Reference timestamp to pass to the scheduler.
                          Defaults to ``datetime.now()`` when ``None``,
                          but can be overridden for testing / replay.

        Returns:
            The assignment log from
            :meth:`~scheduler.ScheduleManager.update_assignments`
            (``flight_id → counter_ids``), or an empty dict when no
            scheduler is attached.
        """
        if self._scheduler is None:
            return {}
        return self._scheduler.update_assignments(
            self.flights,
            current_time if current_time is not None else datetime.now(),
        )

    # ------------------------------------------------------------------
    # Pipeline step 1 – process AI inputs
    # ------------------------------------------------------------------

    def process_inputs(
        self, payloads: Dict[str, Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        Validate and apply incoming AI vision payloads to registered counters.

        Args:
            payloads: Mapping of ``counter_id → ai_data`` dict.

        Returns:
            Per-counter success mapping (``True`` = updated successfully).
        """
        self._processor.clear_errors()
        return self._processor.process_all(self.counters, payloads)

    # ------------------------------------------------------------------
    # Pipeline step 2 – generate flight correlations
    # ------------------------------------------------------------------

    def generate_correlations(self) -> None:
        """
        Correlate every registered flight's departure window against the
        current clearance forecasts of its associated counters.

        Mutates each :class:`~models.Flight` in-place (sets ``at_risk``,
        ``risk_description``, and ``issue``).
        """
        for flight in self.flights:
            flight.correlate_with_counters(self.counters)

    # ------------------------------------------------------------------
    # Pipeline step 3 – suggest optimisations
    # ------------------------------------------------------------------

    def suggest_optimizations(self) -> None:
        """
        Apply rule-based optimisation logic and populate ``self.optimizations``.

        Rules evaluated (see module docstring for full descriptions):

        * **R1** – Staff reallocation between counters with unequal queues.
        * **R2** – Dedicated lane for counters with many special items.
        * **R3** – Extra agent for high-risk, low-flow-rate counters.

        The list is fully rebuilt on every call; stale suggestions are
        discarded.
        """
        self.optimizations.clear()

        # ---- R1: Staff reallocation ------------------------------------------
        for i, c1 in enumerate(self.counters):
            for c2 in self.counters[i + 1:]:
                diff = abs(c1.queue_size - c2.queue_size)
                if diff < QUEUE_REALLOCATION_THRESHOLD:
                    continue

                busy = c1 if c1.queue_size > c2.queue_size else c2
                idle = c2 if busy is c1 else c1

                # Estimated impact scales with the size of the imbalance,
                # capped at 65 %.
                raw_impact = 40.0 + (diff - QUEUE_REALLOCATION_THRESHOLD) * 1.5
                impact = round(min(raw_impact, 65.0), 1)

                self.optimizations.append(
                    Optimization(
                        action="Reallocate Staff",
                        details=(
                            f"Shift 1 agent from Counter {idle.id} ({idle.type}) "
                            f"to Counter {busy.id} ({busy.type}) to balance load. "
                            f"Estimated delay reduction: {impact:.0f}%."
                        ),
                        estimated_impact=impact,
                        actionable=True,
                    )
                )

        # ---- R2: Special items lane ------------------------------------------
        for counter in self.counters:
            if counter.special_items > SPECIAL_ITEMS_LANE_THRESHOLD:
                self.optimizations.append(
                    Optimization(
                        action="Open Special Items Lane",
                        details=(
                            f"Counter {counter.id} ({counter.type}) has "
                            f"{counter.special_items} special items detected "
                            "(strollers / wheelchairs / unaccompanied minors). "
                            "Open a dedicated handling lane to reduce per-passenger "
                            "processing overhead."
                        ),
                        estimated_impact=25.0,
                        actionable=True,
                    )
                )

        # ---- R3: Additional agent for high-risk / slow counters --------------
        for counter in self.counters:
            if (
                counter.get_risk_level() == "High"
                and counter.flow_rate < FLOW_RATE_LOW_THRESHOLD
            ):
                self.optimizations.append(
                    Optimization(
                        action="Deploy Additional Agent",
                        details=(
                            f"Counter {counter.id} ({counter.type}) has a critical "
                            f"queue ({counter.queue_size} pax) and a low flow rate "
                            f"({counter.flow_rate:.1f} pax/min). "
                            "Deploy an additional check-in agent immediately to "
                            "accelerate queue clearance."
                        ),
                        estimated_impact=30.0,
                        actionable=True,
                    )
                )

        # ---- R4: Flight deadline criticality --------------------------------
        for flight in self.flights:
            if flight.at_risk:
                counters_str = ", ".join(flight.associated_counters)
                self.optimizations.append(
                    Optimization(
                        action=f"Open Relief Counter ({flight.id})",
                        details=(
                            f"Flight {flight.id} is critical. Passengers are stuck "
                            f"in queues at counters [{counters_str}]. Open a dedicated "
                            "relief counter immediately to ensure passengers clear "
                            "security before the gate closes."
                        ),
                        estimated_impact=50.0,
                        actionable=True,
                    )
                )

    # ------------------------------------------------------------------
    # Pipeline step 4 – aggregate system metrics
    # ------------------------------------------------------------------

    def _compute_system_metrics(self) -> None:
        """
        Aggregate per-counter and per-flight states into ``self.system_metrics``.

        Called internally by :meth:`get_full_output`; not typically called
        directly by external code.
        """
        # Terminal throughput
        counters_data = [{"flow_rate": c.flow_rate} for c in self.counters]
        throughput = compute_throughput(counters_data)
        throughput_change = compute_throughput_change_pct(throughput)

        # Average clearance time
        clearance_times = [c.get_clearance_minutes() for c in self.counters]
        avg_clearance = compute_avg_clearance(clearance_times)
        delta_sec = compute_clearance_delta_seconds(avg_clearance)

        # Risk tallies
        critical_bottlenecks = sum(
            1 for c in self.counters if c.get_risk_level() == "High"
        )
        flights_at_risk = sum(1 for f in self.flights if f.at_risk)
        action_required = critical_bottlenecks > 0 or flights_at_risk > 0

        self.system_metrics = SystemMetrics(
            throughput=throughput,
            throughput_change_pct=throughput_change,
            avg_clearance_time=format_minutes_to_str(avg_clearance),
            avg_clearance_delta=format_delta_seconds(delta_sec),
            critical_bottlenecks=critical_bottlenecks,
            flights_at_risk=flights_at_risk,
            timestamp=get_current_timestamp(),
            live_feeds_active=LIVE_FEEDS_ACTIVE,
            action_required=action_required,
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def get_full_output(self) -> Dict[str, Any]:
        """
        Build and return the complete dashboard-ready output dictionary.

        Internally refreshes system metrics before serialising.

        Returns:
            Dict with the following top-level keys:

            * ``"system_metrics"``  – :class:`~models.SystemMetrics` fields.
            * ``"counters"``        – list of per-counter dicts.
            * ``"flights"``         – list of per-flight dicts.
            * ``"optimizations"``   – list of optimisation suggestion dicts.
            * ``"processing_errors"`` – list of error strings from the processor.

        This structure is designed for direct consumption by a REST API
        endpoint or a Streamlit / Flask rendering layer.
        """
        self._compute_system_metrics()

        now = datetime.now()
        return {
            "system_metrics": self.system_metrics.to_dict(),
            "counters": [c.to_dict() for c in self.counters],
            "flights": [f.to_dict() for f in self.flights],
            "optimizations": [o.to_dict() for o in self.optimizations],
            "processing_errors": self._processor.get_errors(),
            "schedule": (
                self._scheduler.to_dict(now)
                if self._scheduler is not None
                else {}
            ),
        }

    # ------------------------------------------------------------------
    # Convenience: full pipeline in one call
    # ------------------------------------------------------------------

    def run(self, payloads: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute the complete AeroVision pipeline in a single call.

        Steps::

            _refresh_assignments()   [step 0 – schedule-based counter assignment]
              → process_inputs(payloads)
              → generate_correlations()
              → suggest_optimizations()
              → get_full_output()  [also refreshes system metrics]

        Args:
            payloads: Mapping of ``counter_id → ai_data`` dict (from AI system).

        Returns:
            Full output dict (same structure as :meth:`get_full_output`).
        """
        self._refresh_assignments()
        self.process_inputs(payloads)
        self.generate_correlations()
        self.suggest_optimizations()
        return self.get_full_output()

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Engine(counters={len(self.counters)}, "
            f"flights={len(self.flights)}, "
            f"optimizations={len(self.optimizations)})"
        )
