import './CounterCard.css';
import { COUNTER_ORDER, COUNTER_DISPLAY } from '../data/zoneMap';

function riskColor(r) {
  return r === 'High' ? 'var(--high)' : r === 'Medium' ? 'var(--med)' : 'var(--low)';
}

export default function CounterCards({ counters }) {
  const list = counters || [];
  const ordered = COUNTER_ORDER.map(id => list.find(c => c.id === id)).filter(Boolean);
  const extras = list.filter(c => !COUNTER_ORDER.includes(c.id));
  const sorted = [...ordered, ...extras];

  return (
    <div className="counters-grid">
      {sorted.map(c => {
        const d = COUNTER_DISPLAY[c.id] || { name: c.id, sub: c.type || '', color: 'var(--accent)' };
        const qpct = Math.min(100, ((c.queue_size || 0) / 25) * 100);
        const color = riskColor(c.risk_level);
        return (
          <div className={`counter-card risk-${c.risk_level}`} key={c.id}>
            <div className="counter-head">
              <span className="counter-name">{d.name}</span>
              <span className={`risk-badge ${c.risk_level}`}>{c.risk_level || '—'}</span>
            </div>
            <div className="counter-type">{d.sub}</div>
            <div className="queue-label-row">
              <span>Queue fill <span className="dim">(cap. 25)</span></span>
              <span style={{ color, fontWeight: 700 }}>{qpct.toFixed(0)}%</span>
            </div>
            <div className="queue-bar-wrap">
              <div className="queue-bar" style={{ width: `${qpct}%`, background: color }} />
            </div>
            <div className="counter-stats">
              <div className="stat"><span className="sl">Queue</span><span className="sv">{c.queue_size ?? '—'} pax</span></div>
              <div className="stat"><span className="sl">Flow</span><span className="sv">{(c.flow_rate||0).toFixed(1)}/min</span></div>
              <div className="stat"><span className="sl">Throughput</span><span className="sv">{c.throughput ?? '—'}/hr</span></div>
              <div className="stat"><span className="sl">Baggage</span><span className="sv">{(c.avg_baggage||0).toFixed(1)} avg</span></div>
              {c.special_items > 0 && (
                <div className="stat span2"><span className="sl">Special items</span><span className="sv warn">{c.special_items} ⚠</span></div>
              )}
            </div>
            <div className="forecast">Forecast: <span>{c.forecast || '—'}</span></div>
          </div>
        );
      })}
    </div>
  );
}
