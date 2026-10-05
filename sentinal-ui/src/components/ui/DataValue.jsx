import { useEffect, useRef, useState } from 'react';
import useSystemStore from '../../store/useSystemStore';

/* ═══════════════════════════════════════════════════════════════
   DATAVALUE — Animated data-arrival component
   
   Detects when a value transitions from null/"—" to real data.
   On arrival:  quick fade-in + subtle glow flash
   On update:   fast count-up for numbers, instant swap for text
   
   Props:
     value     — raw value from store (null = awaiting)
     format    — fn(value) → display string   (optional)
     suffix    — appended after formatted value (e.g. "%", "°C")
     fallback  — what to show when null  (default: "—")
     countUp   — enable count-up for numbers (default: false)
     style     — passthrough style object
     className — passthrough className
   ═══════════════════════════════════════════════════════════════ */

export default function DataValue({ 
  value, 
  format, 
  suffix = '', 
  fallback = '—',
  countUp = false,
  style = {},
    className = 'data-value',
    fieldKey = null,
  }) {
    const { lastUpdate } = useSystemStore();
    const prevRef = useRef(value);
    const [arrived, setArrived] = useState(false);
    const [isStale, setIsStale] = useState(false);
    const [displayNum, setDisplayNum] = useState(value);
    const displayedRef = useRef(value);
    const rafRef = useRef(null);
  
    // ── Staleness Monitor ──
    const STALE_MS = 5000;
    useEffect(() => {
      const checkStaleness = () => {
        if (!fieldKey || value === null) return;
        const ts = lastUpdate[fieldKey];
        if (!ts) return;
        setIsStale(Date.now() - ts > STALE_MS);
      };
  
      const interval = setInterval(checkStaleness, 1000);
      checkStaleness();
      return () => clearInterval(interval);
    }, [value, fieldKey, lastUpdate]);
  
    // ── Detect null → real transition ──
  useEffect(() => {
    const wasNull = prevRef.current === null || prevRef.current === undefined;
    const isReal = value !== null && value !== undefined;
    
    const frame = wasNull && isReal ? requestAnimationFrame(() => setArrived(true)) : null;
    prevRef.current = value;
    return () => { if (frame !== null) cancelAnimationFrame(frame); };
  }, [value]);

  // ── Count-up animation for numeric values ──
  useEffect(() => {
    if (!countUp || value === null || value === undefined || typeof value !== 'number') {
      return;
    }

    const target = value;
    const start = typeof displayedRef.current === 'number' ? displayedRef.current : 0;
    const diff = target - start;
    
    const duration = 400; // ms
    const startTime = performance.now();

    function tick(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      displayedRef.current = start + diff * eased;
      setDisplayNum(displayedRef.current);
      
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setDisplayNum(target);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, countUp]);

  // ── Render ──
  if (value === null || value === undefined) {
    return <span className={className} style={{ ...style, opacity: 0.25 }}>{fallback}</span>;
  }

  const numToShow = countUp && typeof value === 'number' && typeof displayNum === 'number' ? displayNum : value;
  const text = format ? format(numToShow) : `${typeof numToShow === 'number' ? Math.round(numToShow) : numToShow}`;
  
  return (
    <span 
      className={`${className} ${arrived ? 'dv-arrive' : ''} ${isStale ? 'stale-value' : ''}`} 
      style={style}
      onAnimationEnd={() => setArrived(false)}
    >
      {text}{suffix}
    </span>
  );
}
