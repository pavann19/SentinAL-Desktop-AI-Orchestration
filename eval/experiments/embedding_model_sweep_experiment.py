"""
eval/experiments/embedding_model_sweep_experiment.py

EXPERIMENT, follow-up to real_data_balanced_experiment.py.

Two changes bundled together, both isolated from production:

1. VOLUME-EQUALIZED real data: the class-weighted experiment regressed
   InformationRetrievalIntent (100%->83%) and SchedulerIntent (100%->80%) on
   the synthetic test set. Root cause found: those two intents got 3,334 and
   2,987 real training examples respectively, vs 1,291/266/92 for the other
   three augmented intents - class_weight balances loss contribution across
   ALL 19 classes, but doesn't stop a class's decision boundary being
   reshaped by sheer example diversity when it gets 10-30x more data than
   its augmented siblings. Fix tried here: cap every augmented intent's real
   training data at the SAME ceiling (the smallest augmented intent's count,
   MediaStreamingIntent's ~1,291), not each intent's own synthetic count.

2. EMBEDDING MODEL SWEEP: the whole pipeline runs on frozen
   all-MiniLM-L6-v2 (22M params) embeddings + a linear head. Before reaching
   for anything more invasive (fine-tuning, ensembling), try swapping in a
   stronger frozen embedding model - same architecture, same training code,
   one parameter changed. Candidates: BAAI/bge-small-en-v1.5 (33M, similar
   speed to MiniLM, stronger MTEB) and all-mpnet-base-v2 (110M, slower,
   generally the strongest sentence-transformers model).

Writes only under _evidence/experiments/. Nothing in production touched.
Downloads route through D: (HF_HOME set below), not C:, per instruction.
"""
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf_cache")
os.environ.setdefault("HF_DATASETS_CACHE", "D:/hf_cache/datasets")

import joblib
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

ROOT = Path(__file__).resolve().parents[2]

PROD_DATASET = ROOT / "eval" / "intent_dataset.json"
PROD_SPLIT_INDICES = ROOT / "_evidence" / "finetuning" / "split_indices.json"
PROD_CLASSIFIER = ROOT / "_evidence" / "finetuning" / "classifier_v1.joblib"

REAL_DATASET = ROOT / "eval" / "real_world_massive_ood.json"

EXP_EVIDENCE_DIR = ROOT / "_evidence" / "experiments"
EXP_SPLIT_INDICES = EXP_EVIDENCE_DIR / "real_data_split_indices.json"  # from prior script

SWEEP_DIR = EXP_EVIDENCE_DIR / "embedding_sweep"
SWEEP_DIR.mkdir(parents=True, exist_ok=True)
REPORT = SWEEP_DIR / "embedding_sweep_report.json"

MODELS = [
    ("all-MiniLM-L6-v2", "sentence-transformers/all-MiniLM-L6-v2"),   # current production model
    ("bge-small-en-v1.5", "BAAI/bge-small-en-v1.5"),
    ("mpnet-base-v2", "sentence-transformers/all-mpnet-base-v2"),
]


def per_intent(labels, preds):
    d = defaultdict(lambda: [0, 0])
    for t, p in zip(labels, preds):
        d[t][1] += 1
        if t == p:
            d[t][0] += 1
    return {k: {"correct": v[0], "total": v[1], "acc": v[0] / v[1]} for k, v in d.items()}


