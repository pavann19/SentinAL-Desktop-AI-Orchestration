"""
scripts/offline_repl.py — text REPL for SENTINAL_OFFLINE=1.

Runs the real pipeline (extract_intent -> validate -> execute) with no voice
loop, no cloud key, and no network required. Sets SENTINAL_OFFLINE=1 before
anything else is imported so BrainConfig never touches Groq and only touches
Ollama if it's actually reachable (config/settings.py, agentic_core/mock_llm.py)
— with neither available, extraction/planning falls back to a deterministic
stub (agentic_core.mock_llm.DeterministicMockLLM) so the loop still runs
end to end instead of hanging on a network call.

This does NOT stub STT/TTS/wake-word — it doesn't import them at all. The
REPL loop itself (stdin -> process_command() -> print response) is what
replaces voice for this mode; interfaces/voice/* stays exactly as it is.

Usage:
    python scripts/offline_repl.py
    python scripts/offline_repl.py --autonomous     # route as a background goal

Type 'exit' or Ctrl+C/Ctrl+D to quit.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

os.environ.setdefault("SENTINAL_OFFLINE", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main() -> int:
    ap = argparse.ArgumentParser(description="SentinAL offline text REPL")
    ap.add_argument("--autonomous", action="store_true",
                    help="route each prompt as an autonomous background goal (T2/T3 denied)")
    args = ap.parse_args()

    from capabilities.system.api_wrapper import process_command

    print("SentinAL offline REPL -- SENTINAL_OFFLINE=1, no voice, no cloud key required.")
    print("Type a request, or 'exit' to quit.\n")

    while True:
        try:
            prompt = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit"):
            break

        try:
            result = await process_command(prompt, autonomous=args.autonomous)
        except Exception as e:
            print(f"sentinal> [error] {e}\n")
            continue

        print(f"sentinal> {result.get('response', '')}")
        if result.get("execution") not in ("Success", None):
            print(f"          [{result.get('execution')}"
                  f"{': ' + result['failure_category'] if result.get('failure_category') else ''}]")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
