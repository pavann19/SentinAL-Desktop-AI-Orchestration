# SentinAL UI

Optional React interface for the loopback Python backend. Start the backend first.

```powershell
npm ci
npm run dev
```

Open http://localhost:5173 and enter the backend's `.sentinal_token` value.
The token is held in page memory and sent in a WebSocket authentication frame;
it is never placed in a URL, frontend environment variable or browser storage.
Reload to replace an invalid token. Do not expose the Vite server to the network.

```powershell
npm run lint
npm run build
```

Electron source is retained as experimental packaging work. Its packaged file-origin
UI is not an approved WebSocket origin; packaged installer operation is unverified.
The packaging manifest excludes local configuration and runtime data.
