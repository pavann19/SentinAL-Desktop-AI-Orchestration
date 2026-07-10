import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import useSystemStore from '../../store/useSystemStore';

/* ═══════════════════════════════════════════════════════════════
   THREE.JS BACKGROUND SYSTEM
   - 3D Particle Field (Points)
   - Spatial Connections (LineSegments)
   - Cinematic Camera Drift & Parallax
   - Depth-based Fog & Scaling
   ═══════════════════════════════════════════════════════════════ */

export default function Background() {
  const containerRef = useRef(null);
  const cleanupRef = useRef(null);
  const mouseRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // ── SCENE SETUP ──
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x020202, 0.0015);

    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 2000);
    camera.position.z = 800;

    const renderer = new THREE.WebGLRenderer({ 
      antialias: true, 
      alpha: true,
      powerPreference: "high-performance"
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    container.appendChild(renderer.domElement);

    // ── PARTICLES SETUP ──
    const particleCount = 600;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const sizes = new Float32Array(particleCount);
    const opacities = new Float32Array(particleCount);

    for (let i = 0; i < particleCount; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 1500;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 1500;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 1500;
      sizes[i] = 1.0 + Math.random() * 2.0;
      opacities[i] = 0.1 + Math.random() * 0.4;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const material = new THREE.PointsMaterial({
      color: 0x00f3ff,
      size: 2,
      transparent: true,
      opacity: 0.3,
      sizeAttenuation: true,
      blending: THREE.AdditiveBlending
    });

    const particles = new THREE.Points(geometry, material);
    scene.add(particles);

    // ── CONNECTIONS SETUP ──
    const lineGeometry = new THREE.BufferGeometry();
    const lineMaterial = new THREE.LineBasicMaterial({ 
      color: 0x00f3ff, 
      transparent: true, 
      opacity: 0.05,
      blending: THREE.AdditiveBlending 
    });
    const lineSegments = new THREE.LineSegments(lineGeometry, lineMaterial);
    scene.add(lineSegments);

    // ── EVENT LISTENERS ──
    const onMouseMove = (e) => {
      mouseRef.current.x = (e.clientX / window.innerWidth - 0.5) * 2;
      mouseRef.current.y = (e.clientY / window.innerHeight - 0.5) * 2;
    };

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('resize', onResize);

    // ── ANIMATION LOOP ──
    let time = 0;
    function animate() {
      const animId = requestAnimationFrame(animate);
      time += 0.001;

      // System Mode Handling
      const mode = useSystemStore.getState().mode;
      const themeColor = mode === 'security' ? 0xff003c : 0x00f3ff;
      material.color.setHex(themeColor);
      lineMaterial.color.setHex(themeColor);

      // Camera Drift & Parallax
      camera.position.x += (mouseRef.current.x * 100 - camera.position.x) * 0.02;
      camera.position.y += (-mouseRef.current.y * 100 - camera.position.y) * 0.02;
      camera.lookAt(scene.position);

      scene.rotation.y = time * 0.1; // Gentle drift

      // Dynamic Connections logic (every few frames for perf)
      if (Math.floor(time * 1000) % 5 === 0) {
        const linePositions = [];
        const posAttribute = geometry.attributes.position;
        const maxDist = 150;

        // Optimization: Subset of particles for connections
        for (let i = 0; i < particleCount; i += 4) {
          for (let j = i + 4; j < particleCount; j += 4) {
            const dx = posAttribute.getX(i) - posAttribute.getX(j);
            const dy = posAttribute.getY(i) - posAttribute.getY(j);
            const dz = posAttribute.getZ(i) - posAttribute.getZ(j);
            const distSq = dx * dx + dy * dy + dz * dz;

            if (distSq < maxDist * maxDist) {
              linePositions.push(
                posAttribute.getX(i), posAttribute.getY(i), posAttribute.getZ(i),
                posAttribute.getX(j), posAttribute.getY(j), posAttribute.getZ(j)
              );
            }
          }
        }
        lineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
      }

      renderer.render(scene, camera);
    }

    animate();

    cleanupRef.current = () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('resize', onResize);
      renderer.dispose();
      container.removeChild(renderer.domElement);
    };

    return cleanupRef.current;
  }, []);

  return (
    <div 
      ref={containerRef} 
      id="bg-3d-container"
      className="fixed top-0 left-0 w-full h-full z-0 overflow-hidden pointer-events-none"
      style={{
        background: 'radial-gradient(circle at center, #020202 0%, #000 100%)'
      }}
    />
  );
}
