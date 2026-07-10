import { useEffect, useRef } from 'react';
import useSystemStore from '../../store/useSystemStore';

/* ═══════════════════════════════════════════════════════════════
   STRICT CORE ROTATING GEAR SYSTEM
   
   LAYER 1 (Inner): Dotted Circle (300px) - Rotating CW
   LAYER 2 (Middle): Gear-Hybrid (380px) - Rotating CCW
   LAYER 3 (Outer): Balanced Arcs (460px) - Rotating CW System
   
   All layers share a single Canvas for perfect concentricity.
   ═══════════════════════════════════════════════════════════════ */

export default function CoreSystem() {
  const coreCanvasRef = useRef(null);
  const requestRef = useRef(null);

  // ═══ CORE RENDER ENGINE ═══
  useEffect(() => {
    const canvas = coreCanvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const size = 600;
    canvas.width = size;
    canvas.height = size;
    const cx = size / 2;
    const cy = size / 2;

    let startTime = null;
    let rotation = 0; // Persistent rotation state

    // Geometry Config
    const r1 = 150; // 300px
    const r2 = 190; // 380px
    const r3 = 230; // 460px
    const arcLen = Math.PI * 0.5; // Corrected to 25% coverage

    // ── Helper: Draw Dotted Circle ──
    const drawDottedCircle = (radius, count, angleOffset, opacity) => {
      ctx.beginPath();
      for (let i = 0; i < count; i++) {
        const theta = (i / count) * Math.PI * 2 + angleOffset;
        const x = cx + radius * Math.cos(theta);
        const y = cy + radius * Math.sin(theta);
        ctx.moveTo(x, y);
        ctx.arc(x, y, 1.2, 0, Math.PI * 2);
      }
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${opacity})`;
      ctx.fill();
    };

    // ── Helper: Draw Gear Ticks ──
    const drawGearTicks = (radius, count, angleOffset, opacity) => {
      ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${opacity})`;
      ctx.lineWidth = 2; // slightly more visible
      for (let i = 0; i < count; i++) {
        const theta = (i / count) * Math.PI * 2 + angleOffset;
        const xStart = cx + (radius - 5) * Math.cos(theta);
        const yStart = cy + (radius - 5) * Math.sin(theta);
        const xEnd = cx + (radius + 5) * Math.cos(theta);
        const yEnd = cy + (radius + 5) * Math.sin(theta);
        ctx.beginPath();
        ctx.moveTo(xStart, yStart);
        ctx.lineTo(xEnd, yEnd);
        ctx.stroke();
      }
    };

    let r = 0, g = 243, b = 255; // Default Cyan

    function animate(time) {
      if (!startTime) startTime = time;
      
      // Pulse and Logic from Store
      const { state, bootPhase, mode, booted, isWaking } = useSystemStore.getState();
      const isSecurity = mode === 'security';
      const isFiery = bootPhase === 'fiery';

      r = isSecurity ? 255 : (isFiery ? 255 : 0);
      g = isSecurity ? 0 : (isFiery ? 176 : 243);
      b = isSecurity ? 60 : (isFiery ? 0 : 255);
      
      let speedBase = 0.15;
      if (bootPhase === 'spinup') speedBase = 1.0;
      if (bootPhase === 'fiery') speedBase = 4.0;
      if (state === 'processing') speedBase = 0.8;
      if (state === 'speaking') speedBase = 0.5; // Audio playback speed
      if (state === 'listening') speedBase = 0.4;
      if (state === 'idle') speedBase = 0.08;

      rotation += speedBase * 0.016; 
      const innerRot = rotation * 0.2;        // Very slow CW
      const middleRot = -rotation * 0.5;     // Slightly faster CCW
      const outerRot = rotation * 1.0;       // Primary motion CW

      ctx.clearRect(0, 0, size, size);

      // ── SUBTLE CENTRAL PULSING GLOW ("Energy") ──
      // Very slow organic pulse (period = ~6 seconds)
      const basePulse = Math.sin(time * 0.001) * 0.03;
      
      // Secondary Listening Pulse (only in standby)
      // Slightly faster frequency, extremely subtle amplitude
      let listeningPulse = 0;
      if (!booted && !isWaking) {
        listeningPulse = Math.sin(time * 0.0025) * 0.015;
      }
      
      // Wake Confirmation Flash (Intensification)
      let wakeFlash = 0;
      if (isWaking) {
        wakeFlash = 0.25; // Significant brightness jump
      }
      
      const glowAlpha = 0.1 + basePulse + listeningPulse + wakeFlash;
      const glowRadius = isWaking ? 220 : 140; // Expand glow during wake
      
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius);
       glow.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${glowAlpha})`);
      glow.addColorStop(0.6, `rgba(${r}, ${g}, ${b}, ${glowAlpha * 0.4})`);
      glow.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, size, size);

      // ── LAYER 1: Inner Dotted (CW) ──
      drawDottedCircle(r1, 80, innerRot, 0.9);

      // ── LAYER 2: Middle Gear-Hybrid (CCW) ──
      drawDottedCircle(r2, 100, middleRot, 0.6);
      drawGearTicks(r2, 40, middleRot, 0.5); 

      // ── LAYER 3: OUTER ARCS (Heavier Motion) ──
      ctx.lineWidth = 3; // Increased thickness
      ctx.lineCap = 'round';
      ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.85)`;
      ctx.shadowBlur = isFiery ? 40 : 15; // Soft cyan glow
      ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.45)`;

      // Arc 1
      ctx.beginPath();
      ctx.arc(cx, cy, r3, outerRot, outerRot + arcLen);
      ctx.stroke();

      // Arc 2 (180 offset)
      const offsetTheta = outerRot + Math.PI;
      ctx.beginPath();
      ctx.arc(cx, cy, r3, offsetTheta, offsetTheta + arcLen);
      ctx.stroke();

      ctx.shadowBlur = 0;
      requestRef.current = requestAnimationFrame(animate);
    }

    requestRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(requestRef.current);
  }, []);

  const { booted, state, bootPhase } = useSystemStore();

  return (
    <div className="core-container" style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: 600, height: 600 }}>
      {/* Consolidate all layers into a single canvas for perfect center lock */}
      <canvas
        ref={coreCanvasRef}
        className="absolute pointer-events-none"
        style={{ width: 600, height: 600, zIndex: 2 }}
      />

      {/* Core Text */}
      <div className="core-text" style={{ zIndex: 5, position: 'absolute', width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {!booted ? (
          null
        ) : state === 'booting' ? (
          <span style={{ color: 'var(--stark-gold)', animation: 'none' }}>IGNITING KERNEL...</span>
        ) : (
          <span className="core-text-jarvis">J.A.R.V.I.S.</span>
        )}
      </div>
    </div>
  );
}
