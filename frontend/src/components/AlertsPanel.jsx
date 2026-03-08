import { ZONE_CAMERA_MAP, CAMERA_DISPLAY_NAMES } from '../data/zoneMap';
import './AlertsPanel.css';

export default function AlertsPanel({ alerts, selectedZone, title }) {
  const allAlerts = alerts || [];
  let filtered = allAlerts;

  if (selectedZone && ZONE_CAMERA_MAP[selectedZone]) {
    const camLabel = ZONE_CAMERA_MAP[selectedZone].label;
    filtered = allAlerts.filter(a => a.camera === camLabel);
  }

  // Sort: RED > AMBER > GREEN
  const sorted = [...filtered].sort((a, b) => {
    const rank = { RED: 0, AMBER: 1, GREEN: 2 };
    return (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9);
  });

  const zoneLabel = selectedZone && ZONE_CAMERA_MAP[selectedZone]
    ? ZONE_CAMERA_MAP[selectedZone].label : null;

  return (
    <div className="alerts-panel">
      <div className="alerts-header">
        <h3>{title || '⚠️ AI Zone Alerts'}</h3>
        {zoneLabel && <span className="alerts-filter">Filtered: {zoneLabel}</span>}
      </div>
      <div className="alerts-scroll">
        {sorted.length === 0 ? (
          <div className="no-alerts">✓ No alerts{zoneLabel ? ` for ${zoneLabel}` : ' for this frame'}.</div>
        ) : (
          sorted.map((a, i) => {
            const displayName = CAMERA_DISPLAY_NAMES[a.camera] || a.camera;
            return (
              <div className="alert-row" key={i}>
                <span className={`alert-sev ${a.severity}`}>{a.severity || '?'}</span>
                <div className="alert-content">
                  <div className="alert-cam">
                    {displayName}
                    <span className="alert-cam-raw">{a.camera}</span>
                    {a.risk_score != null && (
                      <span className="alert-risk">risk {a.risk_score.toFixed(0)}%</span>
                    )}
                  </div>
                  <div className="alert-body">{a.explanation || ''}</div>
                  {a.top_action && <div className="alert-action">↳ {a.top_action}</div>}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
