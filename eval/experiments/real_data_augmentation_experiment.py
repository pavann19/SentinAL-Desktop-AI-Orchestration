"""
eval/experiments/real_data_augmentation_experiment.py

EXPERIMENT — reads production artifacts, writes only under
_evidence/experiments/ and eval/experiments/. Never touches:
  - eval/intent_dataset.json
  - eval/intent_dataset_ood_test.json
  - _evidence/finetuning/classifier_v1.joblib
  - _evidence/finetuning/split_indices.json
  - README.md

Question this answers: does augmenting the production training set with
real-world data (eval/real_world_massive_ood.json, sourced from Amazon
MASSIVE, mapped to the 5 SentinAL intents it actually covers) produce a
classifier that generalizes better to real phrasing, without wrecking
accuracy on the existing synthetic benchmark?

Everything is evaluated on TWO held-out test sets, kept separate:
  - the production synthetic test split (unchanged, from split_indices.json)
  - a fresh real-world test split carved out of real_world_massive_ood.json

The production classifier is also scored against the real-world test split,
so the comparison is apples-to-apples: same test sets, two classifiers.
"""
import json
import random
from pathlib import Path

import joblib
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]

# ── Production artifacts (read-only) ──────────────────────────────────────
PROD_DATASET = ROOT / "eval" / "intent_dataset.json"
PROD_SPLIT_INDICES = ROOT / "_evidence" / "finetuning" / "split_indices.json"
PROD_CLASSIFIER = ROOT / "_evidence" / "finetuning" / "classifier_v1.joblib"
PROD_TEST_EMB = ROOT / "_evidence" / "finetuning" / "test_emb.npy"

# ── Real-world data (read-only input) ──────────────────────────────────────
REAL_DATASET = ROOT / "eval" / "real_world_massive_ood.json"

# ── Experiment outputs (all new, isolated) ─────────────────────────────────
EXP_EVIDENCE_DIR = ROOT / "_evidence" / "experiments"
EXP_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
EXP_CLASSIFIER = EXP_EVIDENCE_DIR / "classifier_real_augmented.joblib"
EXP_SPLIT_INDICES = EXP_EVIDENCE_DIR / "real_data_split_indices.json"
EXP_REPORT = EXP_EVIDENCE_DIR / "real_data_augmentation_report.json"


def get_embeddings(model, texts, cache_path):
    cache_path = Path(cache_path)
    if cache_path.exists():
        cached = np.load(cache_path)
        if cached.shape[0] == len(texts):
            return cached
    emb = model.encode(texts, show_progress_bar=False, batch_size=64)
    np.save(cache_path, emb)
    return emb


def main():
    print("Loading production artifacts (read-only)...")
    prod_data = json.load(open(PROD_DATASET, encoding="utf-8"))
    prod_split = json.load(open(PROD_SPLIT_INDICES, encoding="utf-8"))
    prod_clf = joblib.load(PROD_CLASSIFIER)
    prod_test_emb = np.load(PROD_TEST_EMB)

    prod_train = [prod_data[i] for i in prod_split["train"]]
    prod_test = [prod_data[i] for i in prod_split["test"]]
    prod_test_labels = [d["expected_intent"] for d in prod_test]

    print(f"Production train: {len(prod_train)}, production test: {len(prod_test)}")

    print("\nLoading real-world dataset...")
    real_data = json.load(open(REAL_DATASET, encoding="utf-8"))
    real_labels_all = [d["expected_intent"] for d in real_data]

    # Stratified 70/15/15 split of the real data, same convention as production,
    # but a SEPARATE split file/seed so this never collides with prod indices.
    indices = list(range(len(real_data)))
    train_idx, temp_idx, _, temp_labels = train_test_split(
        indices, real_labels_all, test_size=0.30, stratify=real_labels_all, random_state=99
    )
    val_idx, test_idx = train_test_split(
        temp_idx, test_size=0.50, stratify=temp_labels, random_state=99
    )
    json.dump(
        {"train": train_idx, "val": val_idx, "test": test_idx},
        open(EXP_SPLIT_INDICES, "w", encoding="utf-8"), indent=2,
    )

    real_train = [real_data[i] for i in train_idx]
    real_test = [real_data[i] for i in test_idx]
    real_test_labels = [d["expected_intent"] for d in real_test]

    print(f"Real train: {len(real_train)}, real val: {len(val_idx)}, real test: {len(real_test)}")

    print("\nLoading embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

    real_test_emb = get_embeddings(
        model, [d["prompt"] for d in real_test], EXP_EVIDENCE_DIR / "real_test_emb.npy"
    )

    # ── Baseline: how does the UNCHANGED production classifier do on real data? ──
    print("\n--- Scoring PRODUCTION classifier (unmodified) ---")
    prod_on_prod_test = accuracy_score(prod_test_labels, prod_clf.predict(prod_test_emb))
    prod_on_real_test = accuracy_score(real_test_labels, prod_clf.predict(real_test_emb))
    print(f"Production classifier | synthetic test: {prod_on_prod_test:.4f}")
    print(f"Production classifier | real-world test: {prod_on_real_test:.4f}")

    # ── Experiment: train a NEW classifier on production train + real train ──
    print("\n--- Training EXPERIMENTAL classifier (production train + real train) ---")
    combined_train = prod_train + real_train
    combined_labels = [d["expected_intent"] for d in combined_train]
    combined_emb = get_embeddings(
        model, [d["prompt"] for d in combined_train], EXP_EVIDENCE_DIR / "combined_train_emb.npy"
    )

    exp_clf = LogisticRegression(max_iter=2000, C=1.0)
    exp_clf.fit(combined_emb, combined_labels)
    joblib.dump(exp_clf, EXP_CLASSIFIER)

    exp_on_prod_test = accuracy_score(prod_test_labels, exp_clf.predict(prod_test_emb))
    exp_on_real_test = accuracy_score(real_test_labels, exp_clf.predict(real_test_emb))
    print(f"Experimental classifier | synthetic test: {exp_on_prod_test:.4f}")
    print(f"Experimental classifier | real-world test: {exp_on_real_test:.4f}")

    # Per-intent breakdown on the real test set, both classifiers
    def per_intent(labels, preds):
        from collections import defaultdict
        d = defaultdict(lambda: [0, 0])
        for t, p in zip(labels, preds):
            d[t][1] += 1
            if t == p:
                d[t][0] += 1
        return {k: {"correct": v[0], "total": v[1], "acc": v[0] / v[1]} for k, v in d.items()}

    report = {
        "note": "EXPERIMENT ONLY. Production artifacts unmodified. See docstring.",
        "production_classifier": {
            "synthetic_test_acc": prod_on_prod_test,
            "real_world_test_acc": prod_on_real_test,
            "real_world_per_intent": per_intent(real_test_labels, prod_clf.predict(real_test_emb)),
        },
        "experimental_classifier": {
            "trained_on": f"{len(prod_train)} synthetic + {len(real_train)} real = {len(combined_train)} total",
            "synthetic_test_acc": exp_on_prod_test,
            "real_world_test_acc": exp_on_real_test,
            "real_world_per_intent": per_intent(real_test_labels, exp_clf.predict(real_test_emb)),
        },
    }
    json.dump(report, open(EXP_REPORT, "w", encoding="utf-8"), indent=2)
    print(f"\nReport written to {EXP_REPORT}")


if __name__ == "__main__":
    main()
