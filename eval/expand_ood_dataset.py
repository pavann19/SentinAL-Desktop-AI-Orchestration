"""
eval/expand_ood_dataset.py

Companion to expand_intent_dataset.py: eval/intent_dataset_ood_test.json had
the identical gap - GeneralizedOSIntent, ContinuationIntent, MediaControlIntent
and DictationIntent had zero OOD examples (15/19 trainable intents covered,
10 each). Adds 10 per missing intent, matching the file's existing count and
its deliberately out-of-distribution phrasing style (verbose, unusual verb
choices, paraphrastic - "it would be wonderful if you could...", "initiate
the boot sequence for...", "pop open...") rather than reusing the more direct
phrasing added to the main training set. An OOD set that shares phrasing
style with training data isn't testing generalization, it's testing recall.

Usage:
    python eval/expand_ood_dataset.py            # apply
    python eval/expand_ood_dataset.py --dry-run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parent / "intent_dataset_ood_test.json"

NEW_OOD_EXAMPLES: dict[str, list[str]] = {
    "ContinuationIntent": [
        "would you mind expanding on what you just told me",
        "there's more to that story, isn't there, keep going",
        "don't leave me hanging, what happened after that",
        "I'm curious about the rest of what you were saying",
        "carry on with the explanation from before",
        "so yeah, and then",
        "keep talking, this is interesting",
        "unpack that further for me if you would",
        "what's the remainder of that explanation",
        "pick that thread back up",
    ],
    "DictationIntent": [
        "would you be able to type out everything I'm about to say",
        "I'm going to talk now, please capture it as text",
        "get ready to write down my words verbatim",
        "switch into a mode where you transcribe my speech",
        "I need you acting as a stenographer right now",
        "put my spoken words into written form as I go",
        "let's get this speech-to-text thing going",
        "start capturing whatever comes out of my mouth as text",
        "transcription time, get ready",
        "I want my voice turned into a document as I speak",
    ],
    "MediaControlIntent": [
        "could you possibly bump the sound down a notch",
        "silence this racket immediately",
        "I'd like the next song in the queue please",
        "this track isn't doing it for me, move along",
        "bring the audio level back up to something reasonable",
        "hold the playback right where it is",
        "let the music keep going from here",
        "wind this clip back to the start",
        "give me the tune that played right before this one",
        "cut the sound entirely for a moment",
    ],
    "GeneralizedOSIntent": [
        "would you set up a fresh directory named archive for me",
        "I need this document's name changed to something else",
        "bundle these files into a single compressed package",
        "pull the contents out of this compressed package",
        "show me everything sitting inside this folder",
        "get a terminal window open in this location",
        "run that script I pointed you to earlier",
        "I'd like this file duplicated somewhere else",
        "take me up one level in the folder structure",
        "fire off this command in the shell for me",
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(DATASET_PATH, encoding="utf-8") as fh:
        data = json.load(fh)

    existing = {item["prompt"].strip().lower() for item in data}
    added = 0
    for intent, phrases in NEW_OOD_EXAMPLES.items():
        for phrase in phrases:
            key = phrase.strip().lower()
            if key in existing:
                continue
            data.append({"prompt": phrase, "expected_intent": intent})
            existing.add(key)
            added += 1

    print(f"OOD examples added: {added}")
    print(f"Final OOD count:    {len(data)}")

    if args.dry_run:
        print("--dry-run: not writing to disk.")
        return

    with open(DATASET_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {DATASET_PATH}")


if __name__ == "__main__":
    main()
