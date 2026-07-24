import argparse
import json
import os
import random
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sentence_transformers import SentenceTransformer
import joblib

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATASET_PATH = ROOT / "eval" / "intent_dataset.json"
OOD_DATASET_PATH = ROOT / "eval" / "intent_dataset_ood_test.json"
EVIDENCE_DIR = ROOT / "_evidence" / "finetuning"
CLASSIFIER_PATH = EVIDENCE_DIR / "classifier_v1.joblib"
SPLIT_INDICES_PATH = EVIDENCE_DIR / "split_indices.json"
REPORTS_DIR = ROOT / "_evidence" / "intent_accuracy"

# Ensure evidence dir exists
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def _dataset_hash(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

def load_data():
    with open(DATASET_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    with open(OOD_DATASET_PATH, 'r', encoding='utf-8') as f:
        ood_data = json.load(f)
        
    return data, ood_data

def prepare_splits(data):
    # Step 0a: 70/15/15 stratified split
    indices = list(range(len(data)))
    labels = [d['expected_intent'] for d in data]
    
    # Train = 70%, Temp = 30%
    train_idx, temp_idx, train_labels, temp_labels = train_test_split(
        indices, labels, test_size=0.30, stratify=labels, random_state=42
    )
    
    # Val = 15%, Test = 15% (half of 30%)
    val_idx, test_idx = train_test_split(
        temp_idx, test_size=0.50, stratify=temp_labels, random_state=42
    )
    
    # Save split indices
    split_indices = {
        "train": train_idx,
        "val": val_idx,
        "test": test_idx
    }
    with open(SPLIT_INDICES_PATH, 'w', encoding='utf-8') as f:
        json.dump(split_indices, f, indent=4)
        
    return train_idx, val_idx, test_idx

def get_embeddings(texts, cache_path):
    if cache_path.exists():
        print(f"Loading cached embeddings from {cache_path}")
        return np.load(cache_path)
    
    print(f"Encoding {len(texts)} texts for {cache_path}...")
    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    embeddings = model.encode(texts, show_progress_bar=True)
    np.save(cache_path, embeddings)
    return embeddings

def per_intent_breakdown(true_labels, pred_labels):
    breakdown = {}
    for true, pred in zip(true_labels, pred_labels):
        if true not in breakdown:
            breakdown[true] = {"total": 0, "correct": 0}
        breakdown[true]["total"] += 1
        if true == pred:
            breakdown[true]["correct"] += 1
    
    for b in breakdown.values():
        b["accuracy"] = round(b["correct"] / b["total"], 4) if b["total"] else 0.0
    return breakdown

def calculate_margin(probs):
    top2 = np.partition(probs, -2)[-2:]
    return top2[1] - top2[0]

def calibrate_eps(clf, val_embeddings, val_labels):
    print("\n--- Margin Calibration on Val Split ---")
    val_probs = clf.predict_proba(val_embeddings)
    val_preds = clf.predict(val_embeddings)
    
    correct_margins = []
    incorrect_margins = []
    
    for i in range(len(val_labels)):
        margin = calculate_margin(val_probs[i])
        if val_preds[i] == val_labels[i]:
            correct_margins.append(margin)
        else:
            incorrect_margins.append(margin)
            
    med_correct = np.median(correct_margins) if correct_margins else 0.0
    med_incorrect = np.median(incorrect_margins) if incorrect_margins else 0.0
    
    print(f"Median margin for CORRECT predictions: {med_correct:.4f}")
    print(f"Median margin for INCORRECT predictions: {med_incorrect:.4f}")
    
    # Old eps was 0.05. Pick a new one based on the midpoint or something just above the 75th percentile of incorrect.
    # To keep things simple and data-driven:
    # A threshold halfway between median incorrect and median correct, or just covering most incorrects.
    if incorrect_margins:
        p75_incorrect = np.percentile(incorrect_margins, 75)
        new_eps = min(med_correct, p75_incorrect * 1.5) # ensure we don't clip too many correct ones
    else:
        new_eps = 0.05
        
    new_eps = round(float(new_eps), 4)
    print(f"Old EPS (Zero-shot): 0.0500")
    print(f"New Calibrated EPS: {new_eps:.4f}")
    
    return new_eps, 0.05

def evaluate_zero_shot(dataset_items):
    from agentic_core.router import router
    true_labels = []
    pred_labels = []
    for item in dataset_items:
        r = router.route(item["prompt"])
        true_labels.append(item["expected_intent"])
        pred_labels.append(r["intent"])
    return true_labels, pred_labels

def main():
    parser = argparse.ArgumentParser(description="Finetune classifier and compare with zero-shot")
    parser.add_argument("--run-id", required=True, help="Identifier for output json reports")
    args = parser.parse_args()

    data, ood_data = load_data()
    train_idx, val_idx, test_idx = prepare_splits(data)
    
    train_data = [data[i] for i in train_idx]
    val_data = [data[i] for i in val_idx]
    test_data = [data[i] for i in test_idx]
    
    print(f"Splits: Train {len(train_data)}, Val {len(val_data)}, Test {len(test_data)}, OOD {len(ood_data)}")
    
    # Embeddings
    train_emb = get_embeddings([d['prompt'] for d in train_data], EVIDENCE_DIR / "train_emb.npy")
    val_emb = get_embeddings([d['prompt'] for d in val_data], EVIDENCE_DIR / "val_emb.npy")
    test_emb = get_embeddings([d['prompt'] for d in test_data], EVIDENCE_DIR / "test_emb.npy")
    ood_emb = get_embeddings([d['prompt'] for d in ood_data], EVIDENCE_DIR / "ood_emb.npy")
    
    train_labels = [d['expected_intent'] for d in train_data]
    val_labels = [d['expected_intent'] for d in val_data]
    test_labels = [d['expected_intent'] for d in test_data]
    ood_labels = [d['expected_intent'] for d in ood_data]
    
    # Step 2: C sweep on Val
    best_c = 1.0
    best_val_acc = 0.0
    print("\n--- Sweeping C ---")
    for c in [0.1, 0.3, 1.0, 3.0, 10.0]:
        # NOTE: multinomial is the (and only) multiclass strategy in scikit-learn
        # >= 1.7, where the multi_class argument was removed. Passing it explicitly
        # breaks under 1.8.0 (TypeError). Omitting it preserves the exact same
        # behaviour that multi_class="multinomial" gave under the 1.5/1.6 line the
        # model was originally trained on.
        clf = LogisticRegression(max_iter=2000, C=c)
        clf.fit(train_emb, train_labels)
        preds = clf.predict(val_emb)
        acc = accuracy_score(val_labels, preds)
        print(f"C={c}: Val Acc = {acc:.4f}")
        if acc > best_val_acc:
            best_val_acc = acc
            best_c = c
            
    print(f"\nBest C: {best_c}")
    
    # Final train on best C (multi_class omitted — see sweep loop comment above)
    clf = LogisticRegression(max_iter=2000, C=best_c)
    clf.fit(train_emb, train_labels)
    joblib.dump(clf, CLASSIFIER_PATH)
    
    # Step 3: Calibrate EPS
    new_eps, old_eps = calibrate_eps(clf, val_emb, val_labels)
    
    # Evaluate Classifier
    train_preds = clf.predict(train_emb)
    val_preds = clf.predict(val_emb)
    test_preds = clf.predict(test_emb)
    ood_preds = clf.predict(ood_emb)
    
    clf_train_acc = accuracy_score(train_labels, train_preds)
    clf_val_acc = accuracy_score(val_labels, val_preds)
    clf_test_acc = accuracy_score(test_labels, test_preds)
    clf_ood_acc = accuracy_score(ood_labels, ood_preds)
    
    # Evaluate Zero-Shot
    zs_test_true, zs_test_preds = evaluate_zero_shot(test_data)
    zs_ood_true, zs_ood_preds = evaluate_zero_shot(ood_data)
    
    zs_test_acc = accuracy_score(zs_test_true, zs_test_preds)
    zs_ood_acc = accuracy_score(zs_ood_true, zs_ood_preds)
    
    print("\n--- Evaluation Summary ---")
    print(f"Classifier Train Acc: {clf_train_acc:.4f}")
    print(f"Classifier Val Acc:   {clf_val_acc:.4f}")
    print(f"Classifier Test Acc:  {clf_test_acc:.4f}")
    print(f"Classifier OOD Acc:   {clf_ood_acc:.4f}")
    print(f"Zero-Shot Test Acc:   {zs_test_acc:.4f}")
    print(f"Zero-Shot OOD Acc:    {zs_ood_acc:.4f}")
    
    # Save Report
    report = {
        "run_id": args.run_id,
        "dataset_path": str(DATASET_PATH),
        "dataset_sha256_16": _dataset_hash(DATASET_PATH),
        "ood_dataset_path": str(OOD_DATASET_PATH),
        "classifier_metrics": {
            "train_acc": clf_train_acc,
            "val_acc": clf_val_acc,
            "test_acc": clf_test_acc,
            "ood_acc": clf_ood_acc,
            "best_c": best_c,
            "new_eps": new_eps,
            "old_eps": old_eps,
            "test_per_intent": per_intent_breakdown(test_labels, test_preds),
            "ood_per_intent": per_intent_breakdown(ood_labels, ood_preds)
        },
        "zeroshot_metrics": {
            "test_acc": zs_test_acc,
            "ood_acc": zs_ood_acc,
            "test_per_intent": per_intent_breakdown(zs_test_true, zs_test_preds),
            "ood_per_intent": per_intent_breakdown(zs_ood_true, zs_ood_preds)
        }
    }
    
    out_path = REPORTS_DIR / f"finetune_report_{args.run_id}.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=4)
        
    print(f"\nReport written to {out_path}")

if __name__ == "__main__":
    main()
