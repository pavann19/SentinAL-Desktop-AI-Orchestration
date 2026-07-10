# SentinAL v9 Reunification — Merge Log

**Date started:** 2026-07-10
**Performed by:** Claude Code (forensic investigation + reunification session)
**Goal:** Reunite the two halves of the April 22, 2026 "SentinAL v9.0 / MEGHA" project:
- **BODY** = `C:\Users\Gannoju Pavan\OneDrive\Desktop\Major project` (voice stack, capabilities, config, tests, UI, venv)
- **BRAIN** = `D:\college\Major Project\Major project` (agentic_core, main.py, pytest/CI infra)

**Policy for this merge:**
1. Source folders are READ-ONLY — nothing in OneDrive or the three D:\ workspaces was modified.
2. Every file operation is recorded in this log (what, from where, why).
3. Any subsequent EDIT to any file requires: (a) pristine copy saved under `_backups/` mirroring the path, named `<file>.orig`, (b) an entry in the "Edits" section below with the exact change, (c) a git commit.
4. Git history provides step-by-step revertibility.

---

## Phase 1 — Body copied from OneDrive (`C:\Users\Gannoju Pavan\OneDrive\Desktop\Major project`)

| Item | Destination | Reason |
|---|---|---|
| `capabilities/` (16 skill modules: system/, developer/, web/) | `capabilities/` | Real capability layer WS-C lost; referenced by agentic_core + CI |
| `config/` (settings.py BrainConfig, constants.py, paths.py, prompts.py) | `config/` | Real config package (Apr 21–22, 2026). Replaces WS-C's July 10 stub versions, which were NOT copied |
| `interfaces/` (voice: stt 35KB, tts 8KB, wake_engine, wake_intelligence, nlp_correction; ui_bridge: conversation_manager) | `interfaces/` | Real voice pipeline. Replaces WS-C's no-op stubs (NOT copied) |
| `system_services/` (privacy_router.py 7.7KB, system_state.py) | `system_services/` | Real PrivacyRouter + SystemState singleton that conftest.py/main.py import. Replaces WS-C stubs (NOT copied) |
| `tests/` (21 pytest files incl. test_security_fuzz, test_pipeline_integration, test_stress) | `tests/` | The v9.0 QA test suite; absent from all three D:\ workspaces |
| `data/` (capabilities.db, sentinal_memory.db, models/kokoro-v1.0.onnx 318MB, voices-v1.0.bin 27MB) | `data/` | Runtime DBs + Kokoro TTS models |
| `memory/` (capabilities.db, megha_path_cache.db, sentinal_memory.db) | `memory/` | Secondary DB location referenced by config/paths |
| `images/`, `telemetry/` | same | Assets / referenced dirs |
| `sentinal-ui/` (src/, electron/, public/, package.json Apr 22, vite/eslint configs) | `sentinal-ui/` | Newest Electron-enabled UI. **Excluded:** `node_modules/`, `dist/`, `build/`, `release/`, `.vite/` — rebuildable via `npm install` / `npm run build`; the MEGHAv1 installer remains in OneDrive |
| `CODEBASE_ANALYSIS.md`, `ENGINEERING_REVIEW.md` (July 2, 2026) | root | Prior analysis documents; provenance |
| `venv/` (Python 3.13.3, full: torch, faster-whisper, kokoro-onnx, langchain, fastapi…) | `venv/` | Working interpreter environment. Relocated venv works because `pyvenv.cfg` points to the still-existing base Python at `C:\Users\Gannoju Pavan\AppData\Local\Programs\Python\Python313` |

**Deliberately NOT copied from OneDrive:** `phase_0/` (2.1GB historical snapshot), `archive/` (1.8GB legacy UIs + whisper model cache), `htmlcov/` (stale coverage output), `PDFS/` (documentation exports), `logs/` (old runtime logs; fresh empty `logs/` created instead), `__pycache__/`, `directory_name/` (empty junk). All remain untouched in OneDrive.

