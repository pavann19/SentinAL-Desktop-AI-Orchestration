# Local verification checkpoint — 2026-10-06

This is a local source-release checkpoint on Windows with Python 3.13.3.
It is not a production-readiness or newly observed GitHub CI result.

| Check | Result and boundary |
|---|---|
| Complete test suite | 1,430 passed; 7 skipped; 95 warnings; 86.87% scoped coverage |
| Python lint | Runtime and release helpers passed Ruff 0.16.0 |
| Type checking | Nine orchestration/security/privacy modules passed; imported modules and the rest of the application are not fully checked |
| Clean installation | `.[dev]` installed in a separate virtual environment; `pip check` passed |
| Dependency audit | Zero known vulnerabilities across 171 installed third-party packages; local SentinAL source excluded from PyPI lookup |
| Python packaging | Source distribution and wheel built; entrypoint and voice module present; no private runtime resources |
| Browser HUD | Clean npm install, ESLint with zero warnings, Vite build and moderate-severity npm audit passed; zero reported vulnerabilities |
| Authorization regressions | 25 adversarial tests passed, including actual orchestration/replanning and streaming paths |
| Offline evaluation | `conv-hello`, `deny-format`, `deny-format-d-drive`: 3/3 passed with cached embedding weights |
| Live transport | Shared-command and WebSocket integration tests passed, including real streaming replan escalation regressions |
| Reproducible evaluation | Exhaustive artifact-free router evaluation and source-only classifier training completed; [scores and interpretation](benchmarks/accuracy.md) |
| Source hygiene | Local Markdown targets/anchors, all four external documentation links, ignore controls and common secret patterns passed |
| Docker | Unverified: local Docker daemon unavailable; blocking CI build/import check configured |
| Desktop/voice/installer | Full live OS benchmark, microphone lifecycle, real containment execution and Electron installer not rerun |

Transport integration tests do not exercise microphone/background startup. Skipped
tests include optional real embedding comparison, microphone access, wake-engine
interfaces and the explicitly manual live roundtrip. Warnings include unclosed
SQLite resources in tests and dependency deprecations. Vite reports a nonblocking
bundle-size advisory (about 731 kB uncompressed JavaScript).

The dependency audit reads every installed version, including transitive and dev
packages, without resolving/installing a second environment. It excludes only
this local application, which has no corresponding PyPI release. No vulnerability
IDs are suppressed. The audit does not prove the absence of unknown vulnerabilities.

The current-source scan and an 827-blob scan across local Git refs found no common
API-key/private-key pattern matches. Older published blobs contain personal machine
paths; none remain in the current source tree. This is a limited pattern scan,
not an exhaustive secret-detection guarantee. Git history was not rewritten.

Raw logs, package outputs, generated models and removed materials were archived
outside the repository. Results depend on their stated scope and resolved versions;
future changes require a fresh verification run.
