// ═══════════════════════════════════════════════════════════════
//  SENTINAL OS — Electron Main Process
//  Wraps the existing Vite + React frontend as a native desktop app.
//  Dev mode:  loads http://localhost:5173
//  Prod mode: loads the built dist/ folder
// ═══════════════════════════════════════════════════════════════

const { app, BrowserWindow, ipcMain, session } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

// ── Configuration ────────────────────────────────────────────────
const IS_DEV = !app.isPackaged;
const DEV_URL = 'http://localhost:5173';
const PROD_INDEX = path.join(__dirname, '..', 'dist', 'index.html');
const BOOT_INDEX = path.join(__dirname, 'boot.html');

let mainWindow = null;
let backendProcess = null;
let ollamaProcess = null;

/**
 * Robust path resolution for background services. 
 * Handles differences between Dev (source) and Prod (installed asar).
 */
function resolveBackendPath() {
    const rootPath = path.join(__dirname, '..', '..'); // Root of source in Dev
    
    // Check if we are running from a packaged installation
    if (app.isPackaged) {
        return {
            // Priority 1: User's absolute dev path (for convenience on this machine)
            devRoot: 'c:/Users/Gannoju Pavan/OneDrive/Desktop/Major project',
            // Priority 2: Installed resources folder
            prodRoot: process.resourcesPath
        };
    }
    return { devRoot: rootPath, prodRoot: rootPath };
}

async function ensureServices(window) {
    const updateStatus = (msg, pct) => {
        window.webContents.send('status-update', { message: msg, progress: pct });
        window.webContents.executeJavaScript(`window.postMessage({ type: 'status', message: '${msg}', progress: ${pct} }, '*')`);
    };

    const paths = resolveBackendPath();
    const fs = require('fs');

    try {
        // 1. Check/Start Ollama
        updateStatus("Initializing Neural Core...", 10);
        const ollamaRunning = await checkPort(11434);
        if (!ollamaRunning) {
            updateStatus("Starting Ollama Service...", 20);
            ollamaProcess = spawn('ollama', ['serve'], { 
                detached: false, 
                windowsHide: true,
                shell: true 
            });
            await delay(3000); // Give it a head start
        }

        // 2. Resolve Python & Server Paths
        updateStatus("Locating Neural Engine...", 35);
        
        let pythonPath = 'python'; // Default to global python
        let serverPath = path.join(paths.devRoot, 'main.py');
        let workingDir = paths.devRoot;

        // Logic: Try Venv in devRoot -> Fallback to global python
        const venvPath = path.join(paths.devRoot, 'venv', 'Scripts', 'python.exe');
        if (fs.existsSync(venvPath)) {
            pythonPath = venvPath;
        } else {
            console.debug("[SRE] Venv not found. Using global python as fallback.");
        }

        // Verify Server exists or search in production resources
        if (!fs.existsSync(serverPath)) {
            const prodServer = path.join(paths.prodRoot, 'main.py');
            if (fs.existsSync(prodServer)) {
                serverPath = prodServer;
                workingDir = paths.prodRoot;
            } else {
                console.error("[SRE] CRITICAL: main.py not found at:", serverPath);
                // Last ditch: check if devRoot was incorrectly resolved
            }
        }

        updateStatus("Starting SentinAL Backend...", 45);
        backendProcess = spawn(pythonPath, [serverPath], {
            detached: false,
            windowsHide: true,
            cwd: workingDir
        });

        // 3. Health Check Loop
        updateStatus("Verifying Neural Link...", 60);
        let ready = false;
        let retries = 0;
        const maxRetries = 30;

        while (!ready && retries < maxRetries) {
            ready = await checkHealth();
            if (!ready) {
                retries++;
                updateStatus(`Waiting for Services (${retries}/${maxRetries})...`, 60 + (retries / maxRetries) * 30);
                await delay(1000);
            }
        }

        if (ready) {
            updateStatus("System Ready. Launching UI...", 100);
            await delay(1000);
            if (IS_DEV) {
                mainWindow.loadURL(DEV_URL);
            } else {
                mainWindow.loadFile(PROD_INDEX);
            }
        } else {
            throw new Error("Backend services failed to go online.");
        }

    } catch (err) {
        console.error("Boot sequence failed:", err);
        window.webContents.executeJavaScript(`window.postMessage({ error: true, message: 'System Error' }, '*')`);
    }
}

function checkPort(port) {
    return new Promise((resolve) => {
        const client = require('net').createConnection({ port }, () => {
            client.end();
            resolve(true);
        });
        client.on('error', () => resolve(false));
    });
}

function checkHealth() {
    return new Promise((resolve) => {
        const req = http.get('http://127.0.0.1:8000/health', (res) => {
            resolve(res.statusCode === 200);
        });
        req.on('error', () => resolve(false));
        req.setTimeout(500, () => {
            req.destroy();
            resolve(false);
        });
    });
}

function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1920,
    height: 1080,
    minWidth: 1280,
    minHeight: 720,
    frame: false,
    fullscreen: true,
    backgroundColor: '#020202',
    show: false,
    icon: path.join(__dirname, '..', 'public', 'favicon.svg'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // ── Load Boot Screen First ────────────────────────────────────
  mainWindow.loadFile(BOOT_INDEX);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    mainWindow.focus();
    ensureServices(mainWindow);
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // ── Keyboard Shortcuts ────────────────────────────────────────
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F11' && input.type === 'keyDown') {
      mainWindow.setFullScreen(!mainWindow.isFullScreen());
      event.preventDefault();
    }
    if (input.key === 'Escape' && input.type === 'keyDown' && mainWindow.isFullScreen()) {
      mainWindow.setFullScreen(false);
      event.preventDefault();
    }
  });
}

// ── App Lifecycle ───────────────────────────────────────────────
app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowed = ['media', 'microphone', 'audioCapture'];
    if (allowed.includes(permission)) {
      callback(true);
    } else {
      callback(false);
    }
  });

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// ── Cleanup Process on Exit ─────────────────────────────────────
app.on('before-quit', () => {
    if (backendProcess) {
        console.debug("Terminating Backend Process...");
        backendProcess.kill();
    }
    // We optionally keep Ollama alive as it's often a shared service
});

// ── IPC Handlers ────────────────────────────────────────────────
ipcMain.handle('window:minimize', () => mainWindow?.minimize());
ipcMain.handle('window:maximize', () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow?.maximize();
  }
});
ipcMain.handle('window:close', () => mainWindow?.close());
ipcMain.handle('window:toggleFullscreen', () => {
  mainWindow?.setFullScreen(!mainWindow?.isFullScreen());
});
ipcMain.handle('window:isFullscreen', () => mainWindow?.isFullScreen());

ipcMain.handle('system:platform', () => process.platform);
ipcMain.handle('system:version', () => app.getVersion());
ipcMain.handle('system:boot-retry', () => {
    if (mainWindow) {
        ensureServices(mainWindow);
    }
});
