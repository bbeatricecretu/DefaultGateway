# AeroVision Backend

Simple Python backend structure for processing AI-surveillance counter data at airport check-in.

## What this project does

The system does **not** extract data from cameras or video.
It assumes another AI system already detects and sends structured counter data like:

- people in queue
- baggage count
- special items
- flow rate

This backend takes that data and calculates:

- terminal throughput
- average clearance time
- bottlenecks
- flights at risk
- counter forecasts
- optimization suggestions

## Current files

- [config.py](config.py) — thresholds, constants, app settings
- [utils.py](utils.py) — helper functions for time, formatting, validation, scoring
- [models.py](models.py) — OOP models like `Counter`, `Queue`, `Flight`, `Optimization`, `SystemMetrics`
- [processor.py](processor.py) — validates AI payloads and updates counters
- [scheduler.py](scheduler.py) — assigns counters to flights based on schedule windows
- [engine.py](engine.py) — main orchestration logic
- [main.py](main.py) — entry point with mock data / HTTP / WebSocket adapters

## Main attributes used

### System metrics

- `throughput`
- `throughput_change_pct`
- `avg_clearance_time`
- `avg_clearance_delta`
- `critical_bottlenecks`
- `flights_at_risk`
- `app_version`
- `system_status`
- `timestamp`
- `live_feeds_active`
- `action_required`

### Counter attributes

- `id`
- `type`
- `queue_size`
- `flow_rate`
- `avg_baggage`
- `special_items`
- `forecast`
- `risk_level`
- `clearance_minutes`

### Flight attributes

- `id`
- `status`
- `minutes_to_departure`
- `associated_counters`
- `description`
- `issue`
- `expectation`
- `at_risk`

### Optimization attributes

- `action`
- `details`
- `estimated_impact`
- `actionable`

## Logic implemented so far

### 1. Counter processing

Incoming AI payloads are validated first.

Expected counter payload shape:

```python
{
		"03": {
				"queue_size": 18,
				"flow_rate": 1.2,
				"avg_baggage": 2.8,
				"special_items": 4,
		}
}
```

Then each counter updates its internal state.

### 2. Queue clearance estimate

Clearance logic used:

$$
clearance\_time = \frac{queue\_size}{flow\_rate} + (special\_items \times 2\text{ min})
$$

This is used for forecast text and risk evaluation.

### 3. Counter risk levels

- `High` if queue is above high-risk threshold
- `Medium` if queue is above medium-risk threshold
- `Low` otherwise

### 4. Flight-to-counter assignment

Flights are no longer connected to counters manually.

The `ScheduleManager` now assigns counters dynamically using:

- `flight_id`
- `counter_ids`
- `start_time`
- `end_time`

If current time is inside the flight window, counters are assigned.
If not, `associated_counters` is cleared.

### 5. Flight risk correlation

Each flight checks the counters assigned to it.

If estimated counter clearance time is greater than the available boarding window, the flight becomes `at_risk`.

Boarding window logic used:

$$
boarding\_window = minutes\_to\_departure - 30
$$

If:

$$
clearance\_time > boarding\_window
$$

then the flight is flagged as risky.

### 6. Optimization rules

These rules are implemented in [engine.py](engine.py):

- **R1 — Reallocate Staff**  
	If one counter queue is much larger than another, suggest moving an agent.

- **R2 — Open Special Items Lane**  
	If a counter has many special items, suggest opening a dedicated lane.

- **R3 — Deploy Additional Agent**  
	If a counter is high risk and flow rate is low, suggest adding an agent.

- **R4 — Open Relief Counter**  
	If a flight is `at_risk`, suggest opening a dedicated relief counter.

## Engine flow

The current pipeline in [engine.py](engine.py) is:

1. Refresh schedule-based flight/counter assignments
2. Process AI input payloads
3. Generate flight correlations
4. Suggest optimizations
5. Build final output dict

## Output structure

The backend returns data as a dictionary / JSON-like structure:

```python
{
		"system_metrics": {...},
		"counters": [...],
		"flights": [...],
		"optimizations": [...],
		"processing_errors": [...],
		"schedule": {...}
}
```

## Data source support

Right now the project can run with:

- mock data
- HTTP snapshot input
- WebSocket stream input

The backend logic is the same in all cases.

## Run

Use:

```bash
python main.py
```

Default mode is mock mode for testing.