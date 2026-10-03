# docs/ layout

The public documentation surface is intentionally small:

- `README.md` at the repo root is the recruiter-facing overview.
- `ROADMAP.md` and `CONTAINMENT_ARCHITECTURE.md` are the canonical design docs.
- `docs/DECISIONS.md` records current project state and evidence boundaries.

Generated reports, thesis drafts, handoff notes, and large evidence artifacts are not
published in this public tree. Regenerate measurement outputs with the scripts in
`eval/` and `scripts/`; they write to gitignored local output directories.
