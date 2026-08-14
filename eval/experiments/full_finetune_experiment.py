"""
eval/experiments/full_finetune_experiment.py

EXPERIMENT, follow-up to embedding_model_sweep_experiment.py.

Everything so far kept the embedding model FROZEN and only trained a linear
LogisticRegression head on top (~7,300 trainable params for MiniLM's 384-dim
output x 19 classes). This script actually fine-tunes the embedding model's
own weights (mean-pooled transformer + a joint linear classification head,
trained end-to-end with cross-entropy) against the same combined
synthetic + volume-equalized-real training set, to see whether adapting the
embedding space itself beats a frozen-embedding + linear-probe approach.

No LoRA/QLoRA: these models are 22M-110M params, three orders of magnitude
below where low-rank adapters earn their keep over full fine-tuning (see
prior turn's answer). Full fine-tuning is the correct-scale technique here.

CPU-only torch build in this environment (no CUDA). Runtime differs a lot
by model size - MiniLM (22M) first to get real numbers before deciding
whether bge-small/mpnet-base are worth the wait.

A held-out validation SLICE is carved out of the training pool itself (90/10)
for early stopping - this is separate from and never touches the final
prod_test / real_test evaluation sets, so comparison against every prior
experiment stays apples-to-apples.

Writes only under _evidence/experiments/finetuned/. Nothing in production
touched. HF cache stays on D:, not C:.
"""
import json
import os
import random
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf_cache")

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]

PROD_DATASET = ROOT / "eval" / "intent_dataset.json"
PROD_SPLIT_INDICES = ROOT / "_evidence" / "finetuning" / "split_indices.json"
REAL_DATASET = ROOT / "eval" / "real_world_massive_ood.json"
EXP_SPLIT_INDICES = ROOT / "_evidence" / "experiments" / "real_data_split_indices.json"

# Targeted fix for a regression the promotion test suite caught: "delete the file in
# downloads folder" misrouted to GeneralizedOSIntent (85% confident) instead of
# FileDeletionIntent. Diagnosed cause: production's FileDeletionIntent training data
# only covers "delete the FOLDER itself" ("delete backup folder"), never "delete a
# FILE located inside a folder" - GeneralizedOSIntent has plenty of generic
# folder-navigation examples, so that phrasing pattern-matched toward it by default.
# Additive only (like the real-world data) - does not touch eval/intent_dataset.json.
DISAMBIGUATION_DATASET = ROOT / "eval" / "experiments" / "file_deletion_boundary_fix.json"

OUT_DIR = ROOT / "_evidence" / "experiments" / "finetuned"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CEILING = 1000  # same volume-equalization as the winning candidate
DEVICE = torch.device("cpu")
MAX_LEN = 32
BATCH_SIZE = 16
LR = 2e-5
EPOCHS = 4
PATIENCE = 2  # early stop if val acc doesn't improve for this many epochs


def load_combined_data():
    prod_data = json.load(open(PROD_DATASET, encoding="utf-8"))
    prod_split = json.load(open(PROD_SPLIT_INDICES, encoding="utf-8"))
    prod_train = [prod_data[i] for i in prod_split["train"]]
    prod_test = [prod_data[i] for i in prod_split["test"]]

    real_data = json.load(open(REAL_DATASET, encoding="utf-8"))
    exp_split = json.load(open(EXP_SPLIT_INDICES, encoding="utf-8"))
    real_train = [real_data[i] for i in exp_split["train"]]
    real_test = [real_data[i] for i in exp_split["test"]]

    by_intent = defaultdict(list)
    for d in real_train:
        by_intent[d["expected_intent"]].append(d)
    equalized_real = []
    for intent, items in by_intent.items():
        equalized_real.extend(items if len(items) <= CEILING else random.sample(items, CEILING))

    disambiguation = json.load(open(DISAMBIGUATION_DATASET, encoding="utf-8")) if DISAMBIGUATION_DATASET.exists() else []

    combined = prod_train + equalized_real + disambiguation
    return combined, prod_test, real_test


def mean_pool(last_hidden_state, attention_mask):
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed = torch.sum(last_hidden_state * mask, dim=1)
    counts = torch.clamp(mask.sum(dim=1), min=1e-9)
    return summed / counts


class IntentDataset(Dataset):
    def __init__(self, items, label2id, tokenizer):
        self.items = items
        self.label2id = label2id
        self.tokenizer = tokenizer

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        item = self.items[idx]
        return item["prompt"], self.label2id[item["expected_intent"]]


