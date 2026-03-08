import { FLIGHT_SCHEDULE, FLIGHT_PRED_FALLBACK } from '../data/zoneMap';
import './FlightPanel.css';

function getPrediction(f, idx) {
  const s = FLIGHT_SCHEDULE[f.id];
  if (s) return s.prediction;
  if (f.at_risk) return '⛅ Possible delay due to adverse conditions. ATC coordination underway.';
  return FLIGHT_PRED_FALLBACK[idx % FLIGHT_PRED_FALLBACK.length];
}

export default function FlightPanel({ flights }) {
  const list = flights || [];

  return (
    <div className="panel flight-panel">
      <div className="panel-title">✈ Flights</div>
      <div className="panel-scroll">
        {list.length === 0 ? (
          <div className="no-data">No flights registered.</div>
        ) : (
          list.map((f, i) => {
            const sched = FLIGHT_SCHEDULE[f.id];
            const pred = getPrediction(f, i);
            return (
              <div className="flight-card" key={f.id}>
                <div className="flight-top">
                  <span className="flight-id">{f.id}</span>
                  <span className="flight-status">{f.status || ''}</span>
                  {sched && <span className="flight-route">✈ {sched.origin} → {sched.destination}</span>}
                  <span className={`risk-pill ${f.at_risk ? 'danger' : 'ok'}`}>
                    {f.at_risk ? '⚠ AT RISK' : '✓ OK'}
                  </span>
                </div>
                {sched && (
                  <div className="flight-details">
                    <span>🚪 Gate <strong>{sched.gate}</strong></span>
                    <span>✈ <strong>{sched.aircraft}</strong></span>
                    <span>🕐 Board <strong>{sched.boardingTime}</strong></span>
                    <span>🛫 Depart <strong>{sched.departureTime}</strong></span>
                  </div>
                )}
                <div className="flight-prediction">{pred}</div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
