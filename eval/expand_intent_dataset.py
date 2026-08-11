"""
eval/expand_intent_dataset.py

One-shot (but re-runnable/idempotent) dataset repair for eval/intent_dataset.json.

Fixes two things found while auditing the dataset against ALLOWLIST_INTENTS
(config/constants.py):

1. Four intents had ZERO labeled training examples: GeneralizedOSIntent,
   ContinuationIntent, MediaControlIntent, DictationIntent. This isn't a
   cosmetic gap - eval/finetune_classifier.py's LogisticRegression can never
   predict a class it has never seen in training data, so these four intents
   were permanently unreachable through the trained classifier (Tier 2),
   relying entirely on the router's zero-shot embedding fallback (Tier 1/3).
   agentic_core/router.py's own PHRASE_BANK already documents this exact gap
   at the "GeneralizedOSIntent, ContinuationIntent, DictationIntent, and
   MediaControlIntent have NO training examples" comment near line 628.

2. 45 exact-duplicate prompts (case/whitespace-insensitive) inflate the
   reported dataset size without adding signal.

Phrasing for the four new intents is hand-authored, not templated - varying
directness, formality, length, and natural typos - and deliberately avoids
duplicating phrasings already claimed by other intents' router anchor banks
(e.g. "take a screenshot" / "minimize all windows" are WindowManagementIntent
anchors; GeneralizedOSIntent's new examples stay in file/terminal/generic-UI
territory instead of re-treading that ambiguity).

Usage:
    python eval/expand_intent_dataset.py            # apply and overwrite
    python eval/expand_intent_dataset.py --dry-run   # report only
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parent / "intent_dataset.json"

NEW_EXAMPLES: dict[str, list[str]] = {
    "ContinuationIntent": [
        "continue", "go on", "keep going", "more", "tell me more",
        "elaborate on that", "continue please", "what else",
        "yeah keep talking", "and then what", "say more about that",
        "what happened next", "give me more detail", "and after that",
        "please continue with the explanation",
        "could you elaborate further on this topic",
        "kindly provide additional detail on that point",
        "that's interesting, can you go into more depth about what you just said",
        "I'd like to hear more about the previous point you were making",
        "cotinue please", "tel me more", "what about the rest",
        "keep explaining", "don't stop there", "continue from where you left off",
        "resume that explanation", "pick up where we left off",
        "what's the rest of it", "go deeper into that", "expand on your last point",
        "any more details on this", "carry on", "proceed",
        "keep on explaining", "give me the next part", "what comes after that",
        "is there more to it", "go further into it", "and what else happened",
        "continue the story", "finish explaining that", "go ahead, continue",
        "what's next in the explanation", "add more context to that",
        "dive deeper into that topic", "unpack that a bit more",
        "so what happened after", "please go on with what you were saying",
        "I want to know more", "explain further", "give me the details",
        "what was the rest of that", "please keep going with the answer",
        "and the rest of it", "continue on", "keep it going",
        "more on that please", "what's the continuation",
        "so then what", "and next", "go deeper please",
        "flesh that out a bit more", "say more", "explain more",
        "any more on this subject", "go on with the rest",
        "let's hear the rest", "and what came after that",
        "continue that thought", "finish that thought",
        "you were saying more, go ahead", "please continue talking",
    ],
    "DictationIntent": [
        "take dictation", "start typing what I say",
        "write down what I'm about to say", "please transcribe this for me",
        "I want to dictate a message", "start voice typing now",
        "convert my speech to text", "type out loud what I say",
        "let's do some dictation", "write this exactly as I speak it",
        "begin recording my dictation", "switch to dictation mode",
        "I'm going to dictate a paragraph", "take down my words",
        "type each word as I say it", "start listening and typing",
        "dictate an email to my boss", "help me dictate this letter",
        "write what I speak into the document", "transcribe my voice into text",
        "activate dictation", "turn dictation on", "turn dictation off",
        "stop typing what I say", "end voice typing",
        "I want to speak and have it typed", "please write down everything I say",
        "start transcribing now", "voice to text please",
        "can you type as I talk", "dictate my notes for me",
        "let me speak this out for you to type", "begin taking dictation",
        "start writing what I dictate", "please enter dictation mode",
        "convert speech to text now", "type this for me as I speak",
        "start capturing my voice as text", "go into dictation mode",
        "please transcribe what I say next", "write out loud what I dictate",
        "I'll speak, you type", "dictate a quick note for me",
        "start typing, I'm going to talk now", "record my spoken words as text",
        "please type this message as I say it", "begin voice-to-text mode",
        "let's start dictating", "write down this paragraph as I say it",
        "dictate a reply to this email", "take this down verbatim",
        "type verbatim what I say", "listen and type everything",
        "start transcription mode", "please write this letter as I speak it",
        "I'd like to dictate something", "start my dictation session",
        "type what I'm saying right now", "begin transcribing my speech",
        "write this document as I talk", "let's dictate a memo",
        "please take this dictation down", "start writing as I speak",
        "activate voice typing mode", "I need to dictate a paragraph now",
    ],
    "MediaControlIntent": [
        "turn the volume all the way up", "crank up the volume",
        "lower the volume a bit", "mute my speakers", "unmute the sound",
        "next song please", "skip to the next track",
        "go to the previous track", "pause this", "play this",
        "resume the song", "stop playing music", "increase the volume by 10",
        "decrease the volume", "set volume to zero", "max out the volume",
        "silence the audio", "turn sound off", "turn sound back on",
        "toggle play and pause", "skip ahead", "go back a track",
        "restart the current song", "loop this track", "shuffle the playlist",
        "stop the video", "fast forward this video a bit",
        "rewind this a little", "seek forward 30 seconds",
        "jump back 10 seconds", "skip this track, I don't like it",
        "next track", "previous track", "pause the music",
        "resume playback please", "raise the volume", "drop the volume down",
        "turn it up a bit", "turn it down please", "bump the volume up",
        "quiet it down a little", "can you mute this", "unmute please",
        "play the song again", "replay this track", "start the playlist over",
        "put it on repeat", "turn off repeat", "enable shuffle mode",
        "disable shuffle", "stop the current track", "resume where I left off",
        "go to the next episode", "play the previous episode",
        "skip the intro", "fast forward a minute", "rewind to the beginning",
        "lower the sound a little bit", "turn the sound way down",
        "crank the volume to max", "set the volume halfway",
        "pause playback now", "unpause the video", "stop the audio",
        "hit play", "hit pause", "next please", "back please",
    ],
    "GeneralizedOSIntent": [
        "create a new text file", "make a new folder called projects",
        "rename this file to report", "copy this file to the desktop",
        "move this to downloads", "zip these files together",
        "extract this archive", "list everything in this directory",
        "show me what's in this folder", "open a terminal here",
        "run this command for me", "execute this python script",
        "click the submit button", "right click on this icon",
        "drag this file into that folder", "scroll down a bit",
        "scroll to the top of the page", "press enter", "press escape",
        "hit the tab key", "select all the text", "copy this to clipboard",
        "paste from clipboard", "undo the last action", "redo that",
        "close this tab", "switch to the terminal window",
        "open file explorer here", "navigate to my documents folder",
        "go up one directory", "compress this folder into a zip",
        "unzip this file", "check disk usage of this folder",
        "show hidden files", "change the file extension",
        "duplicate this file", "create a shortcut for this app",
        "run this batch script", "execute this shell command",
        "open a new command prompt", "create a folder named archive",
        "make a copy of this document", "rename that folder",
        "move these files into one directory", "list the contents of this folder",
        "open powershell here", "run this powershell script",
        "navigate up two directories", "go back to the previous folder",
        "open this file in a text editor", "create an empty file here",
        "check the file size of this document", "compress this into a tar file",
        "extract this tar archive", "list all running background tasks",
        "check the current working directory", "print the directory path",
        "make a backup copy of this file", "clone this folder structure",
        "create a symbolic link to this file", "open this folder in explorer",
        "run a diagnostic on this system", "execute a health check script",
        "run the setup script", "install this from the local folder",
        "unpack this zip archive here", "check free space on this drive",
    ],
}


def load_dataset() -> list[dict]:
    with open(DATASET_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def dedupe(data: list[dict]) -> tuple[list[dict], int]:
    seen: set[str] = set()
    out: list[dict] = []
    removed = 0
    for item in data:
        key = item["prompt"].strip().lower()
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        out.append(item)
    return out, removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = load_dataset()
    original_count = len(data)

    deduped, removed = dedupe(data)

    existing_prompts = {item["prompt"].strip().lower() for item in deduped}
    added = 0
    for intent, phrases in NEW_EXAMPLES.items():
        for phrase in phrases:
            key = phrase.strip().lower()
            if key in existing_prompts:
                continue
            deduped.append({"prompt": phrase, "expected_intent": intent})
            existing_prompts.add(key)
            added += 1

    print(f"Original entries:      {original_count}")
    print(f"Exact duplicates removed: {removed}")
    print(f"New examples added:     {added}")
    print(f"Final entries:          {len(deduped)}")

    if args.dry_run:
        print("--dry-run: not writing to disk.")
        return

    with open(DATASET_PATH, "w", encoding="utf-8") as fh:
        json.dump(deduped, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {DATASET_PATH}")


if __name__ == "__main__":
    main()
