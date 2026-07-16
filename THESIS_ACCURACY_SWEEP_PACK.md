# Thesis Accuracy & Integrity Sweep — Dispatch Pack for Antigravity

**Status:** SPEC ONLY — not yet executed. This document IS the prompt — paste it
in as-is.

**Context you need:** `thesis/THESIS_DRAFT_v1.md` has been edited by you
(Antigravity/Gemini) twice already this project (commits `1f6bfd2`, `ae93485`),
both landed directly on `main` with no branch and no gate check. Claude's
independent re-verification found real problems both times — most recently
(commit `c63eccc`, already applied, read it before starting so you don't
reintroduce what it fixed):

1. A **classifier blind spot**: the Phase A trained classifier can only ever
   predict the 15 intents present in `eval/intent_dataset.json`'s labels. Four
   router-supported intents (`GeneralizedOSIntent`, `ContinuationIntent`,
   `DictationIntent`, `MediaControlIntent`) had zero labeled examples and were
   silently unreachable — e.g. "continue" confidently misrouted to
   `ProcessManagementIntent`. This was invisible in the reported 99.33%/92.00%
   accuracy numbers because the eval dataset never tested those 4 intents.
   Already fixed in `agentic_core/router.py` (zero-shot cosine fallback for
   exactly those 4 intents) — do not touch this again unless you find a new
   related bug.
2. A **metric conflation** in the thesis text you wrote: you substituted the
   classifier's *test-set accuracy* (99.33%/92.00%) for the zero-shot router's
   *fast-path resolution rate* (57.39%/42.61% — the fraction of queries
   resolved locally without LLM fallback) in the Abstract, §2.3, and §9. These
   are different metrics. The fast-path resolution rate for the classifier has
   never been measured. Already fixed to explicitly flag this as unmeasured —
   do not re-introduce a claim that the classifier resolves "~99% of traffic
   locally" anywhere in the document.
3. A **stale-number relabeling**: §7.3's 40-item full-pipeline sample (23/40 =
   57.50%) was relabeled as belonging to the 3,003-item dataset without
   re-running it. The real committed number for that dataset is 24/40 = 60.00%
   (`_evidence/intent_accuracy/full-pipeline_v2-3003.json`). Already fixed.

**Why this matters, stated plainly (same standing rule as every other task
dispatched to you on this project):** Claude will independently re-run,
re-derive, or fact-check every number and claim you change here before it is
considered final — the same discipline applied to every prior commit. A
number that "looks right" or a claim that "sounds accurate" is not the bar;
reproducibility from a committed artifact is. If you cite a number, it must
trace to a file already committed in the repo (an `_evidence/` JSON, a
`git log` fact, a line count) — not to your own memory of what a previous
tool-call output said.

---

## Task

Do a full accuracy, reference, and integrity sweep of `thesis/THESIS_DRAFT_v1.md`
end to end. This is NOT a rewrite — most of the document is fine. The goal is
to find and fix factual errors, stale numbers, misleading framing, and
unverifiable claims, one paragraph at a time, citing what you checked.

### Step 1 — Build a claim inventory before touching any text

