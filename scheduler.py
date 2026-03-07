"""
scheduler.py – AeroVision Schedule Manager
============================================
Provides dynamic, time-window-based assignment of check-in counters to
flights, replacing the previous hardcoded ``associated_counters`` lists.

Design overview
---------------
``ScheduleEntry``
    A dataclass holding the counter IDs, start time, and end time for a
    single flight's check-in window.

``ScheduleManager``
    Maintains a registry of ``ScheduleEntry`` records keyed by flight ID.
    On every pipeline cycle the engine calls :meth:`~ScheduleManager.update_assignments`,
    which evaluates each entry against the current wall-clock time and
    writes the result directly into each :class:`~models.Flight` object:

    * **Active window** (``start_time ≤ current_time ≤ end_time``):
      ``flight.associated_counters`` is set to the entry's counter ID list.
    * **Outside window**: ``flight.associated_counters`` is cleared to ``[]``.

    Flights that have no registered entry are left untouched so that manual
    overrides (e.g. from an ops supervisor) survive across cycles.

Integration point
-----------------
``Engine`` calls ``ScheduleManager.update_assignments()`` as **step 0** of
the :meth:`~engine.Engine.run` pipeline, before AI payloads are processed,
so every downstream step (correlations, optimisations) already sees
up-to-date counter assignments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from models import Flight


# ---------------------------------------------------------------------------
# ScheduleEntry
# ---------------------------------------------------------------------------

@dataclass
class ScheduleEntry:
    """
    Immutable schedule record for a single flight's check-in window.

    Attributes:
        counter_ids (list[str]): Ordered list of counter IDs that handle
            this flight's check-in (e.g. ``["03", "05"]``).
        start_time (datetime):   Moment check-in opens for this flight.
        end_time (datetime):     Moment check-in closes (counter assignment
            is cleared after this point).

    Raises:
        ValueError: On construction if ``end_time`` is not strictly after
            ``start_time``, or if ``counter_ids`` contains duplicates.
    """

    counter_ids: List[str]
    start_time: datetime
    end_time: datetime

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ValueError(
                f"end_time ({self.end_time.isoformat()}) must be strictly after "
                f"start_time ({self.start_time.isoformat()})."
            )
        if len(self.counter_ids) != len(set(self.counter_ids)):
            raise ValueError(
                f"counter_ids contains duplicates: {self.counter_ids!r}."
            )

    # ------------------------------------------------------------------

    def is_active(self, current_time: datetime) -> bool:
        """
        Return ``True`` if *current_time* falls within the scheduled window
        (inclusive on both boundaries).

        Args:
            current_time: The timestamp to evaluate against.
        """
        return self.start_time <= current_time <= self.end_time

    def to_dict(self, current_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Serialise to a dictionary.

        Args:
            current_time: When provided, an ``"active"`` boolean key is
                included in the result.

        Returns:
            Dictionary with ``counter_ids``, ``start_time``, ``end_time``
            (both as ISO-8601 strings), and optionally ``active``.
        """
        result: Dict[str, Any] = {
            "counter_ids": list(self.counter_ids),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
        }
        if current_time is not None:
            result["active"] = self.is_active(current_time)
        return result


# ---------------------------------------------------------------------------
# ScheduleManager
# ---------------------------------------------------------------------------

