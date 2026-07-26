import { useCallback, useRef, useEffect } from 'react';
import useSystemStore from '../store/useSystemStore';
import { useIdleTimer, useLiveBackend } from '../hooks/useSystem';
import { sendCommand, sendInterrupt } from '../services/wsService';

import Background from '../components/core/Background';
import CoreSystem from '../components/core/CoreSystem';
import SystemHardware from '../components/hud/SystemHardware';
import Diagnostics from '../components/hud/Diagnostics';
import Dashboard from '../components/hud/Dashboard';
import Terminal from '../components/hud/Terminal';
import TaskPanel from '../components/hud/TaskPanel';
import Notifications from '../components/ui/Notifications';
import CommandInput from '../components/ui/CommandInput';
import ConfirmationDialog from '../components/ui/ConfirmationDialog'; // FIX 6

/* ═══════════════════════════════════════════════════
   MAIN UI — Full-screen AI OS Layout
   Boot: voice wake → spinup → fiery → flash → panels
   ═══════════════════════════════════════════════════ */

export default function MainUI() {
  const { booted, state, mode, bootPhase } = useSystemStore();
  const flashRef = useRef(null);

  // Activate hooks
  useIdleTimer(15000);
  useLiveBackend(); // Initializes /ws/telemetry + /ws/agent after boot

  // ── Manual Wake Trigger (Keyboard Fallback) ──
  // Listens for Enter key while in standby to manually boot the system.
  useEffect(() => {
    if (booted) return;
    
    const handleKey = (e) => {
      if (e.key === 'Enter') {
        useSystemStore.getState().triggerWake();
      }
    };
    
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [booted]);

  // ── Flash overlay control ──
  useEffect(() => {
    if (bootPhase === 'flash' && flashRef.current) {
      flashRef.current.style.opacity = '1';
    }
    if (bootPhase === 'done' && flashRef.current) {
      setTimeout(() => {
        if (flashRef.current) flashRef.current.style.opacity = '0';
      }, 100);
    }
  }, [bootPhase]);

  // ── Command handler ── Routes to live agent WebSocket
  const handleCommand = useCallback((cmd) => {
    sendCommand(cmd);
  }, []);

  // ── Global Interrupt Listener ──
  useEffect(() => {
    const handleKey = (e) => {
      // Allow Escape to interrupt ongoing missions if system is active
      if (e.key === 'Escape' && state !== 'idle') {
        e.preventDefault();
        sendInterrupt();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [state]);

  // ── Dynamic state classes ──
  const isIdle = state === 'idle';
  const isProcessing = state === 'processing' || state === 'speaking';
  const isSecurityMode = mode === 'security';
  const isFullyBooted = bootPhase === 'done';

  const bodyClasses = [
    isSecurityMode ? 'security-mode' : '',
    isIdle ? 'idle-mode' : '',
    isProcessing ? 'processing' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={`jarvis-root ${bodyClasses}`}>
      {/* ═══ BACKGROUND CANVAS ═══ */}
      <Background />

      {/* ═══ FLASH OVERLAY ═══ */}
      <div ref={flashRef} className="flash-overlay" />

      {/* ═══ STANDBY HINT — visible only before boot ═══ */}
      {!booted && (
        <div className="standby-hint">
          <span className="standby-text">Say "Hey Jarvis" to begin</span>
          <span className="standby-sub">or press Enter</span>
        </div>
      )}

      {/* ═══ HUD LAYER ═══ */}
      <div className={`hud-layer ${isIdle ? 'idle-hud' : ''}`}>
        {/* Crosshairs */}
        <div className="crosshair v" />
        <div className="crosshair h" />

        {/* Core System */}
        <CoreSystem />

        {/* HUD Panels — ALL appear simultaneously when bootPhase='done' */}
        <SystemHardware />
        <Diagnostics />
        <Dashboard />
        <Terminal />

        {/* Task Panel */}
        <TaskPanel />

        {/* Command Input — only shows after full boot */}
        {isFullyBooted && <CommandInput onCommand={handleCommand} />}
      </div>

      {/* ═══ NOTIFICATIONS ═══ */}
      <Notifications />

      {/* ═══ FIX 6: CONFIRMATION DIALOG — blocks UI for destructive commands ═══ */}
      <ConfirmationDialog />
    </div>
  );
}
