import { create } from 'zustand';

const useSystemStore = create((set, get) => ({
  // ── System State ──
  booted: false,
  isWaking: false,      // Confirmation phase before boot
  bootPhase: 'none',    // 'none' | 'spinup' | 'fiery' | 'flash' | 'done'
  mode: 'assist',        // 'assist' | 'security'
  state: 'offline',      // 'offline' | 'booting' | 'idle' | 'listening' | 'processing' | 'cooldown'
  
  // ── Hardware Telemetry (null = awaiting backend) ──
  cpu: null,
  ram: null,
  temp: null,
  gpu: null,
  
  // ── Extended Backend Telemetry (null = awaiting backend) ──
  envFiles: null,
  envDirs: null,
  sysUptime: null,
  sysCoreStatus: null,
  sysThreat: null,
  govClearance: null,

  // ── Telemetry Freshness Tracking ──
  lastUpdate: {}, // fieldKey -> timestamp


  // ── Task System ──
  currentTask: null,
  taskProgress: 0,
  taskStatus: 'idle',    // 'idle' | 'executing' | 'completed' | 'failed'
  taskQueue: [],

  // ── Logs ──
  logs: [],
  maxLogs: 50,

  // ── Notifications ──
  notifications: [],

  // ── Session Context ──
  lastTask: 'None',
  lastTaskStatus: 'Awaiting Input',

  // ── WebSocket Connection Status ──
  // 'connecting' | 'connected' | 'disconnected' | 'error'
  wsStatus: { telemetry: 'connecting', agent: 'connecting' },

  // ── FIX 6: Confirmation Dialog State ──
  // Populated when a destructive operation requires explicit user approval.
  confirmationPending: false,
  confirmationCommand: null,  // The raw command text awaiting approval

  // ── Actions ──
  boot: () => set({ booted: true, state: 'booting', bootPhase: 'spinup' }),
  
  setBootPhase: (phase) => set({ bootPhase: phase }),

  setSystemState: (state) => set({ state }),

  // FIX 6: Confirmation dialog actions
  requestConfirmation: (command) => set({ confirmationPending: true, confirmationCommand: command }),
  resolveConfirmation: () => set({ confirmationPending: false, confirmationCommand: null }),
  
  toggleMode: () => set((s) => {
    const newMode = s.mode === 'assist' ? 'security' : 'assist';
    return { mode: newMode };
  }),

  setTelemetry: (data) => set((s) => {
    const now = Date.now();
    const updates = { ...s.lastUpdate };
    Object.keys(data).forEach((k) => (updates[k] = now));
    return { ...data, lastUpdate: updates };
  }),

  resetTelemetry: () => set({
    cpu: null,
    ram: null,
    temp: null,
    gpu: null,
    envFiles: null,
    envDirs: null,
    sysUptime: null,
    sysCoreStatus: null,
    sysThreat: null,
    govClearance: null,
    lastUpdate: {},
  }),

  cooldownTimerId: null,

  // ── Task Actions ──
  startTask: (name) => set((s) => {
    if (s.cooldownTimerId) clearTimeout(s.cooldownTimerId);
    return {
      currentTask: name,
      taskProgress: 0,
      taskStatus: 'executing',
      state: 'processing',
      cooldownTimerId: null,
    };
  }),

  updateTaskProgress: (progress) => set({ taskProgress: Math.min(progress, 100) }),

  completeTask: (status) => set((s) => ({
    taskStatus: status,
    taskProgress: 100,
    // state is not set here explicitly if speech is going to handle it, but we can set it to cooldown
    state: status === 'failed' ? 'cooldown' : s.state, 
    lastTask: s.currentTask?.substring(0, 20) + '...',
    lastTaskStatus: status === 'completed' ? 'Completed' : 'Failed',
  })),

  setCooldownTimer: (timerId) => set((s) => {
    if (s.cooldownTimerId) clearTimeout(s.cooldownTimerId);
    return { cooldownTimerId: timerId };
  }),

  clearTask: () => set({
    currentTask: null,
    taskProgress: 0,
    taskStatus: 'idle',
  }),

  enqueueTask: (name) => set((s) => ({
    taskQueue: [...s.taskQueue, name],
  })),

  dequeueTask: () => set((s) => {
    const [next, ...rest] = s.taskQueue;
    return { taskQueue: rest };
  }),

  // ── Log Actions ──
  addLog: (tag, text, type = 'info') => set((s) => ({
    logs: [...s.logs.slice(-s.maxLogs), { 
      id: Date.now() + Math.random(), 
      tag, 
      text, 
      type, 
      timestamp: Date.now() 
    }],
  })),

  // ── Notification Actions ──
  addNotification: (msg, type = 'info') => {
    const id = Date.now() + Math.random();
    set((s) => ({
      notifications: [...s.notifications, { id, msg, type }],
    }));
    setTimeout(() => {
      set((s) => ({
        notifications: s.notifications.filter((n) => n.id !== id),
      }));
    }, 3500);
  },

  finishBoot: () => set({ booted: true, state: 'idle', bootPhase: 'done' }),

  triggerWake: () => {
    const s = get();
    if (!s.booted && !s.isWaking) {
      set({ isWaking: true });
      setTimeout(() => {
        set({ isWaking: false });
        get().runBootSequence();
      }, 400);
    }
  },

  runBootSequence: () => {
    const { boot, addLog, setBootPhase, addNotification, finishBoot } = get();
    boot(); // state='booting', bootPhase='spinup'
    addLog('SYS', 'Loading OS Kernel v4.2.1...', 'warn');
    
    setTimeout(() => addLog('SYS', 'Initializing AI Modules...', 'info'), 500);
    setTimeout(() => addLog('NET', 'Connecting to Neural Grid...', 'warn'), 1000);
    
    setTimeout(() => {
      addLog('WARN', 'CRITICAL VELOCITY REACHED.', 'crit');
      setBootPhase('fiery');
    }, 1500);

    setTimeout(() => {
      addLog('OK', 'System Fully Online. Access Granted.', 'success');
      addNotification('OS SentinAL Booted Successfully', 'success');
      setBootPhase('flash');
    }, 3500);

    setTimeout(() => {
      finishBoot(); // state='idle', bootPhase='done'
    }, 3900);
  },
}));

export default useSystemStore;