class ScheduleManager:
    """
    Registry and assignment engine for flight-to-counter schedules.

    Typical lifecycle::

        sm = ScheduleManager()

        sm.register("DL789", ["03"], start_time=t0, end_time=t1)
        sm.register("UA456", ["04"], start_time=t2, end_time=t3)

        # Called once per engine cycle:
        assignment_log = sm.update_assignments(flights, datetime.now())

    Attributes:
        _schedule (dict): Internal mapping of ``flight_id → ScheduleEntry``.
    """

    def __init__(self) -> None:
        self._schedule: Dict[str, ScheduleEntry] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        flight_id: str,
        counter_ids: List[str],
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """
        Add or overwrite the schedule entry for a flight.

        Calling ``register`` on an already-registered flight replaces the
        previous entry; this is intentional (supports schedule updates from
        a DCS without requiring an explicit remove/re-add).

        Args:
            flight_id:   IATA-style flight code, e.g. ``"DL789"``.
            counter_ids: Ordered list of counter IDs assigned to this flight.
                         May be empty (e.g. flight not yet assigned counters).
            start_time:  Datetime when check-in opens.
            end_time:    Datetime when check-in closes.

        Raises:
            ValueError: If ``flight_id`` is blank, ``end_time <= start_time``,
                        or ``counter_ids`` contains duplicate entries.
        """
        flight_id = flight_id.strip()
        if not flight_id:
            raise ValueError("flight_id must be a non-empty string.")

        # ScheduleEntry.__post_init__ validates time ordering and duplicates
        self._schedule[flight_id] = ScheduleEntry(
            counter_ids=list(counter_ids),
            start_time=start_time,
            end_time=end_time,
        )

    def remove(self, flight_id: str) -> bool:
        """
        Remove the schedule entry for a flight.

        Args:
            flight_id: Flight to deregister.

        Returns:
            ``True`` if the entry existed and was removed; ``False`` if the
            flight had no registered entry.
        """
        if flight_id in self._schedule:
            del self._schedule[flight_id]
            return True
        return False

    def get_entry(self, flight_id: str) -> Optional[ScheduleEntry]:
        """
        Look up the schedule entry for a specific flight.

        Args:
            flight_id: Flight to look up.

        Returns:
            The :class:`ScheduleEntry` if registered, otherwise ``None``.
        """
        return self._schedule.get(flight_id)

    # ------------------------------------------------------------------
    # Dynamic assignment (called each pipeline cycle)
    # ------------------------------------------------------------------

    def update_assignments(
        self,
        flights: List[Flight],
        current_time: datetime,
    ) -> Dict[str, List[str]]:
        """
        Evaluate every registered flight against *current_time* and update
        each :class:`~models.Flight`'s ``associated_counters`` list in-place.

        Algorithm
        ---------
        For each flight in *flights*:

        1. Look up its entry in ``_schedule``.
        2. **No entry**: leave ``associated_counters`` unchanged (preserves
           any manual override).
        3. **Entry found, window active** (``start ≤ now ≤ end``):
           replace ``associated_counters`` with the entry's counter ID list.
        4. **Entry found, window expired or not yet started**:
           clear ``associated_counters`` to ``[]``.

        Args:
            flights:      All :class:`~models.Flight` objects managed by the
                          engine.
            current_time: The reference timestamp to evaluate windows against.
                          Pass ``datetime.now()`` for real-time operation or a
                          fixed datetime for testing / replay.

        Returns:
            Assignment log: mapping of ``flight_id → counter_ids`` reflecting
            the state *after* this update.  Flights without registered entries
            are omitted from the log.

        Example::

            log = sm.update_assignments(engine.flights, datetime.now())
            # {"DL789": ["03"], "UA456": []}
        """
        log: Dict[str, List[str]] = {}

        for flight in flights:
            entry = self._schedule.get(flight.id)
            if entry is None:
                # No schedule registered – do not touch the flight
                continue

            if entry.is_active(current_time):
                flight.associated_counters = list(entry.counter_ids)
            else:
                flight.associated_counters = []

            log[flight.id] = list(flight.associated_counters)

        return log

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self, current_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Serialise all registered entries.

        Args:
            current_time: When provided, each entry dict will include an
                ``"active"`` boolean.

        Returns:
            Dict keyed by flight ID, values are serialised
            :class:`ScheduleEntry` dicts.

        Example output::

            {
              "DL789": {
                "counter_ids": ["03"],
                "start_time": "2026-03-07T11:30:00",
                "end_time":   "2026-03-07T14:15:00",
                "active":     true
              },
              "UA456": { … }
            }
        """
        return {
            fid: entry.to_dict(current_time)
            for fid, entry in self._schedule.items()
        }

    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of registered schedule entries."""
        return len(self._schedule)

    def __repr__(self) -> str:
        return f"ScheduleManager(entries={len(self._schedule)})"
