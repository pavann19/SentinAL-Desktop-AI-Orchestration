import { useState } from 'react';
import useSystemStore from '../../store/useSystemStore';
import DataValue from '../ui/DataValue';

/* ═══════════════════════════════════════════════════
   SYSTEM DASHBOARD PANEL — Bottom Left
   All values sourced from Zustand (fed by /ws/telemetry).
   Uses DataValue for animated null → real transitions.
   ═══════════════════════════════════════════════════ */

export default function Dashboard() {
  const { 
    bootPhase, state, addNotification,
    envFiles, envDirs, sysUptime, sysThreat, govClearance 
  } = useSystemStore();
  const [filesOpen, setFilesOpen] = useState(false);
  const awake = bootPhase === 'done';
  const booted = bootPhase === 'done';

  const handleToggleFiles = () => {
    if (!booted) return;
    setFilesOpen(!filesOpen);
    if (!filesOpen) addNotification('Expanding Project Environment', 'info');
  };

  return (
    <div className={`hud-corner bottom-left ${awake ? 'sys-awake' : ''}`} id="panel-bl">
      <div className="hud-panel group">
        <div className="bracket bracket-bl" />
        <div className="bracket bracket-tr" />

        <h2 className="hud-title">SYS.DASHBOARD</h2>

        <div className="data-row">
          <span className="data-label">🛡 CLEARANCE</span>
          <DataValue value={govClearance} fieldKey="govClearance" />
        </div>

        <div className="data-row" style={{ marginTop: '0.8rem', cursor: 'pointer' }} onClick={handleToggleFiles}>
          <span className="data-label">📁 PROJECT ENV</span>
          <DataValue value={envFiles} fieldKey="envFiles" format={(v) => `${v} Files`} />
        </div>

        {/* File mini-view */}
        <div style={{
          marginTop: filesOpen ? '10px' : 0,
          fontFamily: 'var(--font-data)',
          fontSize: '0.75rem',
          color: '#fff',
          border: filesOpen ? '1px solid var(--stark-cyan-dim)' : 'none',
          padding: filesOpen ? '10px' : 0,
          background: 'rgba(0, 243, 255, 0.05)',
          transition: 'all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
          transform: filesOpen ? 'scale(1)' : 'scale(0.95)',
          opacity: filesOpen ? 1 : 0,
          maxHeight: filesOpen ? '150px' : 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}>
          <div>Mounted Directories/</div>
          {envDirs && envDirs.length > 0 ? envDirs.map((dir, i) => (
            <div key={i} style={{ marginLeft: 15, color: 'var(--stark-cyan)', opacity: 0.8 }}>
              {i === envDirs.length - 1 ? '└──' : '├──'} {dir.split('\\').pop().split('/').pop() || dir}
            </div>
          )) : (
            <div style={{ marginLeft: 15, color: 'var(--stark-cyan)', opacity: 0.5 }}>Waiting for data...</div>
          )}
        </div>

        <div className="data-row" style={{ marginTop: '0.8rem' }}>
          <span className="data-label">⏱ UPTIME</span>
          <DataValue 
            value={sysUptime} 
            fieldKey="sysUptime"
            format={(v) => v.toFixed(2)}
            suffix="%"
            countUp
            style={{ color: 'var(--stark-green)' }}
          />
        </div>

        <div className="data-row" style={{ marginTop: '0.8rem' }}>
          <span className="data-label">⚠️ THREAT LEVEL</span>
          <DataValue 
            value={sysThreat}
            fieldKey="sysThreat"
            style={{ color: sysThreat === 'ZERO' ? 'var(--stark-cyan)' : sysThreat ? 'var(--stark-red)' : undefined }}
          />
        </div>
      </div>
    </div>
  );
}
