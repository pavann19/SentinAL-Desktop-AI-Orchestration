import { useEffect, useRef } from 'react';
import useSystemStore from '../store/useSystemStore';
import { initializeSockets, destroySockets } from '../services/wsService';

/* ═══════════════════════════════════════════════════
   IDLE TIMER HOOK
   Tracks user inactivity → puts system into idle mode.
   ═══════════════════════════════════════════════════ */

export function useIdleTimer(timeoutMs = 15000) {
  const timerRef = useRef(null);

  useEffect(() => {
    const reset = () => {
      const { booted, state, setSystemState } = useSystemStore.getState();
      if (!booted) return;

      clearTimeout(timerRef.current);

      if (booted && state !== 'processing' && state !== 'cooldown' && state !== 'booting') {
        timerRef.current = setTimeout(() => {
          const current = useSystemStore.getState();
          if (current.state !== 'processing' && current.state !== 'cooldown') {
            setSystemState('idle');
          }
        }, timeoutMs);
      }
    };

    window.addEventListener('mousemove', reset);
    window.addEventListener('keypress', reset);
    window.addEventListener('click', reset);

    return () => {
      clearTimeout(timerRef.current);
      window.removeEventListener('mousemove', reset);
      window.removeEventListener('keypress', reset);
      window.removeEventListener('click', reset);
    };
  }, [timeoutMs]);
}

/* ═══════════════════════════════════════════════════
   LIVE BACKEND HOOK
   Initializes both WebSocket connections (telemetry + 
   agent) after the system has booted. Cleans up on unmount.
   
   Replaces both:
   - useTelemetry (mock → live /ws/telemetry)
   - useSystemEvents (removed — telemetry handles events)
   ═══════════════════════════════════════════════════ */

export function useLiveBackend() {
  useEffect(() => {
    // Initialize both sockets immediately upon mount
    // to allow backend to wake up the UI from standby
    initializeSockets();

    return () => {
      // Only cleanup on full unmount (e.g., page leave)
      // Do NOT destroy on re-renders
    };
  }, []);

  // Global cleanup on app exit
  useEffect(() => {
    return () => {
      destroySockets();
    };
  }, []);
}

/* ═══════════════════════════════════════════════════
   LEGACY EXPORTS — kept for backwards compatibility
   with any imports that still use the old names.
   Both now defer to useLiveBackend internally.
   ═══════════════════════════════════════════════════ */

/** @deprecated — use useLiveBackend() instead */
export function useTelemetry() {
  useLiveBackend();
}

/** @deprecated — background events now driven by /ws/telemetry */
export function useSystemEvents() {
  // No-op. Background events are now emitted by the telemetry stream
  // adapter in wsService.js → adaptGovernanceLogs.
}
