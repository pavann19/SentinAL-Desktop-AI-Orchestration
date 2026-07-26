# config/paths.py
# ─────────────────────────────────────────────────────────────────────────────
# SentinAL OS — Centralized User-Writable Path Resolver
#
# Problem this solves:
#   When installed to C:\Program Files\, Python's os.getcwd() resolves to a
#   read-only directory. All writes (SQLite DBs, logs) fail with WinError 5.
#
# Solution:
#   All writable paths go through this module, which routes to:
#   1. SENTINAL_DATA_DIR env var  ← set by Electron main.cjs (primary)
#   2. %APPDATA%\SentinAL\       ← Windows production fallback
#   3. Project root               ← development mode (cwd is writable)
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys


def _get_app_data_root() -> str:
    """
    Resolves the correct writable root directory for SentinAL user data.

    Priority order:
    1. SENTINAL_DATA_DIR env var  — set by Electron when running packaged
    2. %APPDATA%\\SentinAL        — Windows production fallback
    3. Project root               — development / bare Python mode
    """
    # Priority 1: Electron tells us where to write (most reliable)
    env_override = os.environ.get("SENTINAL_DATA_DIR", "").strip()
    if env_override:
        return env_override

    # Priority 2: Detect packaged/installed environment.
    # If this file lives inside Program Files or a resources/ asar, use AppData.
    this_file = os.path.abspath(__file__)
    in_program_files = "Program Files" in this_file or "resources" in this_file.replace("\\", "/")
    if in_program_files:
        appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(appdata, "SentinAL")

    # Priority 3: Development — use the project root (2 levels up from config/)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Resolved paths ─────────────────────────────────────────────────────────
APP_DATA_ROOT: str = _get_app_data_root()
LOGS_DIR:      str = os.path.join(APP_DATA_ROOT, "logs")
DATA_DIR:      str = os.path.join(APP_DATA_ROOT, "data")
MEMORY_DIR:    str = os.path.join(APP_DATA_ROOT, "memory")
TELEMETRY_DIR: str = os.path.join(APP_DATA_ROOT, "telemetry")

# ── Ensure all writable dirs exist at import time ──────────────────────────
for _writable_dir in (LOGS_DIR, DATA_DIR, MEMORY_DIR, TELEMETRY_DIR):
    os.makedirs(_writable_dir, exist_ok=True)

# Debug log (visible in Electron DevTools console via backend pipe)
print(f"[Paths] APP_DATA_ROOT -> {APP_DATA_ROOT}")
