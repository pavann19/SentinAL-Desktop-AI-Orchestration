import useSystemStore from '../../store/useSystemStore';
import DataValue from '../ui/DataValue';

/* ═══════════════════════════════════════════════════
   SYSTEM HARDWARE PANEL — Top Left
   All values sourced from Zustand (fed by /ws/telemetry).
   Uses DataValue for animated null → real transitions.
   ═══════════════════════════════════════════════════ */

export default function SystemHardware() {
  const { cpu, ram, gpu, temp, mode, toggleMode, bootPhase } = useSystemStore();
  const awake = bootPhase === 'done';

  return (
    <div className={`hud-corner top-left ${awake ? 'sys-awake' : ''}`} id="panel-tl">
      <div className="hud-panel group">
        <div className="bracket bracket-tl" />
        <div className="bracket bracket-br" />

        <h2 className="hud-title">SYS.HARDWARE</h2>

        {/* Protocol Mode Toggle */}
        <div
          onClick={toggleMode}
          className="data-row"
          style={{
            marginBottom: '1.5rem',
            borderBottom: '1px solid var(--stark-cyan-dim)',
            paddingBottom: '5px',
            cursor: 'pointer',
          }}
        >
          <span className="data-label">PROTOCOL.MODE</span>
          <span className="data-value" style={{ color: mode === 'security' ? 'var(--stark-red)' : '#fff' }}>
            {mode === 'security' ? 'SECURITY' : 'ASSIST'}
          </span>
        </div>

        <div className="data-row">
          <span className="data-label">CORE.TEMP</span>
          <DataValue value={temp} fieldKey="temp" format={(v) => v.toFixed(1)} suffix="°C" countUp />
        </div>
        <div className="data-row">
          <span className="data-label">GPU.LOAD</span>
          <DataValue value={gpu} fieldKey="gpu" suffix="%" countUp />
        </div>

        <div style={{ marginTop: '1.5rem' }}>
          <div className="data-row">
            <span className="data-label">CPU.LOAD</span>
            <DataValue value={cpu} fieldKey="cpu" suffix="%" countUp />
          </div>
          <div className="linear-bar">
            <div className="linear-fill" style={{
              width: `${cpu ?? 0}%`,
              background: cpu > 85 ? 'var(--stark-gold)' : undefined,
              boxShadow: cpu > 85 ? '0 0 10px var(--stark-gold)' : undefined,
            }} />
          </div>
        </div>

        <div style={{ marginTop: '1rem' }}>
          <div className="data-row">
            <span className="data-label">MEM.ALLOC</span>
            <DataValue value={ram} fieldKey="ram" suffix="%" countUp />
          </div>
          <div className="linear-bar">
            <div className="linear-fill" style={{ width: `${ram ?? 0}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
