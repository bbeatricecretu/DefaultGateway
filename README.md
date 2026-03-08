# AeroVision — Technical Reference

> **AeroVision** is an AI-assisted airport terminal operations platform.  
> It ingests real-time queue and baggage data from computer-vision cameras, processes it through a rule-based optimisation engine, and surfaces actionable warnings, risk assessments, and staff-deployment suggestions on a live React dashboard.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Structure](#2-repository-structure)
3. [Technology Stack](#3-technology-stack)
   - [Backend](#31-backend)
   - [Frontend](#32-frontend)
4. [Data Ingestion — How Data Is Fetched](#4-data-ingestion--how-data-is-fetched)
   - [Mock Mode](#41-mock-mode-default)
   - [HTTP Snapshot Mode](#42-http-snapshot-mode)
   - [WebSocket Stream Mode](#43-websocket-stream-mode)
   - [Live / Remote API Mode](#44-live--remote-api-mode)
5. [AI Payload Format](#5-ai-payload-format)
6. [Processing Pipeline — Step by Step](#6-processing-pipeline--step-by-step)
   - [Step 0 — Schedule Refresh](#step-0--schedule-refresh)
   - [Step 1 — Counter Processor](#step-1--counter-processor)
   - [Step 2 — Queue Clearance Forecast](#step-2--queue-clearance-forecast)
   - [Step 3 — Risk Classification](#step-3--risk-classification)
   - [Step 4 — Flight Correlation](#step-4--flight-correlation)
   - [Step 5 — Optimisation Rules](#step-5--optimisation-rules)
   - [Step 6 — System Metrics Aggregation](#step-6--system-metrics-aggregation)
7. [Risk Scoring Algorithm](#7-risk-scoring-algorithm)
8. [Warnings, Risks, and Suggestions — Full Logic](#8-warnings-risks-and-suggestions--full-logic)
9. [Dashboard Parameter Reference](#9-dashboard-parameter-reference)
   - [system_metrics](#91-system_metrics)
   - [counters](#92-counters-array)
   - [flights](#93-flights-array)
   - [optimizations](#94-optimizations-array)
   - [schedule](#95-schedule-object)
   - [processing_errors](#96-processing_errors-array)
10. [Configuration Constants](#10-configuration-constants)
11. [REST API Reference](#11-rest-api-reference)
12. [Environment Variables](#12-environment-variables)
13. [Running the Project](#13-running-the-project)
14. [Frontend Dashboard Components](#14-frontend-dashboard-components)

---

## 1. System Overview

AeroVision sits between an upstream AI computer-vision system (which performs object detection on camera feeds) and the operations staff managing airport check-in terminals. It does **not** run neural networks itself. Instead, it receives pre-processed structured metrics per camera zone, feeds them through a deterministic rule-based engine, and produces a continuously updated JSON dashboard payload.

```
┌─────────────────────────┐      structured JSON       ┌───────────────────────┐
│  AI Vision System       │ ─────────────────────────▶ │   AeroVision Backend  │
│  (camera detection,     │   {queue_size, flow_rate,  │   (Flask + Engine)    │
│   YOLOv8 / custom)      │    avg_baggage,            │                       │
└─────────────────────────┘    special_items}           │  • CounterProcessor   │
                                                        │  • ScheduleManager    │
                                                        │  • Engine             │
                                                        │  • Rule Evaluator     │
                                                        └──────────┬────────────┘
                                                                   │ JSON (SSE / REST)
                                                                   ▼
                                                        ┌───────────────────────┐
                                                        │  React Frontend       │
                                                        │  (Vite + Three.js)    │
                                                        │                       │
                                                        │  • MetricsRow         │
                                                        │  • CounterCards       │
                                                        │  • FlightPanel        │
                                                        │  • SuggestionsPanel   │
                                                        │  • AlertsPanel        │
                                                        │  • TerminalMap (3D)   │
                                                        └───────────────────────┘
```

---

## 2. Repository Structure

```
DefaultGateway/
├── app.py                  # Flask REST API server & SSE endpoint
├── engine.py               # Central orchestration engine
├── models.py               # Domain models: Counter, Flight, Queue, Optimization, SystemMetrics
├── processor.py            # AI payload validation and counter update logic
├── scheduler.py            # Time-window-based flight-to-counter assignment
├── utils.py                # Pure helper functions: formatting, scoring, validation
├── config.py               # All system-wide thresholds and constants
├── main.py                 # CLI entry point (mock / HTTP / WebSocket modes)
├── mock_snapshot4.py       # Mock snapshot data for development
├── extract_zones.py        # Zone extraction utility for camera images
├── floor_plan.png          # Terminal floor plan image
├── yolov8n.pt              # YOLOv8 nano model weights (used by upstream vision system)
├── cameras/                # Camera zone subdirectories with frame snapshots
│   ├── Arrivals_Hall/
│   ├── Departures/
│   ├── Gate_A/
│   └── Security/
├── datasets/               # Training / test datasets for the vision model
├── snapshots4/             # Snapshot frames (dataset 4)
├── src/
│   ├── api_client.py       # RemoteAPIClient (background polling thread)
│   ├── config_camere.json  # Camera zone configuration
│   ├── static/             # Static assets served by backend
│   ├── templates/          # Jinja2 HTML templates
│   └── web_app.py          # Secondary web app entry point
├── static/                 # Flask static assets
├── templates/              # Flask Jinja2 templates
└── frontend/               # React + Vite dashboard
    ├── index.html
    ├── package.json
    └── src/
        ├── App.jsx
        ├── hooks/
        │   └── useSSE.js   # SSE connection hook
        ├── components/
        │   ├── Header.jsx
        │   ├── MetricsRow.jsx
        │   ├── CounterCard.jsx
        │   ├── CameraFeed.jsx
        │   ├── AlertsPanel.jsx
        │   ├── FlightPanel.jsx
        │   ├── SuggestionsPanel.jsx
        │   ├── TerminalMap.jsx  # 3D terminal map using Three.js
        │   └── Timeline.jsx
        └── data/
```

---

## 3. Technology Stack

### 3.1 Backend

| Tool / Library | Version | Role |
|---|---|---|
| **Python** | 3.10+ | Core language |
| **Flask** | ≥ 3.x | REST API server, SSE endpoint, static file serving |
| **flask-cors** | — | Cross-Origin Resource Sharing headers for the frontend |
| **requests** | — | HTTP polling in `RemoteAPIClient` (`src/api_client.py`) |
| **websockets** | optional | WebSocket stream mode in `main.py` |
| **urllib.request** | stdlib | HTTP snapshot fetch in `main.py` |
| **threading** | stdlib | Background polling thread in `RemoteAPIClient` |
| **dataclasses** | stdlib | `ScheduleEntry` immutable record |
| **typing** | stdlib | Type annotations throughout |
| **YOLOv8n** | ultralytics | Model weights file (`yolov8n.pt`) stored in the repository for reference. The detection itself is performed by the **external** upstream AI vision system — AeroVision does not execute this model directly. |

### 3.2 Frontend

| Tool / Library | Version | Role |
|---|---|---|
| **React** | 19.x | UI component framework |
| **Vite** | 7.x | Development server and production bundler |
| **Three.js** | 0.183.x | 3D interactive terminal map (`TerminalMap` component) |
| **ESLint** | 9.x | Code linting |
| **@vitejs/plugin-react** | 5.x | React fast-refresh support in Vite |

---

## 4. Data Ingestion — How Data Is Fetched

The engine is completely **data-source agnostic**. The same processing pipeline runs regardless of where the data comes from. The data source is selected via the `DATA_SOURCE` environment variable (or the constant in `main.py`).

### 4.1 Mock Mode (default)

**Trigger:** `DATA_SOURCE=mock` (or unset)

Hardcoded counter payloads are used directly. This mode requires no external dependencies and is the default for local development and testing.

```python
# Example mock payload (from app.py / main.py)
{
    "Gate A":       {"queue_size": 18, "flow_rate": 1.2, "avg_baggage": 2.8, "special_items": 4},
    "Security":     {"queue_size": 12, "flow_rate": 2.1, "avg_baggage": 1.5, "special_items": 3},
    "Arrivals Hall":{"queue_size": 5,  "flow_rate": 3.0, "avg_baggage": 1.2, "special_items": 1},
    "Departures":   {"queue_size": 8,  "flow_rate": 2.5, "avg_baggage": 1.8, "special_items": 2},
}
```

### 4.2 HTTP Snapshot Mode

**Trigger:** `DATA_SOURCE=http`

A single JSON snapshot is pulled via a synchronous HTTP GET from `AI_VISION_URL` (default: `http://localhost:8080/snapshot`). The response must contain a `"counters"` key whose value is a dict keyed by counter ID.

```json
{
  "counters": {
    "Gate A": {"queue_size": 18, "flow_rate": 1.2, "avg_baggage": 2.8, "special_items": 4},
    "Security": {"queue_size": 2, "flow_rate": 3.5, "avg_baggage": 1.1, "special_items": 0}
  }
}
```

The request uses a 5-second timeout. On failure a `RuntimeError` is raised and logged, and the API returns HTTP 500.

### 4.3 WebSocket Stream Mode

**Trigger:** `DATA_SOURCE=websocket`

Requires the third-party `websockets` package (`pip install websockets`). The adapter connects to `AI_VISION_URL` (converted to `ws://` / `wss://`) and processes every incoming frame immediately as it arrives. Each WebSocket message must be JSON with the same `"counters"` structure as the HTTP mode.

This mode **blocks** the calling thread. In production it should be run in a dedicated thread or async task. Each processed frame's full dashboard output is written to stdout as a JSON line, allowing a downstream consumer (Streamlit, Redis, SSE forwarder) to pick it up.

### 4.4 Live / Remote API Mode

**Trigger:** `DATA_SOURCE=live`

The `RemoteAPIClient` (`src/api_client.py`) runs a **background polling thread** that continuously calls `GET /latest` on a remote airport-monitor API (default: `http://192.168.1.42:8000`). Key features:

- **Deduplication:** frames are deduplicated by `timestamp` + `snapshot_id`; identical frames are silently skipped.
- **"No data" detection:** frames carrying sentinel values (`"no data"`, `"no_data"`, `"empty"`, `"unavailable"`) are ignored.
- **Exponential backoff:** consecutive network errors trigger increasing wait times, capped at 30 seconds.
- **Payload normalisation:** the client handles three response shapes from the remote API:
  1. `"counters"` dict keyed by camera name (preferred)
  2. `"detections"` list with per-camera entries
  3. Flat top-level camera keys (`"Gate A"`, `"Security"`, etc.)
- **Camera name normalisation:** variant spellings (`gate_a`, `GateA`, `arrivals_hall`, etc.) are mapped to canonical counter names.
- **Image URL:** the absolute URL of the latest camera snapshot is forwarded to the frontend for display in the `CameraFeed` component.

The backend exposes a **Server-Sent Events (SSE)** endpoint (`GET /api/live`) that streams dashboard updates to the React frontend in real time without polling.

---

## 5. AI Payload Format

Every data source must produce payloads in this counter-keyed format before data is passed to the engine:

```json
{
  "<counter_id>": {
    "queue_size":    18,
    "flow_rate":     1.2,
    "avg_baggage":   2.8,
    "special_items": 4
  }
}
```

| Field | Type | Unit | Description |
|---|---|---|---|
| `queue_size` | `int` | passengers | Number of passengers currently detected in the queue lane |
| `flow_rate` | `float` | pax / min | Rate at which passengers are being processed through the counter. Must be **strictly > 0**. |
| `avg_baggage` | `float` | bags / pax | Average number of checked bags per passenger |
| `special_items` | `int` | count | Number of special-handling items detected: strollers, wheelchairs, unaccompanied minors, oversized bags |

**Validation rules** enforced by `CounterProcessor` (via `utils.validate_ai_payload`):

- All four keys must be present.
- `queue_size` ≥ 0 (integer-compatible)
- `flow_rate` > 0 (strictly positive)
- `avg_baggage` ≥ 0
- `special_items` ≥ 0 (integer-compatible)

Any violation records an error in `processing_errors` and skips the counter update for that cycle.

---

## 6. Processing Pipeline — Step by Step

The `Engine.run(payloads)` method executes all steps in sequence on every request:

```
engine.run(payloads)
  │
  ├── Step 0: _refresh_assignments()    ← ScheduleManager
  ├── Step 1: process_inputs(payloads)  ← CounterProcessor
  ├── Step 2: generate_correlations()   ← Flight risk evaluation
  ├── Step 3: suggest_optimizations()   ← Rule engine (R1–R4)
  └── Step 4: get_full_output()         ← Aggregation + serialisation
                └── _compute_system_metrics()
```

### Step 0 — Schedule Refresh

**File:** `scheduler.py` → `ScheduleManager.update_assignments()`

The `ScheduleManager` holds a registry of `ScheduleEntry` records, one per flight. Each entry specifies:
- `counter_ids`: which counters handle this flight's check-in
- `start_time`: when check-in opens
- `end_time`: when check-in closes

On every pipeline cycle the manager evaluates each entry against `datetime.now()`:

| Condition | Result |
|---|---|
| `start_time ≤ now ≤ end_time` (window active) | `flight.associated_counters` ← entry's counter IDs |
| Window expired or not yet started | `flight.associated_counters` ← `[]` |
| No entry registered for this flight | Flight is left untouched (preserves manual overrides) |

This ensures that all downstream steps (correlation, optimisation) always operate on up-to-date counter assignments without any hardcoded lists.

### Step 1 — Counter Processor

**File:** `processor.py` → `CounterProcessor.process_all()`

For each counter ID in the incoming payload:
1. The payload is validated (see [AI Payload Format](#5-ai-payload-format)).
2. On success, `Counter.update_from_ai_data()` is called to commit the new state.
3. On failure, an error string is appended to `processing_errors` and the counter retains its previous state.

After updating, every counter immediately recomputes its **clearance forecast** (Step 2).

### Step 2 — Queue Clearance Forecast

**File:** `models.py` → `Counter.compute_forecast()`

The clearance time for a counter is estimated as:

```
clearance_minutes = (queue_size / flow_rate) + (special_items × SPECIAL_ITEM_PENALTY_MINUTES)
```

Where `SPECIAL_ITEM_PENALTY_MINUTES = 2.0` minutes per special item (stroller, wheelchair, etc.).

The forecast text is then categorised:

| Clearance time | Forecast text | Meaning |
|---|---|---|
| `> FORECAST_DELAY_THRESHOLD` (15 min) | `"Queue clearance delayed. Est. +Xm impact on boarding."` | Queue will not clear before boarding; delay impact in minutes shown |
| `> 5 min` | `"Moderate queue. Est. Xm XXs to clear."` | Queue is building but manageable |
| `≤ 5 min` | `"Queue on track. Est. Xm XXs to clear."` | Queue is flowing normally |

### Step 3 — Risk Classification

**File:** `models.py` → `Counter.get_risk_level()`

Counter risk level is determined solely by `queue_size` against two thresholds from `config.py`:

| Condition | Risk Level |
|---|---|
| `queue_size >= QUEUE_HIGH_RISK_THRESHOLD` (15 pax) | **High** 🔴 |
| `queue_size >= QUEUE_MEDIUM_RISK_THRESHOLD` (8 pax) | **Medium** 🟡 |
| Otherwise | **Low** 🟢 |

### Step 4 — Flight Correlation

**File:** `models.py` → `Flight.correlate_with_counters()`

Each flight is evaluated against all counters listed in its `associated_counters`:

```
boarding_window = minutes_to_departure − BOARDING_WINDOW_MINUTES (30 min)

for each associated counter:
    if counter.clearance_minutes > boarding_window:
        flight.at_risk = True
        flight.issue   = "ISSUE: BOARDING HOLD"
        flight.risk_description += "<N> passengers for <flight> stuck in Counter <X> queue. Forecasted clearance exceeds boarding window."
```

**Landed flights** (`minutes_to_departure = None`) are never flagged at risk since there is no departure window to evaluate.

### Step 5 — Optimisation Rules

**File:** `engine.py` → `Engine.suggest_optimizations()`

Four rule categories are evaluated on every cycle. See [Section 8](#8-warnings-risks-and-suggestions--full-logic) for full details.

### Step 6 — System Metrics Aggregation

**File:** `engine.py` → `Engine._compute_system_metrics()`

Terminal-level KPIs are aggregated from counter and flight states:

| Metric | Calculation |
|---|---|
| `throughput` | `Σ(flow_rate_i) × 60` — sum of all counter flow rates scaled to pax/hr |
| `throughput_change_pct` | `((throughput − DEFAULT_THROUGHPUT_AVG) / DEFAULT_THROUGHPUT_AVG) × 100` |
| `avg_clearance_time` | Mean of all counter clearance times, formatted as `"Xm XXs"` |
| `avg_clearance_delta` | `avg_clearance_seconds − DEFAULT_CLEARANCE_AVG_SECONDS`, formatted as `"+XXs"` |
| `critical_bottlenecks` | Count of counters with `risk_level == "High"` |
| `flights_at_risk` | Count of flights with `at_risk == True` |
| `action_required` | `True` if `critical_bottlenecks > 0` OR `flights_at_risk > 0` |

---

## 7. Risk Scoring Algorithm

**File:** `utils.py` → `compute_risk_score()`

A normalised risk score in `[0.0, 1.0]` is computed per counter using three factors:

```
base_score    = min(queue_size / QUEUE_HIGH_RISK_THRESHOLD, 1.0)
special_penalty = min(special_items × 0.05, 0.20)        # capped at 0.20 (20 pp)
flow_penalty    = max(0.0, (1.5 − flow_rate) × 0.10)     # only applied when flow_rate < 1.5

risk_score = clamp(base_score + special_penalty + flow_penalty, 0.0, 1.0)
```

| Component | Description |
|---|---|
| `base_score` | Proportion of the high-risk queue threshold that is currently filled. A queue of 15 pax (= threshold) scores 1.0. |
| `special_penalty` | Each special item adds 0.05 to the score, up to a maximum of 0.20. Reflects the processing overhead of strollers, wheelchairs, and similar items. |
| `flow_penalty` | Only activates when `flow_rate < 1.5 pax/min` (below `FLOW_RATE_LOW_THRESHOLD`). A critically slow counter (e.g. 0.5 pax/min) contributes 0.10 additional risk. |

This score is used internally for trend analysis. The dashboard displays the categorical `risk_level` ("High" / "Medium" / "Low") for clarity.

---

## 8. Warnings, Risks, and Suggestions — Full Logic

### Counter Warnings (Forecast Text)

Generated by `Counter.compute_forecast()` after every AI data update. A warning is surfaced on the `CounterCard` component when `clearance_minutes > FORECAST_DELAY_THRESHOLD` (15 min):

> *"Queue clearance delayed. Est. +Xm impact on boarding."*

The `+Xm` figure is `round(clearance_minutes − 15)` — the number of minutes the queue is predicted to overflow the acceptable clearance window.

### Flight Risk Flags

Generated by `Flight.correlate_with_counters()`. A flight becomes `at_risk = True` when any of its assigned counters has a clearance forecast that exceeds the remaining boarding window:

> *"18 passengers for DL789 stuck in Counter Gate A queue. Forecasted clearance exceeds boarding window."*

The `issue` field is set to `"ISSUE: BOARDING HOLD"`. This triggers a visual alert on the `FlightPanel` component and increments `flights_at_risk` in system metrics.

### Optimisation Suggestions (R1 – R4)

Generated by `Engine.suggest_optimizations()`. The full list is rebuilt on every cycle.

#### R1 — Staff Reallocation

**Trigger:** The queue size difference between any two counters exceeds `QUEUE_REALLOCATION_THRESHOLD` (10 pax).

**Impact formula:**
```
raw_impact = 40.0 + (diff − QUEUE_REALLOCATION_THRESHOLD) × 1.5
impact     = min(raw_impact, 65.0)   # capped at 65 %
```

A difference of exactly 10 pax scores 40 % impact. Each additional passenger above the threshold adds 1.5 pp, up to a maximum of 65 %. The suggestion reads:

> *"Shift 1 agent from Counter [idle] ([type]) to Counter [busy] ([type]) to balance load. Estimated delay reduction: X%."*

#### R2 — Open Special Items Lane

**Trigger:** A counter has `special_items > SPECIAL_ITEMS_LANE_THRESHOLD` (3 items).

**Fixed impact:** 25 %.

> *"Counter [X] ([type]) has N special items detected (strollers / wheelchairs / unaccompanied minors). Open a dedicated handling lane to reduce per-passenger processing overhead."*

#### R3 — Deploy Additional Agent

**Trigger:** A counter has `risk_level == "High"` AND `flow_rate < FLOW_RATE_LOW_THRESHOLD` (1.5 pax/min).

**Fixed impact:** 30 %.

> *"Counter [X] ([type]) has a critical queue (N pax) and a low flow rate (F pax/min). Deploy an additional check-in agent immediately to accelerate queue clearance."*

#### R4 — Open Relief Counter

**Trigger:** A flight has `at_risk == True`.

**Fixed impact:** 50 %.

> *"Flight [ID] is critical. Passengers are stuck in queues at counters [list]. Open a dedicated relief counter immediately to ensure passengers clear security before the gate closes."*

---

## 9. Dashboard Parameter Reference

The `GET /api/dashboard` endpoint returns a single JSON object with the following top-level keys. All fields are described below.

### 9.1 `system_metrics`

Terminal-level KPIs displayed in the **MetricsRow** banner at the top of the dashboard.

| Parameter | Type | Example | Description |
|---|---|---|---|
| `throughput` | `int` | `282` | Total passengers processed per hour across the terminal. Calculated as the sum of all counter flow rates × 60. |
| `throughput_change_pct` | `float` | `+101.4` | Percentage change in throughput vs. the historical baseline (`DEFAULT_THROUGHPUT_AVG = 140 pax/hr`). Positive = above average. |
| `avg_clearance_time` | `string` | `"11m 47s"` | Mean queue clearance time across all active counters, formatted as `"Xm XXs"`. |
| `avg_clearance_delta` | `string` | `"+500s"` | Signed difference between current average clearance (in seconds) and the historical baseline (`DEFAULT_CLEARANCE_AVG_SECONDS ≈ 207 s = 3m 27s`). Positive = slower than baseline. |
| `critical_bottlenecks` | `int` | `1` | Number of counters currently classified as **High** risk (queue ≥ 15 pax). Drives the red alert indicator. |
| `flights_at_risk` | `int` | `1` | Number of flights whose boarding may be impacted due to slow counter clearance. |
| `live_feeds_active` | `int` | `2` | Number of AI camera feeds currently active and streaming data. Configured via `LIVE_FEEDS_ACTIVE` in `config.py`. |
| `action_required` | `bool` | `true` | `true` when at least one counter is a critical bottleneck **or** at least one flight is at risk. Triggers the warning banner and audible alert indicator in the UI. |
| `timestamp` | `string` | `"3/7/2026 02:13 PM"` | Wall-clock timestamp of when this dashboard snapshot was generated, formatted as `M/D/YYYY HH:MM AM/PM`. |
| `system_status` | `string` | `"SYSTEM ACTIVE"` | Operational status label shown in the header. Configured via `SYSTEM_STATUS` in `config.py`. |
| `app_version` | `string` | `"v1.0-alpha"` | Application version string from `APP_VERSION` in `config.py`. |

---

### 9.2 `counters` (array)

One object per registered check-in counter, displayed as **CounterCards** in the dashboard.

| Parameter | Type | Example | Description |
|---|---|---|---|
| `id` | `string` | `"Gate A"` | Unique counter identifier. Matches the camera zone name used in AI payloads. |
| `type` | `string` | `"Int'l"` | Counter category label (e.g. `"Int'l"`, `"Domestic"`, `"Departures"`, `"Security"`). |
| `queue_size` | `int` | `18` | Number of passengers currently detected in the queue lane. Sourced directly from the AI payload. |
| `flow_rate` | `float` | `1.2` | Current processing rate in passengers per minute. Sourced from AI payload. Drives clearance calculation and risk rules. |
| `throughput` | `int` | `72` | Per-counter passengers per hour: `round(flow_rate × 60)`. |
| `avg_baggage` | `float` | `2.8` | Average number of checked bags per passenger at this counter. Used as an operational indicator. |
| `special_items` | `int` | `4` | Count of special-handling items at this counter (strollers, wheelchairs, unaccompanied minors, oversized bags). Drives the `SPECIAL_ITEMS_LANE_THRESHOLD` rule and adds processing penalty to clearance time. |
| `forecast` | `string` | `"Queue clearance delayed. Est. +3m impact on boarding."` | Human-readable clearance forecast. See [Step 2](#step-2--queue-clearance-forecast) for full logic. |
| `risk_level` | `string` | `"High"` | Categorical risk classification: `"High"` 🔴, `"Medium"` 🟡, or `"Low"` 🟢. Based on `queue_size` thresholds. |
| `clearance_minutes` | `float` | `18.33` | Estimated minutes until the queue fully clears, including special-item penalties. Used by flight correlation logic. |

---

### 9.3 `flights` (array)

One object per monitored flight, displayed in the **FlightPanel**.

| Parameter | Type | Example | Description |
|---|---|---|---|
| `id` | `string` | `"DL789"` | IATA-style flight identifier. |
| `status` | `string` | `"DEPARTS 45M"` | Human-readable status shown on the flight card. Examples: `"DEPARTS 45M"`, `"DEPARTS 25M"`, `"LANDED"`. |
| `minutes_to_departure` | `float \| null` | `45.0` | Minutes until wheels-up. `null` for landed / arrived flights. Used as the input to boarding window calculation. |
| `associated_counters` | `string[]` | `["Gate A", "Departures"]` | Counter IDs currently assigned to handle this flight's passengers. Updated dynamically every cycle by the `ScheduleManager`. Empty when the check-in window is closed. |
| `at_risk` | `bool` | `true` | `true` when at least one associated counter's clearance forecast exceeds the boarding window (`minutes_to_departure − 30 min`). Triggers visual alert styling on the flight card. |
| `description` | `string` | `"18 passengers for DL789 stuck in Counter Gate A queue…"` | Detailed risk description generated by `Flight.correlate_with_counters()`. Empty string when `at_risk` is `false`. |
| `issue` | `string` | `"ISSUE: BOARDING HOLD"` | Short issue label shown as a badge on the flight card. Set to `"ISSUE: BOARDING HOLD"` when `at_risk` is `true`; empty otherwise. |
| `expectation` | `string` | `"JFK→LHR via Gate A7. Storm system approaching LHR…"` | Forward-looking operational note (transfer volume, weather, inbound status). Informational only; does not affect risk calculations. |

---

### 9.4 `optimizations` (array)

One object per generated suggestion, displayed in the **SuggestionsPanel**.

| Parameter | Type | Example | Description |
|---|---|---|---|
| `action` | `string` | `"Reallocate Staff"` | Short action label used as the suggestion card title. One of: `"Reallocate Staff"`, `"Open Special Items Lane"`, `"Deploy Additional Agent"`, `"Open Relief Counter (<flight_id>)"`. |
| `details` | `string` | `"Shift 1 agent from Counter Security (Security) to Counter Gate A (Int'l) to balance load. Estimated delay reduction: 52%."` | Full human-readable description of the recommended action, including which counters/flights are involved and the expected outcome. |
| `estimated_impact` | `float` | `52.0` | Estimated percentage reduction in passenger delay if the action is taken. Range: 0–100. Calculation differs by rule — see [Section 8](#8-warnings-risks-and-suggestions--full-logic). |
| `actionable` | `bool` | `true` | `true` when the action can be executed immediately by operations staff. Determines the active state of the **Execute** button in the UI. |

---

### 9.5 `schedule` (object)

Flight-to-counter schedule assignments, keyed by flight ID. Used by the **Timeline** and **FlightPanel** components.

```json
{
  "DL789": {
    "counter_ids": ["Gate A", "Departures"],
    "start_time":  "2026-03-07T12:00:00",
    "end_time":    "2026-03-07T14:15:00",
    "active":      true
  },
  "UA456": {
    "counter_ids": ["Arrivals Hall"],
    "start_time":  "2026-03-07T09:00:00",
    "end_time":    "2026-03-07T13:00:00",
    "active":      false
  }
}
```

| Parameter | Type | Description |
|---|---|---|
| `counter_ids` | `string[]` | Ordered list of counter IDs assigned to this flight's check-in window. |
| `start_time` | `string` | ISO-8601 datetime when check-in opens for this flight. |
| `end_time` | `string` | ISO-8601 datetime when check-in closes for this flight. |
| `active` | `bool` | `true` when the current time falls within the `[start_time, end_time]` window (inclusive). |

---

### 9.6 `processing_errors` (array)

A list of error strings from the current pipeline cycle. Empty under normal operation.

```json
["[Counter XYZ] Payload validation failed – Missing required keys: ['flow_rate']"]
```

Each error identifies the counter ID and describes the failure (missing key, type error, value out of range, or unknown counter ID). These are displayed in the `AlertsPanel` when present.

---

## 10. Configuration Constants

All tunable thresholds live in `config.py` and are treated as read-only at runtime.

| Constant | Default | Unit | Used In | Effect |
|---|---|---|---|---|
| `QUEUE_HIGH_RISK_THRESHOLD` | `15` | pax | `Counter.get_risk_level()` | Queues at or above this size are classified "High" risk |
| `QUEUE_MEDIUM_RISK_THRESHOLD` | `8` | pax | `Counter.get_risk_level()` | Queues at or above this size are classified "Medium" risk |
| `FLOW_RATE_LOW_THRESHOLD` | `1.5` | pax/min | R3 optimization rule | Triggers "Deploy Additional Agent" when a High-risk counter falls below this |
| `CLEARANCE_TIME_HIGH_RISK` | `30.0` | min | Internal reference | Clearance above this is critically slow |
| `CLEARANCE_TIME_MEDIUM_RISK` | `15.0` | min | Internal reference | Clearance above this is moderately slow |
| `FORECAST_DELAY_THRESHOLD` | `15.0` | min | `Counter.compute_forecast()` | Clearance above this triggers the "Queue clearance delayed" warning |
| `SPECIAL_ITEM_PENALTY_MINUTES` | `2.0` | min/item | `Queue.estimate_clearance_minutes()` | Processing overhead added per special item |
| `QUEUE_REALLOCATION_THRESHOLD` | `10` | pax | R1 optimization rule | Minimum queue difference to trigger staff reallocation suggestion |
| `SPECIAL_ITEMS_LANE_THRESHOLD` | `3` | items | R2 optimization rule | Minimum special items to suggest opening a dedicated lane |
| `BOARDING_WINDOW_MINUTES` | `30.0` | min | `Flight.correlate_with_counters()` | Passengers must finish check-in this many minutes before departure |
| `DEFAULT_THROUGHPUT_AVG` | `140` | pax/hr | `compute_throughput_change_pct()` | Historical terminal average used as baseline for % change |
| `DEFAULT_CLEARANCE_AVG_SECONDS` | `207.0` | s | `compute_clearance_delta_seconds()` | Historical baseline clearance time (≈ 3m 27s) for delta calculation |
| `LIVE_FEEDS_ACTIVE` | `2` | feeds | `SystemMetrics` | Number of active AI camera feeds reported in the dashboard |
| `APP_VERSION` | `"v1.0-alpha"` | — | `SystemMetrics` | Version string shown in the header |
| `SYSTEM_STATUS` | `"SYSTEM ACTIVE"` | — | `SystemMetrics` | Status label shown in the header |
| `DEFAULT_REMOTE_API_URL` | `"http://192.168.1.42:8000"` | URL | `RemoteAPIClient` | Default base URL for live remote API mode |
| `DEFAULT_POLL_INTERVAL` | `3.0` | s | `RemoteAPIClient` | Seconds between remote API polls in live mode |

---

## 11. REST API Reference

The Flask server (`app.py`) exposes the following endpoints:

### `GET /api/dashboard`

Runs the full AeroVision pipeline and returns the current dashboard state as JSON.

**Response (200 OK):**
```json
{
  "system_metrics": { "throughput": 282, "throughput_change_pct": 101.4, … },
  "counters":        [ { "id": "Gate A", "queue_size": 18, … }, … ],
  "flights":         [ { "id": "DL789", "at_risk": true, … }, … ],
  "optimizations":   [ { "action": "Reallocate Staff", … }, … ],
  "processing_errors": [],
  "schedule":        { "DL789": { "counter_ids": ["Gate A"], "active": true, … }, … }
}
```

**Response (500 Internal Server Error):**
```json
{ "error": "<description>" }
```

### `GET /api/live` (SSE)

Server-Sent Events stream. Each event delivers the full dashboard JSON payload. Used by the React frontend `useSSE` hook.

### `GET /api/live/latest`

Returns the single most recent dashboard frame as JSON (non-streaming). Useful for one-off polling clients.

### `GET /api/live/status`

Returns connection status and frame count from the live remote API client:
```json
{ "connected": true, "frame_count": 42 }
```

---

## 12. Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATA_SOURCE` | `"mock"` | Data ingestion mode: `"mock"` \| `"http"` \| `"websocket"` \| `"live"` |
| `AI_VISION_URL` | `"http://localhost:8080/snapshot"` | Base URL of the AI vision REST or WebSocket endpoint (HTTP and WebSocket modes) |
| `REMOTE_API_URL` | `"http://192.168.1.42:8000"` | Base URL of the remote airport-monitor API (live mode) |
| `POLL_INTERVAL` | `3.0` | Seconds between polls in live mode |
| `PORT` | `5000` | TCP port for the Flask server |
| `HOST` | `"0.0.0.0"` | Bind address for the Flask server |
| `FLASK_ENV` | `"production"` | Set to `"development"` to enable auto-reload and debug tracebacks |

---

## 13. Running the Project

### Backend — CLI mode

```bash
# Default: mock data, prints JSON + summary table to stdout
python main.py

# HTTP snapshot mode
DATA_SOURCE=http AI_VISION_URL=http://localhost:8080/snapshot python main.py

# WebSocket stream mode (blocks until disconnected)
DATA_SOURCE=websocket AI_VISION_URL=ws://localhost:8080/stream python main.py
```

### Backend — Flask API server

```bash
# Default: localhost:5000, mock data
python app.py

# Live mode against a remote airport-monitor instance
DATA_SOURCE=live REMOTE_API_URL=http://192.168.1.42:8000 python app.py

# Development mode with auto-reload
FLASK_ENV=development python app.py
```

### Frontend — React dashboard

```bash
cd frontend
npm install
npm run dev       # development server (default: http://localhost:5173)
npm run build     # production bundle
npm run preview   # preview production build
```

The frontend expects the backend API at `http://localhost:5000`. Ensure the Flask server is running before starting the frontend dev server.

---

## 14. Frontend Dashboard Components

The React dashboard is split into two views toggled by the **Header** navigation.

### Map View
| Component | Description |
|---|---|
| `TerminalMap` | Interactive 3D terminal floor plan rendered with **Three.js**. Camera zones are selectable; clicking a zone filters the `AlertsPanel` and `CameraFeed` to that zone. |
| `AlertsPanel` | Displays live alerts from the backend (`_alerts` field). Filters by selected zone when a zone is active. |
| `CameraFeed` | Shows the latest camera snapshot image for the selected zone. In live mode the image URL is provided by `RemoteAPIClient`. |

### Dashboard View
| Component | Description |
|---|---|
| `Header` | Displays `system_status`, `app_version`, `timestamp`, and connection indicator. Provides the Map / Dashboard view toggle. |
| `MetricsRow` | Renders all `system_metrics` KPI cards: throughput, avg clearance time, critical bottlenecks, flights at risk, live feeds, and action required banner. |
| `CounterCards` | One card per counter showing `queue_size`, `flow_rate`, `risk_level` badge, `forecast` text, `avg_baggage`, `special_items`, and `clearance_minutes`. |
| `FlightPanel` | List of monitored flights with `status`, `at_risk` alert badge, `issue`, `description`, and `expectation` fields. |
| `SuggestionsPanel` | Optimisation suggestion cards, each showing `action`, `details`, `estimated_impact` bar, and an **Execute** button (enabled when `actionable = true`). |
| `Timeline` | Playback controls for stepping through recorded frames (previous / play-pause / next) and a frame-count indicator. |