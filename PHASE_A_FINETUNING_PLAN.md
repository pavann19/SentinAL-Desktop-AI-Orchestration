# Phase A: Trained Classifier Replacement for the Zero-Shot Router

**Status:** SPEC ONLY — not implemented. Written at the end of Session 12 for a
fresh session to execute directly. Read `STATE.md` first for full context on
why this exists (the WebNav/InfoRetrieval experiment proved the zero-shot
router has hit its ceiling — see Session 11/12 entries).

**Goal:** replace the zero-shot cosine-similarity match in
`agentic_core/router.py` with a real, trained classifier — the one lever this
session's evidence says can move accuracy meaningfully past the demonstrated
~55–65% ceiling, without needing a GPU cluster or multi-day training.

**Zero new dependencies required** — `scikit-learn>=1.5.0` and
`sentence-transformers>=3.0.0` are already pinned in `requirements.txt`.

---

## Design decision, stated explicitly (so it isn't re-litigated mid-implementation)

**Approach: frozen embeddings + a trained classification head, NOT full
transformer fine-tuning.** Reasoning:
- The encoder (`all-MiniLM-L6-v2`) already has broad language understanding
  from web-scale pretraining. Fine-tuning the WHOLE transformer on only 3,003
  examples risks overfitting/catastrophic forgetting and is slower, harder to
  debug, and higher-risk on a single laptop.
- A "linear probe on frozen embeddings" (encode once, train a small classifier
  on top) is standard, fast (seconds to minutes on CPU), low-risk, and
  produces calibrated softmax probabilities directly usable by the existing
  tie-break/dead-zone logic in `agentic_core/processor.py` — no changes
  needed there.
- If this approach doesn't hit a reasonable accuracy target (see Step 6), a
  documented escalation path to full encoder fine-tuning exists as
  "Phase A-extended" — do not attempt it first.

---

## Step 0 — Data preparation (must happen before any training)

**0a. Stratified train/val/test split of `eval/intent_dataset.json` (3,003 items).**
- Split ratio: 70/15/15, stratified by `expected_intent` (preserve per-class
  proportions in every split — use `sklearn.model_selection.train_test_split`
  with `stratify=`).
- **Fixed random seed, recorded in the output.** Every split must be
  reproducible — write the exact indices used to
  `_evidence/finetuning/split_indices.json` so this can be re-run identically.
- Include ALL 15 classes, including `CodeActIntent` — the classifier should
  still learn to recognize it even though the live system currently bypasses
  the router entirely for CodeAct via `is_developer_task()` in
  `agentic_core/processor.py` (that pre-check stays exactly as-is; this is
  about what the classifier itself can do, not changing the bypass).

**0b. Build a genuinely held-out out-of-distribution (OOD) test set.**
- This is the step that directly answers the generalization concern raised
  this session: does the classifier work on phrasings that don't share the
  same generation process as the training data?
- Target: 100–150 new items, spanning all 15 intents, authored in a
  DIFFERENTLY-SCOPED pass than the original 3,003 (different session, or
  dispatched to Antigravity as a fresh task with instructions to avoid the
  specific phrasing patterns already in `eval/intent_dataset.json` — read a
  sample of the existing file first specifically to identify and AVOID its
  stylistic patterns, rather than extend them).
- Save as `eval/intent_dataset_ood_test.json`, same schema as the main
  dataset. **Never used in training or hyperparameter tuning — touched
  exactly once, at final evaluation, per Step 6.**
- If time-constrained, a smaller OOD set (even 50 items) is still valuable
  and better than skipping this step — do not skip it to save time.

---

## Step 1 — Encode all splits with the frozen embedding model

```python
# eval/finetune_classifier.py (new file)
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")  # same model router.py already uses
train_embeddings = model.encode(train_prompts, show_progress_bar=True)
val_embeddings   = model.encode(val_prompts, show_progress_bar=True)
test_embeddings  = model.encode(test_prompts, show_progress_bar=True)
ood_embeddings   = model.encode(ood_prompts, show_progress_bar=True)
```
Cache all four arrays to disk (`.npy` files under `_evidence/finetuning/`) so
re-runs of Step 2 (classifier training/tuning) don't re-pay the encoding cost.

---

## Step 2 — Train the classification head

