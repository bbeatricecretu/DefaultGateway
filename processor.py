"""
processor.py – AeroVision Counter Processor
=============================================
Responsible for validating and applying raw AI vision payloads to
:class:`~models.Counter` objects.

Design
------
``CounterProcessor`` is intentionally lightweight — it delegates all
domain logic to :class:`~models.Counter` itself.  Its responsibilities are:

1. Validate each incoming payload via :func:`~utils.validate_ai_payload`.
2. Route each validated payload to the correct ``Counter`` instance.
3. Accumulate and expose per-run error diagnostics.

This separation keeps ``Counter`` free of I/O concerns and makes
``CounterProcessor`` easy to unit-test in isolation.
"""

from __future__ import annotations

from typing import Dict, List, Any

from models import Counter
from utils import validate_ai_payload


# Keys that every AI payload sent for a counter must provide.
REQUIRED_AI_KEYS: frozenset = frozenset(
    {"queue_size", "flow_rate", "avg_baggage", "special_items"}
)


class CounterProcessor:
    """
    Validates and applies AI vision system payloads to ``Counter`` objects.

    Typical usage::

        processor = CounterProcessor()
        results = processor.process_all(counters, payloads)

        if processor.has_errors():
            for err in processor.get_errors():
                print(err)

    Attributes:
        _errors (list[str]): Accumulated error messages from the current run.
    """

    def __init__(self) -> None:
        self._errors: List[str] = []

    # ------------------------------------------------------------------
    # Primary processing interface
    # ------------------------------------------------------------------

    def process_counter(self, counter: Counter, ai_data: Dict[str, Any]) -> bool:
        """
        Validate an AI payload and update a single :class:`~models.Counter`.

        Steps:

        1. Structural / numeric validation via :func:`~utils.validate_ai_payload`.
        2. Delegate update to :meth:`~models.Counter.update_from_ai_data`.
        3. On any failure, record an error and return ``False``.

        Args:
            counter: The counter to update.
            ai_data: Raw dict from the AI vision system.

        Returns:
            ``True`` on success, ``False`` if validation or update failed.
        """
        is_valid, error_msg = validate_ai_payload(ai_data, REQUIRED_AI_KEYS)
        if not is_valid:
            self._record_error(counter.id, f"Payload validation failed – {error_msg}")
            return False

        try:
            counter.update_from_ai_data(ai_data)
        except (ValueError, TypeError) as exc:
            self._record_error(counter.id, f"Update failed – {exc}")
            return False

        return True

    def process_all(
        self,
        counters: List[Counter],
        payloads: Dict[str, Dict[str, Any]],
    ) -> Dict[str, bool]:
        """
        Process AI payloads for a collection of counters in one call.

        Payloads are matched to counters by counter ID.  Payloads for
        unknown counter IDs are skipped with an error recorded.

        Args:
            counters: All registered :class:`~models.Counter` objects.
            payloads: Mapping of ``counter_id → ai_data`` dict.

        Returns:
            Mapping of ``counter_id → success_bool`` for every payload key
            that was processed.

        Example::

            results = processor.process_all(counters, {
                "03": {"queue_size": 18, "flow_rate": 1.2,
                       "avg_baggage": 2.8, "special_items": 4},
                "04": {"queue_size": 2, "flow_rate": 3.5,
                       "avg_baggage": 1.1, "special_items": 0},
            })
            # results → {"03": True, "04": True}
        """
        counter_map: Dict[str, Counter] = {c.id: c for c in counters}
        results: Dict[str, bool] = {}

        for counter_id, ai_data in payloads.items():
            if counter_id not in counter_map:
                self._record_error(
                    counter_id,
                    "Counter ID not found in registered counters. Payload skipped.",
                )
                results[counter_id] = False
                continue

            results[counter_id] = self.process_counter(
                counter_map[counter_id], ai_data
            )

        return results

    # ------------------------------------------------------------------
    # Error management
    # ------------------------------------------------------------------

    def _record_error(self, counter_id: str, message: str) -> None:
        """Append a formatted error entry to the internal error list."""
        self._errors.append(f"[Counter {counter_id}] {message}")

    def has_errors(self) -> bool:
        """Return ``True`` if any errors were recorded during the last run."""
        return bool(self._errors)

    def get_errors(self) -> List[str]:
        """Return a copy of all accumulated error messages."""
        return list(self._errors)

    def clear_errors(self) -> None:
        """Reset the error list (call before starting a new processing cycle)."""
        self._errors.clear()

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CounterProcessor(errors={len(self._errors)}, "
            f"required_keys={sorted(REQUIRED_AI_KEYS)})"
        )
