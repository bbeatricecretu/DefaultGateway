import './Timeline.css';

export default function Timeline({ currentFrame, totalFrames, playing, connected, onPrev, onNext, onToggle, onGoto }) {
  const maxDots = 30;
  const start = Math.max(0, currentFrame - Math.floor(maxDots / 2));
  const end = Math.min(totalFrames, start + maxDots);
  const dots = [];
  for (let i = start; i < end; i++) dots.push(i);

  return (
    <div className="timeline">
      <div className={`conn-dot${connected ? '' : ' off'}`} />
      <span className="tl-label">Frames</span>
      <div className="tl-frames">
        {dots.map(i => (
          <button
            key={i}
            className={`tl-dot${i === currentFrame ? ' active' : i < currentFrame ? ' visited' : ''}`}
            onClick={() => onGoto?.(i)}
          >
            {i + 1}
          </button>
        ))}
      </div>
      <button className="tl-btn" onClick={onPrev}>◀</button>
      <button className={`tl-btn${playing ? ' playing' : ''}`} onClick={onToggle}>
        {playing ? '⏸ Pause' : '▶ Play'}
      </button>
      <button className="tl-btn" onClick={onNext}>▶</button>
      <span className="tl-counter">Frame {currentFrame + 1} / {totalFrames || '—'}</span>
    </div>
  );
}
