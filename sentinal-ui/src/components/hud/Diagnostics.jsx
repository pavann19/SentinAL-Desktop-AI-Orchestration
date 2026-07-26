import { useState, useEffect } from 'react';
import useSystemStore from '../../store/useSystemStore';
import DataValue from '../ui/DataValue';

/* ═══════════════════════════════════════════════════
   DIAGNOSTICS PANEL — Top Right
   All values sourced from Zustand (fed by /ws/telemetry + /ws/agent).
   NET.UPLINK reflects live wsStatus.
   Uses DataValue for animated null → real transitions.
   ═══════════════════════════════════════════════════ */

export default function Diagnostics() {
  const { bootPhase, state, lastTask, lastTaskStatus, wsStatus, sysCoreStatus } = useSystemStore();
  const [time, setTime] = useState('00:00:00');
  const awake = bootPhase === 'done';
  const booted = bootPhase === 'done';

  useEffect(() => {
    const interval = setInterval(() => {
      setTime(new Date().toISOString().split('T')[1].split('.')[0]);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Mic status — derived from system state
  const micLabel = state === 'listening' ? 'LISTENING' :
                   state === 'processing' ? 'BUSY' :
                   booted ? 'STANDBY' : '—';

  // NET.UPLINK — derived from actual WebSocket connection health
  const telemetryStatus = wsStatus.telemetry;
  const agentStatus = wsStatus.agent;

  const isLive = telemetryStatus === 'connected' && agentStatus === 'connected';
  const isConnecting = telemetryStatus === 'connecting' || agentStatus === 'connecting';

  const uplinkLabel = isLive ? 'LIVE' : isConnecting ? 'CONNECTING...' : 'OFFLINE';
  const uplinkClass = isLive ? 'conn-live' : isConnecting ? 'conn-connecting' : 'conn-offline';

  return (
    <div className={`hud-corner top-right ${awake ? 'sys-awake' : ''}`} id="panel-tr">
      <div className="hud-panel group">
        <div className="bracket bracket-tr" />
        <div className="bracket bracket-bl" />

        <h2 className="hud-title" style={{ textAlign: 'right' }}>DIAGNOSTICS</h2>

        <div className="data-row">
          <span className="data-value">{time}</span>
          <span className="data-label">LOCAL.TIME</span>
        </div>
        <div className="data-row">
          <DataValue value={uplinkLabel !== '—' ? uplinkLabel : null} className={`data-value ${uplinkClass}`} />
          <span className="data-label">NET.UPLINK</span>
        </div>

        {/* AI Core Status */}
        <div className="data-row">
          <DataValue value={sysCoreStatus} fieldKey="sysCoreStatus" />
          <span className="data-label">AI.CORE</span>
        </div>

        {/* Mic Status */}
        <div className="data-row" style={{ marginTop: '1rem' }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontFamily: 'var(--font-data)',
            fontSize: '0.8rem',
            color: state === 'listening' ? 'var(--stark-gold)' : 'var(--stark-cyan-dim)',
          }}>
            {micLabel}
            {state === 'listening' && (
              <div style={{ display: 'flex', gap: '3px', height: '10px', alignItems: 'center' }}>
                <div className="wave-bar" style={{ width: 3, background: 'var(--stark-gold)', borderRadius: 2, animation: 'wave 1s infinite alternate' }} />
                <div className="wave-bar" style={{ width: 3, background: 'var(--stark-gold)', borderRadius: 2, animation: 'wave 1s infinite alternate 0.2s' }} />
                <div className="wave-bar" style={{ width: 3, background: 'var(--stark-gold)', borderRadius: 2, animation: 'wave 1s infinite alternate 0.4s' }} />
              </div>
            )}
          </div>
          <span className="data-label">MIC.ARRAY</span>
        </div>

        {/* Session Context */}
        <div style={{ marginTop: '15px', paddingTop: '10px', borderTop: '1px solid var(--stark-cyan-dim)', fontFamily: 'var(--font-data)', fontSize: '0.75rem' }}>
          <div style={{ color: 'var(--stark-cyan)', marginBottom: '5px' }}>SESSION.CONTEXT</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
            <span className="data-label">Last Task:</span>
            <span>{lastTask}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="data-label">Status:</span>
            <span style={{
              color: lastTaskStatus === 'Completed' ? 'var(--stark-green)' :
                     lastTaskStatus === 'Failed' ? 'var(--stark-red)' : 'var(--stark-cyan)',
            }}>
              {lastTaskStatus}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
