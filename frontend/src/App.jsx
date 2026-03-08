import { useState, useCallback } from 'react';
import './App.css';
import useSSE from './hooks/useSSE';
import Header from './components/Header';
import MetricsRow from './components/MetricsRow';
import CounterCards from './components/CounterCard';
import CameraFeed from './components/CameraFeed';
import AlertsPanel from './components/AlertsPanel';
import FlightPanel from './components/FlightPanel';
import SuggestionsPanel from './components/SuggestionsPanel';
import TerminalMap from './components/TerminalMap';
import Timeline from './components/Timeline';

export default function App() {
  const {
    data, connected, playing, currentFrame, totalFrames,
    fetchFrame, goNext, goPrev, togglePlay,
  } = useSSE();

  const [view, setView] = useState('map');
  const [selectedZone, setSelectedZone] = useState(null);

  const handleSelectZone = useCallback((zoneId) => {
    setSelectedZone(zoneId);
  }, []);

  const metrics = data?.system_metrics || {};
  const counters = data?.counters || [];
  const flights = data?.flights || [];
  const alerts = data?._alerts || [];
  const optimizations = data?.optimizations || [];

  return (
    <>
      <Header
        connected={connected}
        metrics={metrics}
        view={view}
        onToggleView={setView}
      />

      <div className="app-main">
        {view === 'map' ? (
          <div className="map-view view-enter" key="map">
            <TerminalMap onSelectZone={handleSelectZone} />
            <div className="map-right-col">
              <AlertsPanel alerts={alerts} selectedZone={selectedZone} />
              <CameraFeed selectedZone={selectedZone} currentFrame={currentFrame} />
            </div>
          </div>
        ) : (
          <div className="dashboard-view view-enter" key="dash">
            <div className="dash-left">
              <MetricsRow metrics={metrics} />
              <CounterCards counters={counters} />
            </div>
            <div className="dash-right">
              <SuggestionsPanel
                optimizations={optimizations}
                alerts={alerts}
                counters={counters}
              />
              <FlightPanel flights={flights} />
            </div>
          </div>
        )}
      </div>

      <Timeline
        currentFrame={currentFrame}
        totalFrames={totalFrames}
        playing={playing}
        connected={connected}
        onPrev={goPrev}
        onNext={goNext}
        onToggle={togglePlay}
        onGoto={fetchFrame}
      />
    </>
  );
}
