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

`SENTINAL_REQUIRE_CONFIRMATION` defaults to true. Guarded T2/T3 actions return a
one-time token for an explicit second request. Setting false enables unsafe legacy
compatibility behavior and changes benchmark semantics; do not use it for normal operation.
