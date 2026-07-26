# capabilities/system/process_manager.py
# Process Management capability for SentinAL.
# Provides safe tasklist inspection and targeted taskkill for user-owned processes.
#
# Design:
#   - tasklist() wraps `tasklist /fo csv /nh` and parses output
#   - kill_process() ONLY kills non-system processes (validates against SOFT_SENSITIVE_TARGETS)
#   - All results returned as structured dicts for LLM summarization

import subprocess
import csv
import io
import re
import logging

from config.constants import SOFT_SENSITIVE_TARGETS, SENSITIVE_TARGETS

_logger = logging.getLogger("ProcessManager")

# Processes that must never be killed — OS integrity protection
_PROTECTED_PROCESS_PREFIXES = {
    "system", "smss", "csrss", "wininit", "winlogon", "services",
    "lsass", "lsm", "svchost", "dwm", "conhost", "explorer",
    "spoolsv", "audiodg", "taskhost", "taskhostw", "sihost",
    "fontdrvhost", "runtimebroker", "securityhealthservice",
}


def list_processes(name_filter: str = "") -> list[dict]:
    """
    Returns a list of running processes as structured dicts.
    Optionally filtered by a case-insensitive name substring.

    Returns:
        [{"name": str, "pid": int, "mem_kb": str}]
    """
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            _logger.error(f"tasklist failed: {result.stderr.strip()}")
            return []

        processes = []
        reader = csv.reader(io.StringIO(result.stdout))
        for row in reader:
            if len(row) < 5:
                continue
            name, pid, _, _, mem = row[0], row[1], row[2], row[3], row[4]
            name_clean = name.strip('"')
            if name_filter and name_filter.lower() not in name_clean.lower():
                continue
            try:
                processes.append({
                    "name": name_clean,
                    "pid": int(pid.strip('"')),
                    "mem_kb": mem.strip('"'),
                })
            except ValueError:
                continue

        _logger.info(f"list_processes: found {len(processes)} matching '{name_filter}'")
        return processes

    except subprocess.TimeoutExpired:
        _logger.error("tasklist timed out after 10s")
        return []
    except Exception as e:
        _logger.error(f"list_processes error: {e}")
        return []


def kill_process(target: str) -> str:
    """
    Terminates a process by name or PID. Enforces a strict allow-list
    to prevent killing system-critical processes.

    Args:
        target: Process name (e.g. 'notepad.exe') or PID string (e.g. '1234')

    Returns:
        str: Human-readable result message
    """
    if not target:
        return "ERROR: No process name or PID specified."

    target_lower = target.lower().strip()

    # 1. Block any protected OS processes
    base_name = re.sub(r'\.exe$', '', target_lower)
    if base_name in _PROTECTED_PROCESS_PREFIXES:
        _logger.warning(f"kill_process BLOCKED — protected process: {target}")
        return f"I can't terminate '{target}' — it's a protected OS process."

    # 2. Block SENSITIVE_TARGETS and SOFT_SENSITIVE_TARGETS keywords
    for blocked in SENSITIVE_TARGETS + SOFT_SENSITIVE_TARGETS:
        if blocked.strip().lower() in target_lower:
            _logger.warning(f"kill_process BLOCKED — policy match '{blocked}': {target}")
            return f"I can't terminate '{target}' — it matches a protected policy keyword."

    # 3. Determine if target is a PID or name
    is_pid = target.strip().isdigit()
    filter_flag = "/PID" if is_pid else "/IM"

    try:
        result = subprocess.run(
            ["taskkill", filter_flag, target.strip(), "/F"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            msg = f"Process '{target}' terminated successfully."
            _logger.info(msg)
            return msg
        else:
            err = result.stderr.strip() or result.stdout.strip()
            _logger.warning(f"taskkill failed for '{target}': {err}")
            return f"Could not terminate '{target}': {err}"

    except subprocess.TimeoutExpired:
        return f"ERROR: taskkill timed out for '{target}'."
    except Exception as e:
        _logger.error(f"kill_process error: {e}")
        return f"ERROR terminating '{target}': {e}"
