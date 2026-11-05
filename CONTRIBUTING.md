# Development

Use Python 3.11 for parity with Windows CI and Node.js 22.12+ for the frontend. Follow the [setup instructions](README.md), then install development tools:

```powershell
python -m pip install -e ".[dev]"
```

`requirements.txt` is the runtime dependency source for both direct installation and Python package metadata. `requirements-eval.txt` is the smaller headless router-evaluation environment. Do not copy runtime dependency lists into `pyproject.toml`.

## Safe test setup

Use an owned temporary data directory before importing runtime modules. Do not run tests against personal documents, an existing runtime database or a live desktop session. Starting `main.py`, the Electron shell or the voice pipeline can initiate real host interactions.

```powershell
$env:SENTINAL_DATA_DIR = Join-Path $env:TEMP "sentinal-development-tests"
$env:LLM_PROVIDER = "local"
$env:GROQ_API_KEY = ""
$env:DEEPGRAM_API_KEY = ""
$env:TAVILY_API_KEY = ""
python scripts/check_repository.py
python -m unittest discover -s tests -p test_ci_gate.py
python -m ruff check agentic_core/ system_services/ config/ capabilities/ interfaces/ --ignore E501,E402,BLE001,S110,S112
python -m mypy agentic_core/validator.py agentic_core/memory_hook.py system_services/privacy_router.py --ignore-missing-imports
```

## CI contract

The workflow runs repository integrity, Python static analysis, Windows regression with coverage, security regression, stress/concurrency, pipeline integration and frontend checks. The final gate requires every prerequisite to finish with `success`; skipped, cancelled and failed jobs cannot satisfy it.

The regression job retains the existing **70% coverage minimum** over `agentic_core`, `system_services`, `config`, `capabilities` and `interfaces`. It uploads coverage and JUnit reports. The historical measured 86.75% is not the configured threshold.

```powershell
python -m pytest tests/ --ignore=tests/test_stress.py --ignore=tests/test_router.py --ignore=tests/test_stt_service.py --ignore=tests/test_wake_intelligence.py --ignore=tests/test_tts_service.py --cov-fail-under=70
python -m pytest tests/test_security_fuzz.py --no-cov
python -m pytest tests/test_stress.py --timeout=60 --no-cov
python -m pytest tests/test_pipeline_integration.py tests/test_api_wrapper.py --no-cov
```

The existing selection excludes the model-dependent router suite and three voice suites from hosted regression; those require separate model/audio provisioning. Stress tests run separately. Security and integration jobs overlap with the regression selection, so their counts must not be added to claim distinct tests. Hosted checks do not establish microphone quality, installed-app behavior or an unattended desktop session.

Frontend checks, from `sentinal-ui/`:

```powershell
npm ci
npm run lint
npm test
npm run build
```

For CI without launching Electron or downloading its executable, set `ELECTRON_SKIP_BINARY_DOWNLOAD=1` before `npm ci`.

## Change review

Keep changes focused and attach the checks relevant to the affected boundary. Authorization and execution changes need adversarial tests for the forbidden effect, not just response text. Keep historical measurements immutable and give fresh reports unique run identifiers. Do not commit `.env`, bearer tokens, runtime databases, generated model artifacts or personal logs. Preserve the thesis entry point at `thesis/Thesis.md`.
