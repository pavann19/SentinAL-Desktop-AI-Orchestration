/* ═══════════════════════════════════════════════════════════════
   CONFIRMATION DIALOG  — FIX 6
   
   Blocks the UI with an explicit approve/deny prompt whenever
   the backend marks a command as `requires_confirmation: true`.
   Designed to match the SentinAL sci-fi aesthetic.
   ═══════════════════════════════════════════════════════════════ */

import useSystemStore from '../../store/useSystemStore';
import { sendCommand } from '../../services/wsService';

export default function ConfirmationDialog() {
  const { confirmationPending, confirmationCommand, resolveConfirmation } = useSystemStore();

  if (!confirmationPending) return null;

  const handleApprove = () => {
    resolveConfirmation();
    // Re-send the command with an explicit confirmation prefix the backend can parse
    sendCommand(`CONFIRMED: ${confirmationCommand}`);
  };

  const handleDeny = () => {
    resolveConfirmation();
  };

  return (
    <>
      {/* Dark overlay */}
      <div
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.72)',
          zIndex: 9000,
          backdropFilter: 'blur(4px)',
          animation: 'standby-fade-in 0.2s ease forwards',
        }}
        onClick={handleDeny}
      />

      {/* Dialog box */}
      <div
        id="confirmation-dialog"
        style={{
          position: 'fixed',
          top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 9001,
          width: '420px',
          background: 'rgba(0, 3, 10, 0.95)',
          border: '1px solid rgba(255, 0, 60, 0.55)',
          boxShadow: '0 0 40px rgba(255, 0, 60, 0.12), inset 0 0 30px rgba(0,0,0,0.4)',
          padding: '28px 32px',
          fontFamily: 'var(--font-data)',
          animation: 'slide-down 0.2s ease forwards',
        }}
      >
        {/* Header */}
        <div style={{
          fontSize: '0.7rem', letterSpacing: '5px', textTransform: 'uppercase',
          color: 'rgba(255, 0, 60, 0.9)', marginBottom: '6px', fontWeight: 600,
        }}>
          ⚠ AEGIS SECURITY GATE
        </div>

        {/* Title */}
        <div style={{
          fontSize: '1.1rem', letterSpacing: '2px', color: 'rgba(255,255,255,0.92)',
          marginBottom: '18px', fontFamily: 'var(--font-display)', fontWeight: 600,
        }}>
          DESTRUCTIVE OPERATION DETECTED
        </div>

        {/* Command display */}
        <div style={{
          background: 'rgba(255, 0, 60, 0.06)',
          border: '1px solid rgba(255, 0, 60, 0.15)',
          padding: '10px 14px',
          marginBottom: '22px',
          fontSize: '0.82rem',
          color: 'rgba(255, 255, 255, 0.7)',
          letterSpacing: '0.5px',
          wordBreak: 'break-all',
        }}>
          <span style={{ opacity: 0.4 }}>CMD › </span>
          {confirmationCommand}
        </div>

        <div style={{
          fontSize: '0.75rem', color: 'rgba(255,255,255,0.35)',
          marginBottom: '24px', letterSpacing: '0.5px',
        }}>
          This action may permanently modify or delete system files.
          Clearance level ADMIN required to proceed.
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            id="confirm-deny-btn"
            onClick={handleDeny}
            style={{
              flex: 1, padding: '10px',
              background: 'transparent',
              border: '1px solid rgba(0, 243, 255, 0.2)',
              color: 'rgba(0, 243, 255, 0.7)',
              fontFamily: 'var(--font-data)',
              fontSize: '0.78rem', letterSpacing: '2px',
              cursor: 'pointer', textTransform: 'uppercase',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={e => {
              e.target.style.borderColor = 'rgba(0, 243, 255, 0.5)';
              e.target.style.color = 'rgba(0, 243, 255, 1)';
            }}
            onMouseLeave={e => {
              e.target.style.borderColor = 'rgba(0, 243, 255, 0.2)';
              e.target.style.color = 'rgba(0, 243, 255, 0.7)';
            }}
          >
            Abort
          </button>

          <button
            id="confirm-approve-btn"
            onClick={handleApprove}
            style={{
              flex: 1, padding: '10px',
              background: 'rgba(255, 0, 60, 0.12)',
              border: '1px solid rgba(255, 0, 60, 0.5)',
              color: 'rgba(255, 0, 60, 0.9)',
              fontFamily: 'var(--font-data)',
              fontSize: '0.78rem', letterSpacing: '2px',
              cursor: 'pointer', textTransform: 'uppercase',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={e => {
              e.target.style.background = 'rgba(255, 0, 60, 0.22)';
              e.target.style.borderColor = 'rgba(255, 0, 60, 0.8)';
              e.target.style.color = '#ff003c';
            }}
            onMouseLeave={e => {
              e.target.style.background = 'rgba(255, 0, 60, 0.12)';
              e.target.style.borderColor = 'rgba(255, 0, 60, 0.5)';
              e.target.style.color = 'rgba(255, 0, 60, 0.9)';
            }}
          >
            Execute
          </button>
        </div>
      </div>
    </>
  );
}
