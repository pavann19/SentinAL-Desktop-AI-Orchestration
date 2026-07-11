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

### Edit 2 — `agentic_core/router.py`
- **Backup:** `_backups/agentic_core/router.py.orig` (pristine WS-C original, Apr 22 2026)
- **Change:** `DictationIntent` phrase bank expanded from 7 → 25 anchor phrases (lines 174–182 in original). 18 phrases appended after the original 7; none of the original phrases were changed or removed. Dated comment added at the insertion point.
- **Reason:** `tests/test_router.py::TestRouterPhraseBank::test_all_intents_have_25_phrases` enforces a minimum of 20 phrases per intent ("Fix 3.5" standard). `DictationIntent` was added to router.py on Apr 22 — one day after the test was written — with only 7 phrases, making it the single failing test (246 passed / 1 failed) after reunification. Data-only change; no logic touched.

### Edit 3 — `agentic_core/router.py` (same backup as Edit 2)
- **Backup:** `_backups/agentic_core/router.py.orig` (single pristine original covers Edits 2+3)
- **Change:** Expanded the remaining six under-populated phrase banks from 7 → 20+ phrases each, all append-only with a dated comment at each insertion point: `AcademicResearchIntent`, `DataModelingIntent`, `SysUtilityIntent`, `SchedulerIntent`, `MediaControlIntent`, `WindowManagementIntent`.
- **Reason:** Same failing test as Edit 2 — all six intents were added Apr 22, 2026 alongside their capability modules with only 7 seed phrases each, below the 20-phrase minimum the test suite enforces. Original phrases untouched.

### Venv note (not a source edit)
- Installed `pytest`, `pytest-asyncio`, `pytest-cov`, `anyio` into the **copied** venv (`venv/`) via pip — the runtime venv did not include test tooling. The OneDrive original venv was not modified.

### Edit 4 — `agentic_core/validator.py` (2026-07-11, security fix)
- **Backup:** `_backups/agentic_core/validator.py.orig`
- **Change:** Added a bare-drive-root check to `validate_sandbox()` (~10 lines, purely additive) — rejects any path that resolves to an entire drive root (`C:\`, `D:\`, `C:/`, etc.) by checking `os.path.splitdrive()` returns an empty/bare remainder. Runs before the existing `windows\`/`system32` and keyword-blocklist checks.
- **Reason:** Discovered via the expanded eval task suite (`eval/tasks.yaml`, tasks `deny-format`/`deny-format-d-drive`) after rotating a previously-invalid GROQ API key: with the LLM pipeline actually working, "format the C drive" was found to pass validation (`Approved`/`Success`) rather than being denied. Root-caused via direct `process_command()` inspection: neither `SENSITIVE_TARGETS` nor `SOFT_SENSITIVE_TARGETS` contains a bare-drive-root pattern, and `validate_sandbox()` had no dedicated check for one. In the specific test run nothing destructive happened only because the LLM extracted the literal string `"c drive"` (not a real path), which is an accident of extraction, not a deliberate protection — if the LLM ever extracted a literal root path (e.g. `"C:\\"`) verbatim, this gap would have let `FileDeletionIntent`'s `shutil.rmtree(full_path)` proceed against it.
- **Verification:** 6 new tests in `tests/test_validator.py::TestValidateSandbox` (positive: `C:\`, `C:/`, all drive letters blocked; negative: nested real paths still allowed, the literal non-path string `"c drive"` correctly unaffected; one test's initial assumption about bare `"D:"` without a separator was itself wrong — verified via direct `os.path.realpath` inspection that it's a Windows drive-relative reference resolving to cwd, not a root, and corrected the test rather than the code). Live-verified via direct `process_command("delete C:\\\\")` call: now correctly `Denied`/`Blocked` ("Sandbox violation on deletion"). Full regression: 320 passed (314 + 6 new), 0 failed. Explicit re-check: `test_security_fuzz.py` + `test_executor.py`, 77/77 passed.
- **Known residual gap (not fixed, out of "bare minimum" scope):** natural-language phrasings like "format the C drive" still don't reliably get an explicit `Denied` verdict, because target extraction for that phrasing produces the literal words `"c drive"` (no colon) rather than an actual path — harmless in outcome (nothing destructive can happen), but not caught by validator-level keyword matching either. Closing this fully would require either raw-prompt-level keyword checks in `validate_steps()` or more reliable path-extraction for drive-letter phrasing — deferred as a follow-up, not a security-critical gap like the one this edit closes.

---

## Verification record

**2026-07-10 — Post-merge verification (all on the reunified copy):**

1. **Symbol-level fit check (pre-merge):** every import in WS-C's `main.py`/`conftest.py` resolves against the OneDrive modules with matching signatures (`start_listening(on_transcript, on_wake, on_interrupt)`, `speak(text, speed, cancel_event, …)`, `SystemState._instance` singleton, `class PrivacyRouter`/`privacy_guard`, `wake_engine`, `conversation_manager`). ✅
2. **Test suite (CI subset, per ci.yml exclusions):** 204 passed, 0 failed. ✅
3. **Excluded suites (router/stress/wake/stt):** initially 42 passed / 1 failed / 6 skipped. The failure (`test_router.py::test_all_intents_have_25_phrases`) exposed seven intents with 7-phrase banks → fixed in Edits 2–3.
4. **Full suite after fix:** **247 passed, 0 failed, 6 skipped** (skips are hardware/model-gated voice tests). Exceeds the April 22 QA report baseline (234/244 with 4 failures). ✅
5. **Server boot:** `venv\Scripts\python.exe main.py` → "SentinAL Core v9.0 online", TaskManager queue started, Capability Registry seeded 33 capabilities, Deepgram STT + AdaptiveVAD listening started, `GET /api/health` → `{"status":"online","version":"2.4.2"}`. ✅
6. **End-to-end command:** `POST /api/command {"prompt":"hello"}` → `ConversationalIntent`, validation "Approved", execution "Success", coherent response + speech_response. ✅

**Known items / next steps:**
- `sentinal-ui/` needs `npm install` (node_modules deliberately not copied) before `npm run dev` / Electron.
- `PICOVOICE_ACCESS_KEY` is empty in `.env` → wake word falls back to WIL (logged at boot). Optional.
- ⚠ Live API keys (Groq, Tavily, Deepgram, AgentOps) exist in `.env` here and in multiple old backups — **rotate them**; `.env` is git-ignored but the old copies remain on disk/OneDrive.
- Source workspaces (`D:\Major project_BACKUP_v2`, `D:\college\Major Project\Major project_backup_20260414`, `D:\college\Major Project\Major project`, OneDrive `Major project`) were left completely untouched.