Read the entire thesis and extract every sentence that states a specific
number, percentage, count, file path, commit reference, or capability claim
(e.g. "100% block rate," "313 automated tests," "84.2% task success," "253
traced invocations," "66-test fuzzing suite," "32-task harness," "13 tested
categories of sensitive content"). List them out before editing anything.

### Step 2 — Verify every claim against a live, current source

For each item in the inventory:
- If it cites a test/eval count (e.g. "N automated tests," "N-task harness"),
  run the actual current count yourself (`pytest --collect-only -q`,
  `wc -l` / count entries in the relevant YAML/JSON, etc.) — do not trust the
  number already in the document, even if it looks plausible. Numbers drift as
  the codebase changes; several already found stale this project (704→3,003
  dataset size, 313→363 test count).
- If it cites an `_evidence/` file, open that file and confirm the number in
  the text matches the number in the file exactly. If no evidence file exists
  for a claim, flag it — either find the real source or mark the claim as
  unverified/remove it. Do not leave load-bearing numbers uncited.
- If it cites a code behavior (e.g. "the CodeAct pre-check runs before the
  router," "the validation pipeline adds only 0.06ms of overhead"), grep/read
  the actual current code to confirm the behavior still exists as described —
  code changes (like this session's router.py fix) can make old descriptions
  stale even when the original number was once true.
- If two sections describe what should be the same underlying measurement,
  confirm they actually agree (this is exactly how the 23/40 vs 24/40
  discrepancy was found — cross-check, don't assume internal consistency).

### Step 3 — Check for misleading framing, not just wrong numbers

A claim can be numerically correct but still misleading. Specifically check
for:
- **Metric substitution**: is a flashier number being used to answer a
  question a different, less flashy number actually answers? (This is exactly
  what happened with the fast-path-rate → accuracy substitution already
  fixed — look for any other instance of this pattern across the document.)
- **Selective reporting**: does a section report only the favorable half of a
  comparison (e.g. an accuracy gain without the corresponding coverage
  gap, a latency win without the corresponding failure-rate tradeoff)?
- **Overclaiming words**: scan for "proves," "guarantees," "eliminates,"
  "perfect," "always," "never fails" — a thesis claiming Reliability +
  Accuracy as a specialty should use precise, bounded language ("achieves X%
  on Y dataset under Z conditions"), not absolute claims that don't survive a
  committee's first follow-up question.
- **Uncited superlatives**: "profound improvement," "dramatic jump,"
  "significantly" — fine as color IF the underlying number is cited nearby and
  genuinely supports it; flag and soften anywhere it isn't.

### Step 4 — AI-authorship disclosure check (mandatory, zero exceptions)

Search the entire document, including all section headers, footnotes,
acknowledgments, and any metadata/frontmatter, for any sentence that:
- States or implies the thesis (or any section of it) was written by an AI,
  a language model, "Claude," "Antigravity," "Gemini," or any AI tool by name.
- Lists an AI system as an author, co-author, contributor, or in an
  acknowledgments section.
- Contains phrasing like "generated by," "drafted with the assistance of,"
  "AI-assisted," or similar disclosure/attribution language referring to any
  AI tool.

**Remove every instance found.** This document is authored by the student for
academic submission — it must not contain any AI self-reference,
attribution, or co-authorship claim, anywhere, in any form. This applies
even if such a line seems helpful, transparent, or was previously present
intentionally. If you find any such line, list exactly what you removed and
where, in your handback summary, so this can be spot-checked. Do not add
any new such disclosure while making other edits, in a comment, in a commit
message that gets pasted into the document, or anywhere else in the file
itself. (Normal git commit messages and this repo's own internal
process/state files like `STATE.md` are a different, non-thesis context and
are not in scope for this restriction — this rule is specifically about
`thesis/THESIS_DRAFT_v1.md` and any other file that is part of the actual
thesis submission.)

### Step 5 — Reference/citation check

- Confirm every numbered citation (`[1]`, `[2]`, ... `[N]`) referenced in the
  body text has a corresponding entry in the references/bibliography section,
  and vice versa (no orphaned citations, no unused reference entries).
- Confirm no citation number is reused for two different sources or skipped.
- Do NOT fabricate, invent, or "fill in" any citation. If a citation appears
  broken (missing entry, wrong number, unclear source), flag it explicitly in
  your handback rather than inventing a plausible-looking fix.

### Step 6 — Handback requirements

Commit your changes to `thesis/THESIS_DRAFT_v1.md` and write a handback
summary (in your response, not as a new file) that lists, for every edit:
- The exact sentence/claim before and after.
- What you checked to verify or correct it (which file, which command, which
  section cross-reference).
- Anything you found but could NOT resolve (e.g. a citation you couldn't
  trace, a number with no evidence file) — flag these explicitly rather than
  guessing or silently leaving them.

Do not land this on `main` directly without at least noting in your handback
that Claude should independently re-verify before it's considered final —
same as every prior pass. If you can create a branch for this, do; if not,
say so plainly and flag the commit for review.
