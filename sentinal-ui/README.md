# SentinAL desktop interface

React, Vite, Three.js and Zustand provide the desktop dashboard. Electron hosts the built interface and starts the Python backend and local Ollama service when needed.

## Development

Use Node.js 22.12+ and install the [Python backend](../README.md) separately. From this directory:

```powershell
npm ci
npm run dev
```

Vite serves the interface at `http://localhost:5173`. Backend API/WebSocket traffic requires the separately configured local backend. To launch the Electron shell with its service-startup behavior:

```powershell
npm run electron:dev
```

Launching Electron can start real desktop/voice services; use a supervised test environment.

## Checks

```powershell
npm run lint
npm test
npm run build
```

The Node tests verify backend path selection without launching Electron. The build checks the web bundle; it does not validate an installed Windows application or live audio. The current dashboard bundle produces a size warning; loading/performance optimization remains open.

## Packaging

`npm run electron:build` invokes the existing Windows packaging configuration. Development resolves the backend relative to the source tree; packaged startup resolves it from Electron resources. No personal checkout path is required. Existing application identifiers are retained for compatibility.

The resource list includes backend source, excluding `.env` and runtime `data/`. Users must provision Python, dependencies, credentials and model assets separately. A packaged installer is not established as self-contained or end-to-end verified by the web build. Never include local credentials or runtime databases in release resources.
