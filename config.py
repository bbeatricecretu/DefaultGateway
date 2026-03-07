"""
config.py – AeroVision Configuration Constants
================================================
Central place for all system-wide thresholds, labels, and defaults.
Importing modules should treat these as read-only at runtime.
"""

from typing import Final

# ---------------------------------------------------------------------------
# Application metadata
# ---------------------------------------------------------------------------
APP_VERSION: Final[str] = "v1.0-alpha"
SYSTEM_STATUS: Final[str] = "SYSTEM ACTIVE"

# ---------------------------------------------------------------------------
# Risk classification thresholds (queue size in pax)
# ---------------------------------------------------------------------------
QUEUE_HIGH_RISK_THRESHOLD: Final[int] = 15       # >= this  → "High"
QUEUE_MEDIUM_RISK_THRESHOLD: Final[int] = 8      # >= this  → "Medium"
                                                  # < medium → "Low"

# ---------------------------------------------------------------------------
# Flow-rate thresholds (pax / minute)
# ---------------------------------------------------------------------------
FLOW_RATE_LOW_THRESHOLD: Final[float] = 1.5      # Below this triggers extra-agent rule

# ---------------------------------------------------------------------------
# Clearance-time thresholds (minutes)
# ---------------------------------------------------------------------------
CLEARANCE_TIME_HIGH_RISK: Final[float] = 30.0    # > this → clearance critically slow
CLEARANCE_TIME_MEDIUM_RISK: Final[float] = 15.0  # > this → clearance moderately slow

# Forecast delay: if estimated clearance exceeds this, flag delayed forecast
FORECAST_DELAY_THRESHOLD: Final[float] = 15.0    # minutes

# ---------------------------------------------------------------------------
# Special-item processing overhead
# ---------------------------------------------------------------------------
# Each special item (stroller, wheelchair, child, oversized bag) adds a
# flat processing penalty on top of the queue's base clearance time.
SPECIAL_ITEM_PENALTY_MINUTES: Final[float] = 2.0  # minutes per special item

# ---------------------------------------------------------------------------
# Optimization rules
# ---------------------------------------------------------------------------
# Minimum queue-size difference between two counters before suggesting
# a staff reallocation between them.
QUEUE_REALLOCATION_THRESHOLD: Final[int] = 10    # pax

# Minimum special-items count at a counter before suggesting a dedicated lane.
SPECIAL_ITEMS_LANE_THRESHOLD: Final[int] = 3

# ---------------------------------------------------------------------------
# Flight timing
# ---------------------------------------------------------------------------
# Passengers must finish check-in at least this many minutes before departure.
BOARDING_WINDOW_MINUTES: Final[float] = 30.0

# ---------------------------------------------------------------------------
# Baseline averages (used for computing deltas / percentage changes)
# ---------------------------------------------------------------------------
DEFAULT_THROUGHPUT_AVG: Final[int] = 140          # pax/hr  – historical terminal avg
DEFAULT_CLEARANCE_AVG_SECONDS: Final[float] = 207.0  # seconds – 3 m 27 s baseline

# ---------------------------------------------------------------------------
# Live feeds
# ---------------------------------------------------------------------------
LIVE_FEEDS_ACTIVE: Final[int] = 2
