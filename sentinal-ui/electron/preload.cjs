// ═══════════════════════════════════════════════════════════════
//  SENTINAL OS — Electron Preload Script
//  Secure bridge between the renderer (React) and main process.
//  Exposes only safe, whitelisted APIs via contextBridge.
// ═══════════════════════════════════════════════════════════════

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // ── Window Controls ───────────────────────────────────────────
  minimize: () => ipcRenderer.invoke('window:minimize'),
  maximize: () => ipcRenderer.invoke('window:maximize'),
  close: () => ipcRenderer.invoke('window:close'),
  toggleFullscreen: () => ipcRenderer.invoke('window:toggleFullscreen'),
  isFullscreen: () => ipcRenderer.invoke('window:isFullscreen'),

  // ── System Info ───────────────────────────────────────────────
  getPlatform: () => ipcRenderer.invoke('system:platform'),
  getVersion: () => ipcRenderer.invoke('system:version'),

  // ── IPC Event Bridge ──────────────────────────────────────────
  // Allows the React app to listen for events from the main process
  on: (channel, callback) => {
    const validChannels = ['system:update', 'window:state-change'];
    if (validChannels.includes(channel)) {
      ipcRenderer.on(channel, (event, ...args) => callback(...args));
    }
  },
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  },

  // ── Runtime Detection ─────────────────────────────────────────
  isElectron: true,
  retryBoot: () => ipcRenderer.invoke('system:boot-retry'),
});