def main():
    random.seed(31)

    prod_data = json.load(open(PROD_DATASET, encoding="utf-8"))
    prod_split = json.load(open(PROD_SPLIT_INDICES, encoding="utf-8"))
    prod_clf = joblib.load(PROD_CLASSIFIER)

    prod_train = [prod_data[i] for i in prod_split["train"]]
    prod_test = [prod_data[i] for i in prod_split["test"]]
    prod_test_labels = [d["expected_intent"] for d in prod_test]
    prod_test_prompts = [d["prompt"] for d in prod_test]

    real_data = json.load(open(REAL_DATASET, encoding="utf-8"))
    exp_split = json.load(open(EXP_SPLIT_INDICES, encoding="utf-8"))
    real_train = [real_data[i] for i in exp_split["train"]]
    real_test = [real_data[i] for i in exp_split["test"]]
    real_test_labels = [d["expected_intent"] for d in real_test]
    real_test_prompts = [d["prompt"] for d in real_test]

    # ── Volume-equalized real data: cap every augmented intent at the SAME ceiling ──
    # Fix: originally used min(counts) as the ceiling, expecting it to land near
    # MediaStreamingIntent's ~1,291. It didn't - ConversationalIntent's real count
    # (92, after the earlier general_quirky exclusion) was the true minimum, which
    # crushed all five intents down to 92 examples each (460 total real data) and
    # produced WORSE real-world accuracy than the uncapped class-weighted run this
    # was meant to improve on. A fixed ceiling avoids that: intents below it (like
    # ConversationalIntent) just keep their full count, intents above it (like
    # InformationRetrievalIntent's 3,334) get capped, without everyone being
    # dragged down to whichever intent happens to have the least real data.
    CEILING = 1000
    by_intent = defaultdict(list)
    for d in real_train:
        by_intent[d["expected_intent"]].append(d)
    ceiling = CEILING
    equalized_real = []
    for intent, items in by_intent.items():
        equalized_real.extend(items if len(items) <= ceiling else random.sample(items, ceiling))
    print(f"Volume-equalized real data: ceiling={ceiling}, counts -> "
          f"{ {k: min(len(v), ceiling) for k, v in by_intent.items()} }")

    combined_train = prod_train + equalized_real
    combined_labels = [d["expected_intent"] for d in combined_train]
    combined_prompts = [d["prompt"] for d in combined_train]
    print(f"Combined training set: {len(prod_train)} synthetic + {len(equalized_real)} real (equalized) = {len(combined_train)}")

    report = {"note": "EXPERIMENT ONLY. Production artifacts unmodified.", "ceiling": ceiling, "models": {}}

    for short_name, hf_name in MODELS:
        print(f"\n=== {short_name} ({hf_name}) ===")
        model_dir = SWEEP_DIR / short_name
        model_dir.mkdir(exist_ok=True)

        model = SentenceTransformer(hf_name, device="cpu", cache_folder="D:/hf_cache")

        train_emb = model.encode(combined_prompts, show_progress_bar=False, batch_size=64)
        prod_test_emb = model.encode(prod_test_prompts, show_progress_bar=False, batch_size=64)
        real_test_emb = model.encode(real_test_prompts, show_progress_bar=False, batch_size=64)
        np.save(model_dir / "train_emb.npy", train_emb)
        np.save(model_dir / "prod_test_emb.npy", prod_test_emb)
        np.save(model_dir / "real_test_emb.npy", real_test_emb)

        clf = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
        clf.fit(train_emb, combined_labels)
        joblib.dump(clf, model_dir / "classifier.joblib")

        prod_preds = clf.predict(prod_test_emb)
        real_preds = clf.predict(real_test_emb)

        synth_acc = accuracy_score(prod_test_labels, prod_preds)
        real_acc = accuracy_score(real_test_labels, real_preds)
        print(f"synthetic_test_acc={synth_acc:.4f}  real_world_test_acc={real_acc:.4f}")

        report["models"][short_name] = {
            "hf_name": hf_name,
            "embedding_dim": model.get_sentence_embedding_dimension(),
            "synthetic_test_acc": synth_acc,
            "real_world_test_acc": real_acc,
            "synthetic_per_intent": per_intent(prod_test_labels, prod_preds),
            "real_world_per_intent": per_intent(real_test_labels, real_preds),
        }

    # Production baseline for reference (MiniLM embeddings it was actually trained/tested with)
    prod_minilm_test_emb = np.load(ROOT / "_evidence" / "finetuning" / "test_emb.npy")
    prod_real_test_emb = np.load(EXP_EVIDENCE_DIR / "real_test_emb.npy")
    report["production_baseline"] = {
        "synthetic_test_acc": accuracy_score(prod_test_labels, prod_clf.predict(prod_minilm_test_emb)),
        "real_world_test_acc": accuracy_score(real_test_labels, prod_clf.predict(prod_real_test_emb)),
    }

    json.dump(report, open(REPORT, "w", encoding="utf-8"), indent=2)

    print("\n=== SUMMARY ===")
    print(f'{"variant":<22}{"synthetic":<12}{"real-world"}')
    b = report["production_baseline"]
    print(f'{"production":<22}{b["synthetic_test_acc"]:.4f}      {b["real_world_test_acc"]:.4f}')
    for short_name in report["models"]:
        m = report["models"][short_name]
        print(f'{short_name:<22}{m["synthetic_test_acc"]:.4f}      {m["real_world_test_acc"]:.4f}')

    print(f"\nReport written to {REPORT}")


if __name__ == "__main__":
    main()
