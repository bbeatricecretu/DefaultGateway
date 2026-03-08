import './SuggestionsPanel.css';

const icons = {
  'Reallocate Staff': '👥', 'Open Special Items Lane': '🧳',
  'Deploy Additional Agent': '🚨', 'Open Relief Counter': '🔓',
};

function impactClass(pct) {
  if (pct >= 40) return 'priority-high';
  if (pct >= 20) return 'priority-medium';
  return 'priority-low';
}

function buildWarnings(alerts, counters, opts) {
  const warnings = [];

  // From RED/AMBER alerts
  (alerts || []).filter(a => a.severity === 'RED').forEach(a => {
    const covered = opts.some(o => (o.details || '').toLowerCase().includes(a.camera.toLowerCase()));
    if (covered) return;
    warnings.push({
      action: `🆘 Critical — ${a.camera}`,
      details: `${a.explanation}${a.top_action ? ' → ' + a.top_action : ''}`,
      estimated_impact: Math.round(a.risk_score || 75),
      _severity: 'RED',
    });
  });

  (alerts || []).filter(a => a.severity === 'AMBER' && (a.risk_score || 0) >= 45).forEach(a => {
    const covered = opts.some(o => (o.details || '').toLowerCase().includes(a.camera.toLowerCase()))
      || warnings.some(w => w.action.includes(a.camera));
    if (covered) return;
    warnings.push({
      action: `⚠️ Elevated Risk — ${a.camera}`,
      details: `${a.explanation} Risk: ${(a.risk_score||0).toFixed(0)}%`,
      estimated_impact: Math.round(a.risk_score || 40),
      _severity: 'AMBER',
    });
  });

  // From High/Medium counters
  (counters || []).filter(c => c.risk_level === 'High').forEach(c => {
    warnings.push({
      action: `📊 High Queue — ${c.id}`,
      details: `${c.queue_size} pax, ${(c.flow_rate||0).toFixed(1)} pax/min. ${c.forecast || ''}`,
      estimated_impact: 50,
      _severity: 'counter',
    });
  });

  return warnings;
}

export default function SuggestionsPanel({ optimizations, alerts, counters }) {
  const opts = optimizations || [];
  const warnings = buildWarnings(alerts, counters, opts);
  const all = [
    ...warnings.map(w => ({ ...w, _synthetic: true })),
    ...opts.map(o => ({ ...o, _synthetic: false })),
  ].sort((a, b) => (b.estimated_impact || 0) - (a.estimated_impact || 0));

  return (
    <div className="panel suggestions-panel">
      <div className="panel-title">💡 Warnings & Suggestions</div>
      <div className="panel-scroll">
        {all.length === 0 ? (
          <div className="no-data">✓ No warnings or suggestions at this time.</div>
        ) : (
          all.map((o, i) => (
            <div className={`opt-card ${impactClass(o.estimated_impact || 0)}`} key={i}>
              <span className="opt-icon">{icons[o.action] || (o._synthetic ? '⚠️' : '💡')}</span>
              <div className="opt-body">
                <div className="opt-action">{o.action}</div>
                <div className="opt-reason">{o.details || ''}</div>
                {o.estimated_impact != null && (
                  <div className="opt-meta">Impact: ~{o.estimated_impact}% throughput improvement</div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
