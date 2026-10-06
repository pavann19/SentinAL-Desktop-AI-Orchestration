# Contributing

Models may propose actions; deterministic policy controls authority. A capability
must not widen its own tier, alter validation, or replace an OS observation with a
fabricated success result. State limitations explicitly.

## Development

Follow the Windows installation in [README](README.md), including `.[dev]`.
Use a virtual environment. The package metadata defines runtime dependencies;
`requirements.txt` mirrors it and is a range specification, not a lockfile.

```powershell
python -m pytest tests/test_<area>.py --no-cov --timeout=60
python -m pytest tests/ --timeout=60
python -m ruff check main.py agentic_core system_services config capabilities interfaces scripts/check_release.py --ignore E501,E402,BLE001,S110,S112
python -m mypy --explicit-package-bases --follow-imports=silent agentic_core/execution_authority.py agentic_core/capability_broker.py agentic_core/confirmation.py agentic_core/executor.py capabilities/system/api_wrapper.py config/capability_tiers.py agentic_core/validator.py agentic_core/memory_hook.py system_services/privacy_router.py --ignore-missing-imports
python scripts/check_release.py
python -m build
```

Behavior changes require tests that expose the previous failure. Preserve assertions,
negative cases, and failure reporting. Do not loosen gates to hide failures.
Security-kernel changes require a deliberate explanation and targeted regression tests.
Do not reload `config.settings` during tests; patch the existing objects instead.

For UI changes run `npm ci`, `npm run lint` and `npm run build` in `sentinal-ui/`.
For evaluation changes run the relevant harness and report mode/dataset/environment.
Full desktop benchmarks need a disposable supervised machine.

Keep runtime state, live configuration, secrets, model artifacts, generated reports,
private handoffs and academic drafts out of Git. Summarize useful findings in docs.
Never silently rewrite published history. [Security reporting](SECURITY.md).
