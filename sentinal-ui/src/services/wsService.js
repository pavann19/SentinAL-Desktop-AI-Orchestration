/* ═══════════════════════════════════════════════════════════════
   WEBSOCKET SERVICE LAYER
   
   Two isolated, self-reconnecting WebSocket connections:
   - TelemetrySocket → /ws/telemetry (recv only)
   - AgentSocket     → /ws/agent     (send + recv)
   
   Both use exponential backoff and do NOT crash the UI on failure.
   All incoming messages are routed through messageAdapter.js BEFORE
   touching the Zustand store.
   ═══════════════════════════════════════════════════════════════ */

import useSystemStore from '../store/useSystemStore';
import {
  adaptAgentMessage,
  adaptTelemetryMessage,
  adaptGovernanceLogs,
} from './messageAdapter';

const BASE_URL = 'ws://localhost:8000';
const MAX_BACKOFF_MS = 30_000;

// ── Connection status reporting ──────────────────────────────────
// Updates a lightweight connection status in the store.
// We add `wsStatus` field — no layout/animation impact.
function setWsStatus(channel, status) {
  useSystemStore.setState((s) => ({
    wsStatus: { ...s.wsStatus, [channel]: status },
  }));
}


/* ════════════════════════════════════════════════════════════════
   TELEMETRY SOCKET — /ws/telemetry
   Receive-only. 1s cadence from server.
   ════════════════════════════════════════════════════════════════ */
class TelemetrySocket {
  constructor() {
    this._ws = null;
    this._backoff = 1_000;
    this._destroyed = false;
    this._retryTimer = null;
  }

  connect() {
    if (this._destroyed) return;
    setWsStatus('telemetry', 'connecting');

    const ws = new WebSocket(`${BASE_URL}/ws/telemetry`);
    this._ws = ws;

    ws.onopen = () => {
      this._backoff = 1_000; // reset backoff on success
      setWsStatus('telemetry', 'connected');
      console.debug('[WS:telemetry] Connected.');
    };

    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        
        if (payload.type === 'wake' || payload.type === 'wake_ack') {
          useSystemStore.getState().triggerWake();
          return;
        }

        const store = useSystemStore.getState();

        // ── 1. Throttled Telemetry Update ──
        const hw = adaptTelemetryMessage(payload);
        if (hw) {
          store.setTelemetry(hw);
        }

        // ── 2. Governance Logs (passive, non-destructive) ──
        // Only add novel log entries if system is in idle state to
        // avoid polluting the terminal during active agent tasks.
        if (store.state === 'idle' || store.state === 'cooldown') {
          const govLogs = adaptGovernanceLogs(payload);
          // Only add the latest entry (avoid log flooding on reconnect)
          if (govLogs.length > 0) {
            const latest = govLogs[govLogs.length - 1];
            if (latest.text.trim() && latest.text !== '[INFO] ') {
              store.addLog(latest.tag, latest.text, latest.type);
            }
          }
        }
      } catch {
        // Silently discard malformed frames
      }
    };

    ws.onerror = () => {
      setWsStatus('telemetry', 'error');
      // [INDUSTRY STANDARD] UI HYDRATION: Preserve last known state instead of resetting telemetry
    };

    ws.onclose = () => {
      if (this._destroyed) return;
      setWsStatus('telemetry', 'disconnected');
      // [INDUSTRY STANDARD] UI HYDRATION: Do not clear visual dashboard on micro-disconnects
      console.warn(`[WS:telemetry] Disconnected. Retrying in ${this._backoff / 1000}s...`);
      this._retryTimer = setTimeout(() => {
        this._backoff = Math.min(this._backoff * 2, MAX_BACKOFF_MS);
        this.connect();
      }, this._backoff);
    };
  }

  destroy() {
    this._destroyed = true;
    clearTimeout(this._retryTimer);
    this._ws?.close();
  }
}


/* ════════════════════════════════════════════════════════════════
   AGENT SOCKET — /ws/agent
   Full-duplex. Send commands, receive execution stream.
   ════════════════════════════════════════════════════════════════ */
class AgentSocket {
  constructor() {
    this._ws = null;
    this._backoff = 1_000;
    this._destroyed = false;
    this._retryTimer = null;
    this._currentTaskName = null;
  }

