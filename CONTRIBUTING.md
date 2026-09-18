# Contributing to SentinAL

Read this first, then [`docs/DECISIONS.md`](docs/DECISIONS.md) (why things are the way
they are, and where the project stands), then [`ROADMAP.md`](ROADMAP.md) (what is done
and what is next) and [`CONTAINMENT_ARCHITECTURE.md`](CONTAINMENT_ARCHITECTURE.md) (the
security design everything else is subordinate to).

## The one invariant

**The LLM is untrusted. Authority flows down, never up.** Models propose; deterministic
code (`agentic_core/validator.py`, the capability broker, budgets, the confirmation
channel) disposes. No model output may widen its own permissions, edit its own policy,
or promote its own risk tier. If a change lets that happen, it is wrong regardless of
how useful it is.

Corollary: **success is what the OS says, not what a call returned.** Every capability
that can be verified must be verified against real OS state after it runs
(`capabilities/system/postcondition_observer.py`).

## Quality bar (non-negotiable)

1. **Honest numbers only.** Every metric in a doc traces to a committed, re-runnable
   measurement. No retries that inflate a score, no cherry-picked runs, no rounding up.
   If a number is stale, fix or delete it. Say "not verified" when it is not.
2. **Tests with the change.** A behavior change ships with a test that fails without it.
   Run the targeted test files for what you touched; run the full suite before a
   release-level change, not after every edit.
3. **Lint clean at the pinned version.** `ruff==0.16.0` (pinned in `pyproject.toml` and CI).
   Fix findings; do not widen the CI ignore list to make a red build green.
4. **New behavior is opt-in.** Anything that acts more autonomously or changes routing
   ships behind a `SENTINAL_*` flag, default **off**, and is only flipped after it has
   been lived with and measured.
5. **Fail closed.** Broad `except Exception` in this codebase is a deliberate
   fail-safe (see the comment in `.github/workflows/ci.yml`); it must log or return a
   safe default, never swallow silently.
6. **No fabricated success.** A capability that did not do the work must not say it did.

## Frozen files

These are the security-critical kernel. Do not edit them without an explicit, recorded
decision from the maintainer; verify they are untouched with `git diff --stat` after
every change:

- `agentic_core/validator.py`
- `agentic_core/executor.py`
- `benchmarks/tasks.py`
- `main.py` (only ever changed deliberately, e.g. adding a documented route)

## Environment

- Windows 10/11, Python 3.11+. **Always use the project virtualenv**
  (`venv\Scripts\python.exe`), never a global interpreter — the global site-packages can
  carry incompatible `huggingface-hub`/`sentence-transformers` versions that silently
  degrade the router to keyword-only fallback and make results irreproducible.
- `scikit-learn` is pinned to the version the committed classifier was pickled under.
- No API keys are needed to run or test: `SENTINAL_OFFLINE=1 python scripts/offline_repl.py`.

## Everyday commands

```bash
venv\Scripts\python.exe -m pytest tests/test_<area>.py -q --no-cov     # targeted
venv\Scripts\python.exe -m pytest tests/ --deselect tests/test_stress.py   # full
venv\Scripts\python.exe -m ruff check agentic_core/ system_services/ config/ capabilities/ interfaces/ --ignore E501,E402,BLE001,S110,S112
python scripts/reproduce_router_accuracy.py       # router accuracy, no keys, no network
python -m eval.run_eval                            # task-success harness
```

Tests that patch `config.settings.BrainConfig...` must not `importlib.reload` that
module — reloading creates a new class object and silently breaks every other test's
patch. Use `monkeypatch.setattr` on the already-imported module instead.

## Workflow

1. Read the relevant `ROADMAP.md` section and `docs/DECISIONS.md`.
2. Build the smallest coherent increment. Do not add speculative features.
3. Test (targeted), lint, confirm frozen files untouched.
4. Commit with an honest, specific message: what changed, why, what was measured, what
   is still open. One logical change per commit.
5. Update `ROADMAP.md` in a separate commit citing the hash of the change it records.
6. Never push or rewrite published history without the maintainer's explicit go-ahead.

## Definition of done for an increment

Code + tests green, ruff clean, frozen files untouched, `ROADMAP.md` updated with the
commit hash and any honest caveats, any new env flag documented in `.env.example` and
listed in `docs/DECISIONS.md`, and — if it changes a published number — the number
re-measured and every doc that quotes it updated.
