"""
tests/test_intent_dataset_coverage.py

Guards eval/intent_dataset.json against the exact gap it had until this
session: GeneralizedOSIntent, ContinuationIntent, MediaControlIntent and
DictationIntent had ZERO labeled examples, meaning
eval/finetune_classifier.py's LogisticRegression could never predict them -
they were permanently unreachable through the trained classifier regardless
of how good the model was, since sklearn cannot output a class it never saw
in training data. agentic_core/router.py's own PHRASE_BANK comment near line
628 already documented this as a known gap; these tests make it a build-time
failure instead of a comment someone has to remember to read.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from config.constants import ALLOWLIST_INTENTS

DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "eval", "intent_dataset.json")
OOD_DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "eval", "intent_dataset_ood_test.json")

# UnknownIntent is deliberately not a labeled training target - it's the
# router's fallback for utterances that don't match any real intent, so a
# dataset of "examples of UnknownIntent" would be incoherent by definition.
TRAINABLE_INTENTS = ALLOWLIST_INTENTS - {"UnknownIntent"}

# Below this, a stratified 70/15/15 split leaves too few examples per split
# for the val/test slices to mean anything. Not a hard requirement of the
# classifier itself - a floor on what "labeled" should mean in practice.
MIN_EXAMPLES_PER_INTENT = 20


@pytest.fixture(scope="module")
def dataset():
    with open(DATASET_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def ood_dataset():
    with open(OOD_DATASET_PATH, encoding="utf-8") as fh:
        return json.load(fh)


class TestEveryAllowlistedIntentIsLabeled:
    def test_every_trainable_intent_has_at_least_one_example(self, dataset):
        covered = {item["expected_intent"] for item in dataset}
        missing = TRAINABLE_INTENTS - covered
        assert not missing, (
            f"{missing} have ZERO labeled examples in eval/intent_dataset.json. "
            "The trained classifier (eval/finetune_classifier.py) can never "
            "predict a class absent from its training data - this makes the "
            "intent structurally unreachable via the classifier, not just "
            "under-represented."
        )

    def test_every_trainable_intent_meets_the_minimum_count(self, dataset):
        counts = Counter(item["expected_intent"] for item in dataset)
        thin = {
            intent: counts.get(intent, 0)
            for intent in TRAINABLE_INTENTS
            if counts.get(intent, 0) < MIN_EXAMPLES_PER_INTENT
        }
        assert not thin, (
            f"Intents below the {MIN_EXAMPLES_PER_INTENT}-example floor: {thin}. "
            "Too few examples for a meaningful stratified train/val/test split."
        )

    def test_no_dataset_entry_targets_an_unregistered_intent(self, dataset):
        """The inverse check: catches a typo'd or retired intent name silently
        accumulating dead training examples that never reach any real class."""
        unknown_targets = {
            item["expected_intent"] for item in dataset
        } - ALLOWLIST_INTENTS
        assert not unknown_targets, (
            f"Dataset labels {unknown_targets} that aren't in ALLOWLIST_INTENTS."
        )


class TestOODDatasetCoverage:
    """Same gap, same fix, second file: eval/intent_dataset_ood_test.json had
    15/19 trainable intents covered (10 examples each) - the identical 4
    intents missing from the main dataset were missing here too."""

    OOD_MIN_EXAMPLES_PER_INTENT = 10

    def test_every_trainable_intent_has_ood_examples(self, ood_dataset):
        covered = {item["expected_intent"] for item in ood_dataset}
        missing = TRAINABLE_INTENTS - covered
        assert not missing, f"{missing} have zero OOD test examples."

    def test_every_trainable_intent_meets_the_ood_minimum(self, ood_dataset):
        counts = Counter(item["expected_intent"] for item in ood_dataset)
        thin = {
            intent: counts.get(intent, 0)
            for intent in TRAINABLE_INTENTS
            if counts.get(intent, 0) < self.OOD_MIN_EXAMPLES_PER_INTENT
        }
        assert not thin, f"OOD intents below the {self.OOD_MIN_EXAMPLES_PER_INTENT}-example floor: {thin}"

    def test_ood_set_does_not_overlap_the_training_set(self, dataset, ood_dataset):
        """The whole point of an OOD set is testing generalization to UNSEEN
        phrasing - an entry duplicated into both files would test memorization
        for that one example instead."""
        train_prompts = {item["prompt"].strip().lower() for item in dataset}
        ood_prompts = {item["prompt"].strip().lower() for item in ood_dataset}
        overlap = train_prompts & ood_prompts
        assert not overlap, f"{len(overlap)} prompt(s) appear in both train and OOD sets: {overlap}"


class TestDatasetHygiene:
    def test_no_exact_duplicate_prompts(self, dataset):
        prompts = [item["prompt"].strip().lower() for item in dataset]
        dupes = len(prompts) - len(set(prompts))
        assert dupes == 0, f"{dupes} exact-duplicate prompts (case/whitespace-insensitive)."

    def test_every_entry_has_prompt_and_intent(self, dataset):
        for item in dataset:
            assert isinstance(item.get("prompt"), str) and item["prompt"].strip()
            assert isinstance(item.get("expected_intent"), str) and item["expected_intent"]

    def test_dataset_is_not_trivially_small(self, dataset):
        """Loose sanity floor, not a target - guards against a bad merge or a
        truncated write silently shrinking the file."""
        assert len(dataset) >= 3000