## Phase 2 — Brain copied from WS-C (`D:\college\Major Project\Major project`)

| Item | Destination | Reason |
|---|---|---|
| `agentic_core/` (processor, router, executor 45KB, validator, scheduler, capability_registry, memory_hook, telemetry) | `agentic_core/` | The v9.0 brain; exists ONLY in WS-C. Marked "✗ missing" by OneDrive's own CODEBASE_ANALYSIS.md |
| `main.py` (33KB FastAPI server, Apr 22 18:48) | `main.py` | The v9.0 entry point; exists only in WS-C |
| `conftest.py`, `pytest.ini`, `.coveragerc` | root | Test infrastructure matching the OneDrive `tests/` suite |
| `.github/workflows/ci.yml` | `.github/` | 6-job CI pipeline written for exactly this merged layout |
| `requirements.txt` (pinned, "Fix 2.1") | root | OneDrive workspace has no root requirements.txt |
| `.env`, `.env.example` | root | Newest env config (Deepgram/Picovoice/AgentOps era). ⚠ Contains live keys — rotation recommended |
| `scan_mics.py`, `capture_ui.py` | root | Utility scripts |
| `SentinAL_Full_QA_Report.md`, `SentinAL_Health_Report.md`, `SentinAL_System_Report.md` | root | v9.0 QA evidence (Apr 22, 2026) |
| `.gitignore` | root | Base ignore file (extended in Phase 3 — see Edits) |

**Deliberately NOT copied from WS-C:**
- `config/`, `interfaces/`, `system_services/` — these were **no-op stub files created 2026-07-10 13:34–13:37** (verified by mtime + content) to work around the missing OneDrive half. Superseded by the real OneDrive modules.
- `start_sentinal.ps1`, `boot_sentinal.bat` — stale launchers referencing non-existent paths (`server.py`, `jarvis-ui-new`, `archive\ui_legacy`).
- `data/`, `logs/`, `sentinal-ui/` — OneDrive versions kept (identical or newer). WS-C's `sentinal-ui` lacked the `electron/` folder and had the older package.json.
- `archive/` (deprecated kernel + QA experiment scripts), `venv-less` boot leftovers, `agentops.log`, `.coverage` (stale binary), `megha_path_cache.db` (WS-C root copy; `memory/` has one).

## Conflict resolutions (files present in both halves)

| File | Chosen | Rejected | Basis |
|---|---|---|---|
| `config/*` | OneDrive (Apr 21–22, real code) | WS-C (Jul 10 stubs) | Stubs are no-ops with wrong class names |
| `interfaces/*`, `system_services/*` | OneDrive (real) | WS-C (stubs) | Same |
| `sentinal-ui/package.json` | OneDrive (Apr 22 15:56, 1929B, Electron scripts) | WS-C (769B) | Newer, Electron-enabled |
| `SentinAL_Health_Report.md` | WS-C (10,662B) | OneDrive/phase_0 (10,477B) | WS-C copy is the later revision |
| root DBs | OneDrive `data/` + `memory/` | WS-C `data/` | Same era; OneDrive set is the one co-located with the models |

---

## Edits (every line-level change to any file after the copy)

> Format: file, backup path, reason, exact change. NO ENTRY = file is byte-identical to its source half.

*(entries appended below as they happen)*

### Edit 1 — `.gitignore`
- **Backup:** `_backups/.gitignore.orig` (pristine WS-C original, 6 lines)
- **Change:** Appended 11 ignore rules under a dated comment: `node_modules/`, `data/models/` (345MB TTS models), `data/capabilities.db`, `memory/*.db`, `.coverage`, `htmlcov/`, `sentinal-ui/{dist,build,release}/`, `_backups/`.
- **Reason:** Keep large binaries, runtime DBs, and build output out of git. No original line was modified or removed — pure append.

---

## Verification record

*(appended as verification proceeds)*