  connect() {
    if (this._destroyed) return;
    setWsStatus('agent', 'connecting');

    const ws = new WebSocket(`${BASE_URL}/ws/agent`);
    this._ws = ws;

    ws.onopen = () => {
      this._backoff = 1_000;
      setWsStatus('agent', 'connected');
      console.debug('[WS:agent] Connected.');

      // Announce connection in the terminal log
      useSystemStore.getState().addLog('SYS', 'Agent link established. Neural pipeline online.', 'success');
    };

    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        const adapted = adaptAgentMessage(payload);
        const store = useSystemStore.getState();

        // ── 1. System State Transition ──
        if (adapted.systemState) {
          store.setSystemState(adapted.systemState);
        }

        // ── 2. Task Lifecycle ──
        if (adapted.taskAction === 'start' && this._currentTaskName) {
          store.startTask(this._currentTaskName);
        }
        if (adapted.taskAction === 'complete') {
          store.completeTask('completed');
        }
        if (adapted.taskAction === 'speech_start') {
          // System state already set to speaking by adapted.systemState
          if (store.cooldownTimerId) clearTimeout(store.cooldownTimerId);
        }
        if (adapted.taskAction === 'speech_end') {
          // Lock in the cooldown state and set managed timer
          const timerId = setTimeout(() => {
            const s = useSystemStore.getState();
            if (s.state === 'cooldown') {
              s.setSystemState('idle');
              s.clearTask();
            }
          }, 2500);
          store.setCooldownTimer(timerId);
        }
        if (adapted.taskAction === 'fail') {
          store.completeTask('failed');
          const timerId = setTimeout(() => {
            const s = useSystemStore.getState();
            if (s.state === 'cooldown') {
              s.setSystemState('idle');
              s.clearTask();
            }
          }, 2500);
          store.setCooldownTimer(timerId);
        }

        // ── 3. Log Entry ──
        store.addLog(adapted.log.tag, adapted.log.text, adapted.log.type);

        // ── 4. Notification (if any) ──
        if (adapted.notification) {
          store.addNotification(adapted.notification.msg, adapted.notification.type);
        }
      } catch {
        // Silently discard malformed frames
      }
    };

    ws.onerror = () => {
      setWsStatus('agent', 'error');
    };

    ws.onclose = () => {
      if (this._destroyed) return;
      setWsStatus('agent', 'disconnected');
      console.warn(`[WS:agent] Disconnected. Retrying in ${this._backoff / 1000}s...`);
      useSystemStore.getState().addLog('WARN', 'Agent link lost. Reconnecting...', 'warn');

      this._retryTimer = setTimeout(() => {
        this._backoff = Math.min(this._backoff * 2, MAX_BACKOFF_MS);
        this.connect();
      }, this._backoff);
    };
  }

  /**
   * sendCommand(text)
   * Sends a command to the agent. Only dispatches if connection is open.
   * Returns true if sent, false if buffered/failed.
   */
  sendCommand(text) {
    if (!text?.trim()) return false;

    this._currentTaskName = text;

    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
      useSystemStore.getState().addLog('ERR', 'Agent link not ready. Command queued.', 'warn');
      return false;
    }

    this._ws.send(JSON.stringify({ type: 'command', text }));
    return true;
  }

  /**
   * sendInterrupt()
   * Signals the backend to halt the current mission.
   */
  sendInterrupt() {
    this._ws?.send(JSON.stringify({ type: 'interrupt' }));
    useSystemStore.getState().addLog('SYS', 'Interrupt signal sent. Halting mission.', 'warn');
  }

  destroy() {
    this._destroyed = true;
    clearTimeout(this._retryTimer);
    this._ws?.close();
  }
}


/* ════════════════════════════════════════════════════════════════
   SINGLETON INSTANCES
   One socket per connection — initialized once, reused app-wide.
   ════════════════════════════════════════════════════════════════ */
let _telemetrySocket = null;
let _agentSocket = null;

export function initializeSockets() {
  if (!_telemetrySocket) {
    _telemetrySocket = new TelemetrySocket();
    _telemetrySocket.connect();
  }
  if (!_agentSocket) {
    _agentSocket = new AgentSocket();
    _agentSocket.connect();
  }
}

export function destroySockets() {
  _telemetrySocket?.destroy();
  _agentSocket?.destroy();
  _telemetrySocket = null;
  _agentSocket = null;
}

export function sendCommand(text) {
  return _agentSocket?.sendCommand(text) ?? false;
}

export function sendInterrupt() {
  _agentSocket?.sendInterrupt();
}
