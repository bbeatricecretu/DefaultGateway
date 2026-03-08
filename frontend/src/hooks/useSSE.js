import { useState, useEffect, useRef, useCallback } from 'react';

export default function useSSE() {
  const [data, setData] = useState(null);
  const [connected, setConnected] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [totalFrames, setTotalFrames] = useState(0);
  const playingRef = useRef(true);

  // Keep ref in sync
  useEffect(() => { playingRef.current = playing; }, [playing]);

  // SSE connection
  useEffect(() => {
    let es;
    function connect() {
      es = new EventSource('/api/stream');
      es.onopen = () => setConnected(true);
      es.onmessage = (e) => {
        if (!playingRef.current) return;
        const parsed = JSON.parse(e.data);
        setData(parsed);
        if (parsed._frame !== undefined) setCurrentFrame(parsed._frame);
        if (parsed._total) setTotalFrames(parsed._total);
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        setTimeout(connect, 3000);
      };
    }
    connect();
    return () => { if (es) es.close(); };
  }, []);

  const fetchFrame = useCallback((idx) => {
    fetch(`/api/mock/snapshot/${idx}`)
      .then(r => r.json())
      .then(d => {
        d._frame = idx;
        setData(d);
        setCurrentFrame(idx);
        if (d._total) setTotalFrames(d._total);
      });
  }, []);

  const goNext = useCallback(() => {
    if (totalFrames > 0) fetchFrame((currentFrame + 1) % totalFrames);
  }, [currentFrame, totalFrames, fetchFrame]);

  const goPrev = useCallback(() => {
    if (totalFrames > 0) fetchFrame((currentFrame - 1 + totalFrames) % totalFrames);
  }, [currentFrame, totalFrames, fetchFrame]);

  const togglePlay = useCallback(() => setPlaying(p => !p), []);

  return {
    data, connected, playing, currentFrame, totalFrames,
    fetchFrame, goNext, goPrev, togglePlay,
  };
}