```python
from sklearn.linear_model import LogisticRegression

clf = LogisticRegression(max_iter=2000, multi_class="multinomial", C=1.0)
clf.fit(train_embeddings, train_labels)
```
- Start with default `C=1.0`. If val accuracy suggests over/underfitting,
  sweep `C` over `[0.1, 0.3, 1.0, 3.0, 10.0]` on the VAL split only — never
  touch train or test/OOD during this tuning.
- Save the fitted classifier: `joblib.dump(clf, "_evidence/finetuning/classifier_v1.joblib")`.
- **Escalation trigger** (only if this underperforms): if val accuracy is
  materially worse than expected (see Step 6 targets), the next thing to try
  is a small 2-layer MLP (`sklearn.neural_network.MLPClassifier` or a tiny
  PyTorch model) on the same frozen embeddings — still no full encoder
  fine-tuning yet. Full encoder fine-tuning is Phase A-extended, a separate,
  later escalation, not the default path.

---

## Step 3 — Evaluate honestly, in this exact order

1. **Train accuracy** — sanity check only, expect it near 100%; if it's much
   lower, something is broken (label encoding bug, etc.) — fix before
   proceeding.
2. **Val accuracy** — used only for the `C` sweep in Step 2. Report but don't
   headline this number (it's been used for tuning, so it's optimistic).
3. **Test accuracy** — touch this exactly once, after all tuning is finalized.
   **This is the primary in-distribution accuracy number for the thesis.**
4. **OOD accuracy** — the honest generalization number. **Report this
   explicitly next to test accuracy, not instead of it** — the gap between
   them (if any) is itself real, useful evidence for the thesis's Discussion
   chapter, not something to hide.

---

## Step 4 — Direct comparison against the existing zero-shot router

Run the SAME test split + OOD set through the current `router.route()`
zero-shot method (unchanged, for a true apples-to-apples baseline). Report:
- Zero-shot router accuracy on test split vs. classifier accuracy on test split.
- Zero-shot router accuracy on OOD set vs. classifier accuracy on OOD set.

---

## Step 5 — Integration (only after Step 3/4 numbers justify it)

Do NOT integrate before seeing real numbers. If the classifier genuinely
outperforms the zero-shot router on BOTH test and OOD accuracy:
- Add the classifier as an alternative path in `agentic_core/router.py`,
  loaded once at module init (like the embedding model already is).
- `route()`'s return contract stays the same shape (`intent`, `confidence`,
  `margin`, `is_ambiguous`) — `confidence` becomes the top softmax
  probability, `margin` becomes top1-minus-top2 softmax probability (same
  concept as the current cosine-similarity margin, just computed from the
  classifier's output instead). This means `agentic_core/processor.py`'s
  tie-break/dead-zone logic (Session 12) needs ZERO changes — it already
  consumes exactly this shape.
- Keep the `is_developer_task()` CodeAct pre-check exactly where it is,
  running before the classifier is ever consulted.
- Keep `_keyword_fallback()` as the last-resort path if the classifier/model
  fails to load, unchanged.

---

## Step 6 — Verification (same rigor as every other change this session)

- Full regression: `pytest tests/ -q` must stay green, same baseline as
  whatever `STATE.md` reports at the time this is executed.
- New independent tests for the classifier integration (mirror
  `tests/test_router.py`'s existing structure: reachability, no-crash on
  edge cases, margin/is_ambiguous keys present).
- Live E2E verification: run at least one real query through
  `capabilities/system/api_wrapper.py::process_command()` end-to-end and
  confirm the new classifier path is actually being hit (not silently
  falling back to the old zero-shot path).
- Explicit security re-check: `tests/test_security_fuzz.py`.
- **Report honestly, whatever the numbers are.** If the classifier does NOT
  outperform the zero-shot router (possible — 3,003 examples on a 15-way
  problem with some structural noise already found, like the
  SysUtility/MediaControl labeling issue), do not force the integration
  (Step 5) — report the negative result and stop at Step 4's comparison. That
  is still a genuine, useful, honest finding for the thesis.

**No specific accuracy target is promised here** — Session 12's honest
estimate was 80–90% on in-distribution test data, materially lower is
possible on the OOD set, and both numbers should be reported exactly as
measured, not adjusted to match this estimate.
