import { AnimatePresence, motion } from 'framer-motion';
import useSystemStore from '../../store/useSystemStore';

/* ═══════════════════════════════════════════════════
   ACTIVE TASK PANEL — Center Bottom
   ═══════════════════════════════════════════════════ */

export default function TaskPanel() {
  const { currentTask, taskProgress, taskStatus, taskQueue } = useSystemStore();

  if (!currentTask) return null;

  const isCompleted = taskStatus === 'completed';
  const isFailed = taskStatus === 'failed';

  let borderColor = 'var(--stark-cyan)';
  let barBg = 'var(--stark-cyan)';
  let barShadow = '0 0 10px var(--stark-cyan)';
  let panelShadow = 'none';
  let statusColor = 'var(--stark-cyan)';

  if (isCompleted) {
    borderColor = 'var(--stark-green)';
    barBg = 'var(--stark-green)';
    barShadow = '0 0 10px var(--stark-green)';
    panelShadow = '0 0 25px var(--stark-green)';
    statusColor = 'var(--stark-green)';
  } else if (isFailed) {
    borderColor = 'var(--stark-red)';
    barBg = 'var(--stark-red)';
    barShadow = '0 0 10px var(--stark-red)';
    panelShadow = '0 0 25px var(--stark-red)';
    statusColor = 'var(--stark-red)';
  }

  return (
    <div className="active-task-panel" style={{
      display: 'block',
      borderColor,
      boxShadow: panelShadow,
      backdropFilter: 'blur(12px)',
    }}>
      <h2 style={{
        fontFamily: 'var(--font-display)',
        fontSize: '0.8rem',
        marginBottom: '0.5rem',
        border: 'none',
        padding: 0,
        letterSpacing: '4px',
        textTransform: 'uppercase',
        color: 'var(--stark-cyan)',
        textShadow: '0 0 5px var(--stark-cyan-glow)',
      }}>
        ACTIVE.TASK
      </h2>

      <div className="data-row">
        <span className="data-label">TASK</span>
        <span className="data-value" style={{ color: '#fff' }}>{currentTask}</span>
      </div>

      <div className="linear-bar">
        <div className="linear-fill" style={{
          width: `${taskProgress}%`,
          background: barBg,
          boxShadow: barShadow,
        }} />
      </div>

      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        fontFamily: 'var(--font-data)',
        fontSize: '0.8rem',
        marginTop: '8px',
        color: '#aaa',
      }}>
        <span style={{ color: statusColor }}>
          STATUS: {taskStatus === 'executing' ? 'EXECUTING' :
                   taskStatus === 'completed' ? 'COMPLETED' : 'FAILED'}
        </span>
        <span>
          ETA: {taskStatus === 'executing'
            ? `${((100 - taskProgress) / 15).toFixed(1)}s`
            : '--'}
        </span>
      </div>

      {/* Task Queue */}
      {taskQueue.length > 0 && (
        <div style={{
          marginTop: '15px',
          paddingTop: '10px',
          borderTop: '1px solid var(--stark-cyan-dim)',
          fontFamily: 'var(--font-data)',
          fontSize: '0.75rem',
        }}>
          <div style={{ color: 'var(--stark-cyan)', marginBottom: '5px' }}>TASK.QUEUE</div>
          {taskQueue.map((t, i) => (
            <div key={i} style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: '4px',
              color: '#888',
            }}>
              [WAIT] {t}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
