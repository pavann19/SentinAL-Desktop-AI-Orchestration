/* ═══════════════════════════════════════════════════════════════
   MESSAGE ADAPTER LAYER
   
   All backend WebSocket messages pass through here FIRST.
   Raw server payloads → clean UI-friendly structures.
   Never let raw backend format leak into Zustand or components.
   ═══════════════════════════════════════════════════════════════ */

import useSystemStore from '../store/useSystemStore';

// ── Backend → UI State Mapping ──────────────────────────────────
// Maps the backend's execution "stage" string to a valid UI system state.
const STAGE_TO_STATE = {
  perception:     'thinking',
  governance:     'analyzing',
  researching:    'processing',
  actuation:      'executing',
};

// ── Backend Log Level Mapping ────────────────────────────────────
// Maps backend message types to the UI log tag and severity.
const TYPE_TO_LOG = {
  execution_step: { tag: 'REACT', type: 'warn'    },
  final_response: { tag: 'DONE',  type: 'success' },
  error:          { tag: 'ERR',   type: 'crit'    },
};

// ── Stage Label Mapping (for display in Terminal) ────────────────
const STAGE_PREFIX = {
  perception:  'THINK',
  governance:  'GUARD',
  researching: 'OBS',
  actuation:   'ACT',
};

/**
 * adaptAgentMessage(payload)
 * 
 * Transforms a raw /ws/agent server message into a set of
 * imperative UI actions to be dispatched to the Zustand store.
 * 
 * Returns an object describing what the UI should do:
 * {
 *   systemState: string | null,   → set this as the new system state
 *   log: { tag, text, type },     → add this log entry
 *   notification: { msg, type } | null,
 *   taskAction: 'start' | 'complete' | 'fail' | null,
 *   isFinalResponse: bool,
 *   finalMessage: string | null,
 * }
 */
export function adaptAgentMessage(payload) {
  const { type, message = '', stage = '', status } = payload;

  const logMeta = TYPE_TO_LOG[type] || { tag: 'SYS', type: 'info' };
  const stageLabel = STAGE_PREFIX[stage];
  const tag = stageLabel ? `REACT::${stageLabel}` : logMeta.tag;

  let systemState = null;
  let taskAction = null;
  let notification = null;
  let isFinalResponse = false;
  let finalMessage = null;

  if (type === 'execution_step') {
    if (status === 'failed') {
      systemState = 'cooldown';
      taskAction = 'fail';
    } else {
      systemState = STAGE_TO_STATE[stage] || 'processing';
      // First perception step = start of a new task
      if (stage === 'perception') {
        taskAction = 'start';
      }
    }
  }

  if (type === 'final_response') {
    systemState = 'cooldown';
    taskAction = 'complete';
    isFinalResponse = true;
    finalMessage = payload.final_response || message;
    notification = { msg: 'Mission Complete', type: 'success' };
  }

  if (type === 'error' || type === 'interrupted' || type === 'system_overload') {
    const isCritical = message.startsWith('Security Block:');
    let errorMsg = 'Command Error';
    if (type === 'interrupted') errorMsg = 'Mission Interrupted';
    if (type === 'system_overload') errorMsg = 'System Capacity Exceeded';
    if (isCritical) errorMsg = 'Security Block Active';

    systemState = 'cooldown';
    taskAction = 'fail';
    notification = {
      msg: errorMsg,
      type: type === 'interrupted' ? 'warn' : 'crit',
    };
  }

  if (type === 'speech_start') {
    systemState = 'speaking';
    taskAction = 'speech_start';
  }

  if (type === 'speech_end') {
    systemState = 'cooldown';
    taskAction = 'speech_end';
  }

  // FIX 6: Handle requires_confirmation from backend (FileDeletionIntent)
  if (type === 'requires_confirmation') {
    useSystemStore.getState().requestConfirmation(payload.command || message);
  }

  return {
    systemState,
    log: logMeta ? {
      tag,
      text: message,
      type: logMeta.type,
    } : null,
    notification,
    taskAction,
    isFinalResponse,
    finalMessage,
  };
}

/**
 * adaptTelemetryMessage(payload)
 * 
 * Transforms a raw /ws/telemetry server message into only what the
 * UI store needs. Applies a meaningful-change threshold to avoid
 * excessive re-renders (throttle by value delta).
 * 
 * Returns { cpu, ram, temp } or null if change is negligible.
 */
const TELEMETRY_THRESHOLD = 1.5; // Minimum % change to trigger a UI update
let _lastTelemetry = { cpu: -1, ram: -1 };

export function adaptTelemetryMessage(payload) {
  const hw = payload?.hardware;
  const env = payload?.environment;
  const sys = payload?.system;
  const gov = payload?.governance;

  if (!hw) return null;

  const cpu  = Math.round(hw.cpu_percent ?? _lastTelemetry.cpu);
  const ram  = Math.round(hw.ram_percent ?? _lastTelemetry.ram);
  const gpu  = hw.gpu_percent !== null && hw.gpu_percent !== undefined ? Math.round(hw.gpu_percent) : null;
  // Use real temperature from backend if available, else fallback safely
  const temp = (env?.temperature !== undefined && env?.temperature !== null) ? env.temperature : 
               (hw?.temperature !== undefined && hw?.temperature !== null ? hw.temperature : 0);

  const cpuDelta = Math.abs(cpu - _lastTelemetry.cpu);
  const ramDelta = Math.abs(ram - _lastTelemetry.ram);

  // Skip update if change is negligible (throttle)
  if (cpuDelta < TELEMETRY_THRESHOLD && ramDelta < TELEMETRY_THRESHOLD) {
    return null;
  }

  _lastTelemetry = { cpu, ram };
  
  return { 
    cpu, 
    ram, 
    gpu,
    temp,
    envFiles: env?.file_count ?? 0,
    envDirs: env?.directories ?? [],
    sysUptime: sys?.uptime_percent ?? 0,
    sysCoreStatus: sys?.ai_core_status ?? 'UNKNOWN',
    sysThreat: sys?.threat_level ?? 'UNKNOWN',
    govClearance: gov?.clearance ?? 'UNKNOWN',
  };
}

/**
 * adaptGovernanceLogs(payload)
 * 
 * Extracts the latest_logs array from the telemetry stream
 * and formats them for the UI Terminal/Governance log component.
 * Returns an array of { tag, text, type } or empty array.
 */
export function adaptGovernanceLogs(payload) {
  const raw = payload?.latest_logs;
  if (!Array.isArray(raw) || raw.length === 0) return [];

  return raw.map((entry) => ({
    tag: 'GOV',
    text: `[${entry.execution_status ?? 'INFO'}] ${entry.input ?? ''}`.trim(),
    type: entry.execution_status === 'Error' ? 'crit' : 'info',
  }));
}
