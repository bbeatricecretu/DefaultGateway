import './MetricsRow.css';

const cards = [
  { key: 'throughput',    label: 'Throughput',          unit: 'pax / hr',          accent: true },
  { key: 'clearance',     label: 'Avg Clearance',       unit: 'vs baseline',       accent: true },
  { key: 'bottlenecks',   label: 'Critical Bottlenecks',unit: 'high-risk counters', accent: false },
  { key: 'flights_risk',  label: 'Flights at Risk',     unit: 'boarding impact',    accent: false },
];

export default function MetricsRow({ metrics }) {
  const m = metrics || {};
  const throughputChg = m.throughput_change_pct;

  return (
    <div className="metrics-row">
      {/* Throughput */}
      <div className="metric-card">
        <div className="metric-label">Throughput</div>
        <div className="metric-value">{m.throughput ?? '—'}</div>
        <div className={`metric-sub ${throughputChg > 0 ? 'up' : throughputChg < 0 ? 'down' : ''}`}>
          {throughputChg != null ? `${throughputChg > 0 ? '+' : ''}${throughputChg.toFixed(1)}% vs baseline` : 'pax / hr'}
        </div>
      </div>
      {/* Avg Clearance */}
      <div className="metric-card">
        <div className="metric-label">Avg Clearance</div>
        <div className="metric-value">{m.avg_clearance_time ?? '—'}</div>
        <div className={`metric-sub ${(m.avg_clearance_delta || '').startsWith('+') ? 'down' : (m.avg_clearance_delta || '').startsWith('-') ? 'up' : ''}`}>
          {m.avg_clearance_delta ? `${m.avg_clearance_delta} vs baseline` : 'vs baseline'}
        </div>
      </div>
      {/* Bottlenecks */}
      <div className="metric-card">
        <div className="metric-label">Critical Bottlenecks</div>
        <div className="metric-value" style={{
          color: m.critical_bottlenecks > 0 ? 'var(--high)' : m.critical_bottlenecks === 0 ? 'var(--low)' : undefined,
        }}>{m.critical_bottlenecks ?? '—'}</div>
        <div className="metric-sub">high-risk counters</div>
      </div>
      {/* Flights at Risk */}
      <div className="metric-card">
        <div className="metric-label">Flights at Risk</div>
        <div className="metric-value" style={{
          color: m.flights_at_risk > 0 ? 'var(--med)' : m.flights_at_risk === 0 ? 'var(--low)' : undefined,
        }}>{m.flights_at_risk ?? '—'}</div>
        <div className="metric-sub">boarding impact possible</div>
      </div>
    </div>
  );
}
