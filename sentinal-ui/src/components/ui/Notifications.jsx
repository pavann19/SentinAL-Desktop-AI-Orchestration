import { AnimatePresence, motion } from 'framer-motion';
import useSystemStore from '../../store/useSystemStore';

/* ═══════════════════════════════════════════════════
   NOTIFICATIONS — Top Center
   ═══════════════════════════════════════════════════ */

export default function Notifications() {
  const { notifications } = useSystemStore();

  const typeStyles = {
    info: { borderColor: 'var(--stark-cyan)', boxShadow: '0 0 15px var(--stark-cyan-glow)', color: '#fff' },
    warn: { borderColor: 'var(--stark-gold)', boxShadow: '0 0 15px var(--stark-gold)', color: 'var(--stark-gold)' },
    success: { borderColor: 'var(--stark-green)', boxShadow: '0 0 15px var(--stark-green)', color: 'var(--stark-green)' },
    crit: { borderColor: 'var(--stark-red)', boxShadow: '0 0 15px var(--stark-red)', color: 'var(--stark-red)', fontWeight: 'bold' },
  };

  return (
    <div className="notify-container">
      <AnimatePresence>
        {notifications.map((n) => (
          <motion.div
            key={n.id}
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3, ease: [0.175, 0.885, 0.32, 1.275] }}
            style={{
              background: 'rgba(0, 0, 0, 0.9)',
              borderWidth: '1px',
              borderStyle: 'solid',
              padding: '10px 20px',
              fontFamily: 'var(--font-data)',
              fontSize: '0.9rem',
              ...(typeStyles[n.type] || typeStyles.info),
            }}
          >
            {n.msg}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
