"""
eval/experiments/real_data_balanced_experiment.py

EXPERIMENT, follow-up to real_data_augmentation_experiment.py.

The naive concat experiment (production train + ALL real train, no rebalancing)
fixed real-world accuracy for the 5 augmented intents but broke 14 UNAUGMENTED
intents by up to 55pp — pure class imbalance (7,970 real examples for 5
intents vs ~100-160 synthetic examples per intent for the other 14 swamped
the decision boundary). This script tries two fixes for that, both still
fully isolated from production:

  A. DOWNSAMPLED  - cap real-data-per-intent at 3x that intent's existing
                     synthetic training count, so no intent can outnumber
                     the others by more than the same ratio already present
                     in the synthetic set.
  B. CLASS-WEIGHTED - keep the full naive-concat training set, but fit
                     LogisticRegression with class_weight='balanced' so the
                     loss itself compensates for the count imbalance instead
                     of throwing away real data.

Same read-only production artifacts, same held-out test sets (production
synthetic test + the real-world test carved out by the previous script),
so all four classifiers (production, naive-concat, downsampled,
class-weighted) are compared on identical data.

Writes only under _evidence/experiments/. Nothing in production touched.
"""
import json
import random
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

ROOT = Path(__file__).resolve().parents[2]

PROD_DATASET = ROOT / "eval" / "intent_dataset.json"
PROD_SPLIT_INDICES = ROOT / "_evidence" / "finetuning" / "split_indices.json"
PROD_CLASSIFIER = ROOT / "_evidence" / "finetuning" / "classifier_v1.joblib"
PROD_TEST_EMB = ROOT / "_evidence" / "finetuning" / "test_emb.npy"

REAL_DATASET = ROOT / "eval" / "real_world_massive_ood.json"

EXP_EVIDENCE_DIR = ROOT / "_evidence" / "experiments"
EXP_SPLIT_INDICES = EXP_EVIDENCE_DIR / "real_data_split_indices.json"  # from prior script
REAL_TEST_EMB = EXP_EVIDENCE_DIR / "real_test_emb.npy"                  # from prior script
COMBINED_TRAIN_EMB = EXP_EVIDENCE_DIR / "combined_train_emb.npy"        # from prior script (naive)
NAIVE_CLASSIFIER = EXP_EVIDENCE_DIR / "classifier_real_augmented.joblib"

DOWNSAMPLED_CLASSIFIER = EXP_EVIDENCE_DIR / "classifier_real_downsampled.joblib"
BALANCED_CLASSIFIER = EXP_EVIDENCE_DIR / "classifier_real_classweighted.joblib"
REPORT = EXP_EVIDENCE_DIR / "real_data_balanced_report.json"

DOWNSAMPLE_RATIO = 3  # cap real examples per augmented intent at 3x its synthetic train count


def get_embeddings(model, texts, cache_path):
    cache_path = Path(cache_path)
    if cache_path.exists():
        cached = np.load(cache_path)
        if cached.shape[0] == len(texts):
            return cached
    emb = model.encode(texts, show_progress_bar=False, batch_size=64)
    np.save(cache_path, emb)
    return emb


def per_intent(labels, preds):
    d = defaultdict(lambda: [0, 0])
    for t, p in zip(labels, preds):
        d[t][1] += 1
        if t == p:
            d[t][0] += 1
    return {k: {"correct": v[0], "total": v[1], "acc": v[0] / v[1]} for k, v in d.items()}


