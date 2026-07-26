import { useState, useRef, useEffect, useCallback } from 'react';
import useSystemStore from '../../store/useSystemStore';

/* ═══════════════════════════════════════════════════
   COMMAND MODE — Invisible System Command Line
   
   Activation: "/" or "Enter"
   Cancel: "Escape"
   Auto-dismiss after command execution
   ═══════════════════════════════════════════════════ */

export default function CommandInput({ onCommand }) {
  const { bootPhase } = useSystemStore();
  const [active, setActive] = useState(false);
  const [value, setValue] = useState('');
  const [visible, setVisible] = useState(false); // controls CSS transition
  const inputRef = useRef(null);

  // ── Global keyboard listener ──
  useEffect(() => {
    if (bootPhase !== 'done') return;

    const handleKeyDown = (e) => {
      // Ignore if already typing in an input
      if (active) return;

      if (e.key === '/' || e.key === 'Enter') {
        e.preventDefault();
        setActive(true);
        setValue('');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [bootPhase, active]);

  // ── Focus & animate in when active ──
  useEffect(() => {
    if (active) {
      // Trigger CSS transition on next frame
      requestAnimationFrame(() => setVisible(true));
      // Focus the input after mount
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [active]);

  // ── Dismiss handler ──
  const dismiss = useCallback(() => {
    setVisible(false);
    // Wait for fade-out transition to complete
    setTimeout(() => {
      setActive(false);
      setValue('');
    }, 300);
  }, []);

  // ── Submit handler ──
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      dismiss();
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = value.trim();
      if (!cmd) {
        dismiss();
        return;
      }
      onCommand(cmd);
      dismiss();
    }
  }, [value, onCommand, dismiss]);

  if (bootPhase !== 'done') return null;
  if (!active) return null;

  return (
    <>
      {/* Subtle dim overlay */}
      <div
        className="cmd-overlay"
        style={{ opacity: visible ? 1 : 0 }}
        onClick={dismiss}
      />

      {/* Floating command line */}
      <div
        className="cmd-line"
        style={{
          opacity: visible ? 1 : 0,
          transform: visible ? 'translateX(-50%) translateY(0)' : 'translateX(-50%) translateY(12px)',
        }}
      >
        <span className="cmd-prefix">›</span>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          spellCheck="false"
          autoComplete="off"
          className="cmd-input"
        />
      </div>
    </>
  );
}
