# docs/ layout

Kept at the repo root (canonical, frequently cross-referenced): `README.md`,
`ROADMAP.md`, `CONTAINMENT_ARCHITECTURE.md`. Everything else is grouped here
by what it's for, not when it was written:

- **`planning/`** — forward-looking design docs: the original
  `AGENTIC_OS_ROADMAP_AND_THESIS_PLAN.md`, `PHASE_TASK_BOARD.md`,
  `PHASE_A_FINETUNING_PLAN.md`, `SENTINAL_V2_RECONCILED_ARCHITECTURE.md`, and
  `OPEN_ENDED_ROADMAP.md` (the A1–A8 capability-axis extension of `ROADMAP.md`).
- **`reports/`** — point-in-time analysis and status snapshots:
  `CODEBASE_ANALYSIS.md`, `ENGINEERING_REVIEW.md`, the `SentinAL_*_Report.md`
  files, `THESIS_ACCURACY_SWEEP_PACK.md`, `STATE.md`, `OVERNIGHT_HANDOFF.md`.
  These describe the project as of the date in the file, not as it is now —
  check `ROADMAP.md` for current status.
- **`dev-history/`** — internal development-process artifacts:
  `MERGE_LOG.md`, `VERIFICATION_PROTOCOL.md`, and prior sessions' planning
  prompts. **Local-`main`-only** — none of this belongs on `public-release`;
  see the repo's standing rule on not disclosing AI-tool authorship.

Utility/one-off scripts that used to sit at the repo root (`capture_ui.py`,
`generate_ood_data.py`, `scan_mics.py`) now live in `scripts/`, alongside
`verify_s4_live_roundtrip.py`. None of them import project modules by path,
so the move is safe.

Reorganized 2026-09-11 for hygiene; file *contents* are unchanged, only
locations (`git mv`, history preserved). Code comments and older docs that
mention one of these files by its old bare filename were not rewritten — the
filename is still unique enough to `grep`/find under its new folder.
