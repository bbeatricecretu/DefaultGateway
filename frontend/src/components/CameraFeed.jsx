import { useState, useEffect, useRef } from 'react';
import { ZONE_CAMERA_MAP } from '../data/zoneMap';
import './CameraFeed.css';

const fileCache = {};
async function getFiles(folder) {
  if (fileCache[folder]) return fileCache[folder];
  try {
    const r = await fetch(`/api/camera_list/${folder}`);
    const d = await r.json();
    fileCache[folder] = d.files || [];
    return fileCache[folder];
  } catch { return []; }
}

function parseTimestamp(fname) {
  const parts = fname.replace('.jpg', '').split('_');
  if (parts.length >= 5) {
    const d = parts[1], t = parts[2], n = parseInt(parts[3], 10);
    return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)} · ${t.slice(0,2)}:${t.slice(2,4)}:${t.slice(4,6)} · frame #${n}`;
  }
  return '';
}

export default function CameraFeed({ selectedZone, currentFrame }) {
  const [imageUrl, setImageUrl] = useState(null);
  const [timestamp, setTimestamp] = useState('');
  const mapping = selectedZone ? ZONE_CAMERA_MAP[selectedZone] : null;

  useEffect(() => {
    if (!mapping) { setImageUrl(null); setTimestamp(''); return; }
    let cancelled = false;
    getFiles(mapping.folder).then(files => {
      if (cancelled || !files.length) return;
      const idx = currentFrame % files.length;
      const fname = files[idx];
      setImageUrl(`/api/camera_image/${mapping.folder}/${fname}`);
      setTimestamp(parseTimestamp(fname));
    });
    return () => { cancelled = true; };
  }, [mapping, currentFrame]);

  return (
    <div className="camera-panel">
      <div className="camera-header">
        <h3>📷 Live Camera Feed</h3>
        <div className="camera-meta">
          {mapping ? (
            <>
              <span className="zone-tag" style={{ background: mapping.color + '22', color: mapping.color, borderColor: mapping.color + '44' }}>
                {mapping.label}
              </span>
              <span className="cam-ts">{timestamp}</span>
            </>
          ) : (
            <span className="cam-ts">Select a zone on the map</span>
          )}
        </div>
      </div>
      <div className="camera-viewport">
        {imageUrl ? (
          <img src={imageUrl} alt="Camera feed" onError={(e) => { e.target.style.display = 'none'; }} />
        ) : (
          <div className="feed-placeholder">
            <div className="ph-icon">📷</div>
            <div>Click a zone label on the 3D map to view its camera feed</div>
          </div>
        )}
      </div>
    </div>
  );
}
