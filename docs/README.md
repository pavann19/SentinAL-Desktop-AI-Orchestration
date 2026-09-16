# docs/ layout

Kept at the repo root (canonical, frequently cross-referenced): `README.md`,
`ROADMAP.md`, `CONTAINMENT_ARCHITECTURE.md`. Everything else is grouped here
by what it's for, not when it was written:

- **`planning/`** — forward-looking design docs kept in the public tree:
  `OPEN_ENDED_ROADMAP.md` (the A1–A8 capability-axis extension of
  `ROADMAP.md`). A handful of earlier internal planning drafts are kept
  locally only (gitignored) and are not part of this repo.
- **`reports/`** — point-in-time analysis and status snapshots kept in the
  public tree: `ENGINEERING_REVIEW.md`, the `SentinAL_*_Report.md` files,
  `OVERNIGHT_HANDOFF.md`. These describe the project as of the date in the
  file, not as it is now — check `ROADMAP.md` for current status. A few
  internal status-tracking docs are kept locally only (gitignored).
- **`dev-history/`** — this repo doesn't publish internal
  development-process artifacts; kept locally only (gitignored) if present.

Utility/one-off scripts that used to sit at the repo root (`capture_ui.py`,
`generate_ood_data.py`, `scan_mics.py`) now live in `scripts/`, alongside
`verify_s4_live_roundtrip.py`. None of them import project modules by path,
so the move is safe.

Reorganized 2026-09-11 for hygiene; file *contents* are unchanged, only
locations (`git mv`, history preserved). Code comments and older docs that
mention one of these files by its old bare filename were not rewritten — the
filename is still unique enough to `grep`/find under its new folder.
