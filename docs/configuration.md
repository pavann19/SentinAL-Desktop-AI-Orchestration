# Local configuration

Copy `.env.example` to `.env` for live setup. Environment variables override provider
settings. Keep `SENTINAL_HOST=127.0.0.1`; the backend defaults to port 8000 and the
browser HUD to port 5173. Choose `LLM_PROVIDER=local` for Ollama-only routing or
configure cloud credentials deliberately. Voice providers require their own setup.

`SENTINAL_OFFLINE=1` disables cloud LLM usage and the voice demo path; local Ollama is
used when reachable, otherwise a deterministic mock. Model weights can still require
initial downloads. For a cached disconnected verification run, also set
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

`SENTINAL_API_TOKEN` supplies the REST/WebSocket token. If absent, startup generates
`.sentinal_token`. The browser HUD asks for it and stores it only in page memory.
Do not put it in a `VITE_*` variable. Only localhost/127.0.0.1 port 5173 browser
origins are accepted; arbitrary browser origins and packaged `file:` origins fail closed.

`SENTINAL_DATA_DIR` redirects runtime databases/logs/telemetry to a writable directory
outside the checkout. Otherwise development runs write ignored runtime directories.
Never package that directory or local `.env`. Learning, autonomous goals, semantic
memory and self-improvement flags are experimental and default off.

Guarded T2/T3 actions require one-time confirmation of the exact resolved action.
`SENTINAL_REQUIRE_CONFIRMATION=false` blocks guarded requests; it does not enable
an execution bypass. Changed targets, arguments and dynamic substitutions require
a new resolved request. Autonomous T2/T3 actions are denied.

## Electron packaging dependencies

The download helper uses a scoped `global-agent` 4.1.3 override to remove the
`roarr`/`sprintf-js` dependency chain affected by
[GHSA-hp3w-g68c-fv3c](https://github.com/advisories/GHSA-hp3w-g68c-fv3c).
The helper retains its `bootstrap()` interface. Review this override when
upgrading `@electron/get`; the Electron installer remains experimental.