def collate(batch, tokenizer):
    texts, labels = zip(*batch)
    enc = tokenizer(list(texts), padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt")
    return enc, torch.tensor(labels, dtype=torch.long)


class FineTunedClassifier(nn.Module):
    def __init__(self, base_model, hidden_size, n_classes):
        super().__init__()
        self.base = base_model
        self.head = nn.Linear(hidden_size, n_classes)

    def forward(self, input_ids, attention_mask):
        out = self.base(input_ids=input_ids, attention_mask=attention_mask)
        pooled = mean_pool(out.last_hidden_state, attention_mask)
        return self.head(pooled)


def evaluate(model, items, label2id, id2label, tokenizer, batch_size=32):
    model.eval()
    ds = IntentDataset(items, label2id, tokenizer)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=False, collate_fn=lambda b: collate(b, tokenizer))
    correct, total = 0, 0
    per_intent = defaultdict(lambda: [0, 0])
    with torch.no_grad():
        for enc, labels in dl:
            logits = model(enc["input_ids"], enc["attention_mask"])
            preds = logits.argmax(dim=-1)
            for p, t in zip(preds.tolist(), labels.tolist()):
                total += 1
                intent = id2label[t]
                per_intent[intent][1] += 1
                if p == t:
                    correct += 1
                    per_intent[intent][0] += 1
    acc = correct / total if total else 0.0
    per_intent_out = {k: {"correct": v[0], "total": v[1], "acc": v[0] / v[1]} for k, v in per_intent.items()}
    return acc, per_intent_out


def finetune_one(short_name, hf_name):
    print(f"\n{'='*70}\nFULL FINE-TUNE: {short_name} ({hf_name})\n{'='*70}")
    t_start = time.time()

    combined, prod_test, real_test = load_combined_data()

    all_labels = sorted({d["expected_intent"] for d in combined})
    label2id = {l: i for i, l in enumerate(all_labels)}
    id2label = {i: l for l, i in label2id.items()}

    random.seed(41)
    shuffled = combined[:]
    random.shuffle(shuffled)
    n_val = max(1, int(0.10 * len(shuffled)))
    val_items = shuffled[:n_val]
    train_items = shuffled[n_val:]
    print(f"Train: {len(train_items)}, internal val (early stop only): {len(val_items)}")

    tokenizer = AutoTokenizer.from_pretrained(hf_name, cache_dir="D:/hf_cache")
    base_model = AutoModel.from_pretrained(hf_name, cache_dir="D:/hf_cache")
    hidden_size = base_model.config.hidden_size

    model = FineTunedClassifier(base_model, hidden_size, len(all_labels)).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    loss_fn = nn.CrossEntropyLoss()

    train_ds = IntentDataset(train_items, label2id, tokenizer)
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, collate_fn=lambda b: collate(b, tokenizer))

    best_val_acc = -1.0
    best_state = None
    epochs_no_improve = 0

    for epoch in range(1, EPOCHS + 1):
        model.train()
        epoch_loss = 0.0
        t_epoch = time.time()
        for enc, labels in train_dl:
            optimizer.zero_grad()
            logits = model(enc["input_ids"], enc["attention_mask"])
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        val_acc, _ = evaluate(model, val_items, label2id, id2label, tokenizer)
        print(f"Epoch {epoch}: train_loss={epoch_loss/len(train_dl):.4f}  val_acc={val_acc:.4f}  ({time.time()-t_epoch:.1f}s)")

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= PATIENCE:
                print(f"Early stopping (no val improvement for {PATIENCE} epochs)")
                break

    model.load_state_dict(best_state)

    synth_acc, synth_per_intent = evaluate(model, prod_test, label2id, id2label, tokenizer)
    real_acc, real_per_intent = evaluate(model, real_test, label2id, id2label, tokenizer)

    elapsed = time.time() - t_start
    print(f"\n{short_name}: synthetic_test_acc={synth_acc:.4f}  real_world_test_acc={real_acc:.4f}  (total {elapsed/60:.1f} min)")

    out_dir = OUT_DIR / short_name
    out_dir.mkdir(exist_ok=True)
    torch.save(model.state_dict(), out_dir / "model_state.pt")
    json.dump({"label2id": label2id}, open(out_dir / "labels.json", "w"))

    return {
        "hf_name": hf_name,
        "synthetic_test_acc": synth_acc,
        "real_world_test_acc": real_acc,
        "internal_val_acc": best_val_acc,
        "elapsed_minutes": elapsed / 60,
        "synthetic_per_intent": synth_per_intent,
        "real_world_per_intent": real_per_intent,
    }


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "all-MiniLM-L6-v2"
    MODELS = {
        "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
        "bge-small-en-v1.5": "BAAI/bge-small-en-v1.5",
        "mpnet-base-v2": "sentence-transformers/all-mpnet-base-v2",
    }
    if target == "all":
        results = {}
        for short_name, hf_name in MODELS.items():
            results[short_name] = finetune_one(short_name, hf_name)
    else:
        results = {target: finetune_one(target, MODELS[target])}

    report_path = OUT_DIR / "full_finetune_report.json"
    existing = json.load(open(report_path)) if report_path.exists() else {}
    existing.update(results)
    json.dump(existing, open(report_path, "w", encoding="utf-8"), indent=2)
    print(f"\nReport updated at {report_path}")
