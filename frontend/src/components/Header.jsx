import './Header.css';

export default function Header({ connected, metrics, view, onToggleView }) {
  const m = metrics || {};
  const statusText = !connected ? 'RECONNECTING…'
    : m.action_required ? '⚠ ACTION REQUIRED' : 'SYSTEM ACTIVE';
  const danger = !connected || m.action_required;

  return (
    <header className="header">
      <div className="logo" onClick={() => onToggleView?.('map')} title="Home">
        🛫 Aero<span>Vision</span>
      </div>
      <div className={`status-pill${danger ? ' danger' : ''}`}>{statusText}</div>
      <div className="hdr-center">
        <div className="hdr-timestamp">{m.timestamp || '—'}</div>
      </div>
      <button
        className={`nav-btn${view === 'dashboard' ? ' secondary' : ''}`}
        onClick={() => onToggleView?.(view === 'map' ? 'dashboard' : 'map')}
      >
        {view === 'map' ? '📊 Enter Dashboard' : '🗺 Back to Map'}
      </button>
    </header>
  );
}