def main():
    random.seed(21)

    prod_data = json.load(open(PROD_DATASET, encoding="utf-8"))
    prod_split = json.load(open(PROD_SPLIT_INDICES, encoding="utf-8"))
    prod_clf = joblib.load(PROD_CLASSIFIER)
    prod_test_emb = np.load(PROD_TEST_EMB)

    prod_train = [prod_data[i] for i in prod_split["train"]]
    prod_test = [prod_data[i] for i in prod_split["test"]]
    prod_test_labels = [d["expected_intent"] for d in prod_test]

    from collections import Counter
    prod_train_counts = Counter(d["expected_intent"] for d in prod_train)

    real_data = json.load(open(REAL_DATASET, encoding="utf-8"))
    exp_split = json.load(open(EXP_SPLIT_INDICES, encoding="utf-8"))
    real_train = [real_data[i] for i in exp_split["train"]]
    real_test = [real_data[i] for i in exp_split["test"]]
    real_test_labels = [d["expected_intent"] for d in real_test]

    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    real_test_emb = get_embeddings(model, [d["prompt"] for d in real_test], REAL_TEST_EMB)
    naive_train_emb = get_embeddings(
        model, [d["prompt"] for d in prod_train + real_train], COMBINED_TRAIN_EMB
    )
    naive_clf = joblib.load(NAIVE_CLASSIFIER)

    results = {
        "production": {
            "synthetic_test_acc": accuracy_score(prod_test_labels, prod_clf.predict(prod_test_emb)),
            "real_world_test_acc": accuracy_score(real_test_labels, prod_clf.predict(real_test_emb)),
        },
        "naive_concat": {
            "synthetic_test_acc": accuracy_score(prod_test_labels, naive_clf.predict(prod_test_emb)),
            "real_world_test_acc": accuracy_score(real_test_labels, naive_clf.predict(real_test_emb)),
        },
    }

    # ── Variant A: downsampled real data ────────────────────────────────────
    print("--- Variant A: downsampled real data (cap 3x synthetic count per intent) ---")
    by_intent = defaultdict(list)
    for d in real_train:
        by_intent[d["expected_intent"]].append(d)

    downsampled_real = []
    for intent, items in by_intent.items():
        cap = prod_train_counts.get(intent, 50) * DOWNSAMPLE_RATIO
        downsampled_real.extend(items if len(items) <= cap else random.sample(items, cap))

    print(f"Real data: {len(real_train)} -> {len(downsampled_real)} after downsampling")
    downsampled_train = prod_train + downsampled_real
    downsampled_train_emb = get_embeddings(
        model, [d["prompt"] for d in downsampled_train],
        EXP_EVIDENCE_DIR / "downsampled_train_emb.npy",
    )
    downsampled_labels = [d["expected_intent"] for d in downsampled_train]
    downsampled_clf = LogisticRegression(max_iter=2000, C=1.0)
    downsampled_clf.fit(downsampled_train_emb, downsampled_labels)
    joblib.dump(downsampled_clf, DOWNSAMPLED_CLASSIFIER)

    results["downsampled"] = {
        "trained_on": f"{len(prod_train)} synthetic + {len(downsampled_real)} real (capped) = {len(downsampled_train)} total",
        "synthetic_test_acc": accuracy_score(prod_test_labels, downsampled_clf.predict(prod_test_emb)),
        "real_world_test_acc": accuracy_score(real_test_labels, downsampled_clf.predict(real_test_emb)),
    }

    # ── Variant B: class_weight='balanced' on the FULL naive-concat set ───────
    print("--- Variant B: class_weight='balanced' on full concat ---")
    balanced_clf = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
    naive_labels = [d["expected_intent"] for d in prod_train + real_train]
    balanced_clf.fit(naive_train_emb, naive_labels)
    joblib.dump(balanced_clf, BALANCED_CLASSIFIER)

    results["class_weighted"] = {
        "trained_on": f"{len(prod_train)} synthetic + {len(real_train)} real (full, class_weight=balanced) = {len(prod_train) + len(real_train)} total",
        "synthetic_test_acc": accuracy_score(prod_test_labels, balanced_clf.predict(prod_test_emb)),
        "real_world_test_acc": accuracy_score(real_test_labels, balanced_clf.predict(real_test_emb)),
    }

    # ── Per-intent synthetic-test breakdown for all 4, to see collateral damage ──
    print("\n=== Synthetic test, per intent, all variants ===")
    variants = {
        "production": prod_clf, "naive_concat": naive_clf,
        "downsampled": downsampled_clf, "class_weighted": balanced_clf,
    }
    per_intent_all = {name: per_intent(prod_test_labels, clf.predict(prod_test_emb)) for name, clf in variants.items()}

    header = f'{"Intent":<28}' + "".join(f'{name:<16}' for name in variants)
    print(header)
    all_intents = sorted(per_intent_all["production"].keys())
    for intent in all_intents:
        row = f'{intent:<28}'
        for name in variants:
            v = per_intent_all[name].get(intent, {"acc": 0})
            row += f'{v["acc"]:.0%}'.ljust(16)
        print(row)

    print("\n=== Real-world test, overall ===")
    for name, r in results.items():
        print(f'{name:<18} synthetic={r["synthetic_test_acc"]:.4f}  real={r["real_world_test_acc"]:.4f}')

    full_report = {
        "note": "EXPERIMENT ONLY. Production artifacts unmodified.",
        "summary": results,
        "synthetic_test_per_intent_all_variants": per_intent_all,
    }
    json.dump(full_report, open(REPORT, "w", encoding="utf-8"), indent=2)
    print(f"\nReport written to {REPORT}")


if __name__ == "__main__":
    main()
