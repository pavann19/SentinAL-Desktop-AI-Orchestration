import { useEffect, useRef } from 'react';
import useSystemStore from '../../store/useSystemStore';

/* ═══════════════════════════════════════════════════
   GOVERNANCE LOG / TERMINAL — Bottom Right
   ═══════════════════════════════════════════════════ */

export default function Terminal() {
  const { bootPhase, logs } = useSystemStore();
  const scrollRef = useRef(null);
  const awake = bootPhase === 'done';
  const booted = bootPhase === 'done' || bootPhase === 'spinup' || bootPhase === 'fiery' || bootPhase === 'flash';

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const typeColors = {
    info: 'var(--stark-cyan)',
    warn: 'var(--stark-gold)',
    crit: 'var(--stark-red)',
    success: 'var(--stark-green)',
  };

  return (
    <div className={`hud-corner bottom-right ${awake ? 'sys-awake' : ''}`} id="panel-br" style={{ opacity: booted ? undefined : 0, pointerEvents: booted ? undefined : 'none', transition: 'opacity 0.8s ease' }}>
      <div className="hud-panel group" style={{ textAlign: 'left' }}>
        <div className="bracket bracket-br" />
        <div className="bracket bracket-tl" />

        <h2 className="hud-title">GOVERNANCE.LOG</h2>

        <div
          ref={scrollRef}
          style={{
            fontFamily: 'var(--font-data)',
            fontSize: '0.75rem',
            opacity: 0.85,
            lineHeight: 1.4,
            height: '220px',
            overflowY: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'flex-end',
          }}
        >
          {logs.map((log) => (
            <div key={log.id} style={{
              marginBottom: '10px',
              borderLeft: '2px solid var(--stark-cyan-dim)',
              paddingLeft: '8px',
            }}>
              <div style={{ fontWeight: 'bold', color: '#fff', marginBottom: '2px' }}>[{log.tag}]</div>
              <div style={{
                wordWrap: 'break-word',
                color: typeColors[log.type] || typeColors.info,
                textShadow: log.type !== 'info' ? `0 0 5px ${typeColors[log.type]}` : 'none',
                whiteSpace: 'pre-wrap',
              }}>
                {log.text}
              </div>
            </div>
          ))}
          {logs.length === 0 && (
            <div style={{ color: 'var(--stark-cyan-dim)', fontStyle: 'italic' }}>Awaiting system boot...</div>
          )}
        </div>
      </div>
    </div>
  );
}
