# config/snapshots.py
# Storage + retention for the S4 pre-action filesystem snapshots.
#
# A Windows Home/Pro machine has no native copy-on-write overlay filesystem
# (OverlayFS is Linux; ProjFS is heavy, intrusive machinery), so the T2 model
# from CONTAINMENT_ARCHITECTURE.md §6 — "real writes + pre-action snapshot +
# provenance -> restore snapshot" — is implemented as capture-and-restore:
# before a step with a declarable write target runs, the prior state of that
# path is captured; on plan success the capture is discarded, on plan failure
# it is restored.

import os
import tempfile

from config.paths import DATA_DIR

# Snapshots live under the app data area, in their own subtree, so a stray one
# is obviously not project or user content.
SNAPSHOT_ROOT = os.path.join(DATA_DIR, "_snapshots")

# Fallback if DATA_DIR is somehow unwritable at import time.
_SNAPSHOT_ROOT_FALLBACK = os.path.join(tempfile.gettempdir(), "SentinAL_snapshots")

# Keep this many finished-plan snapshot dirs before the oldest are purged.
# A snapshot dir holds file copies, so this is a real disk ceiling, not just
# tidiness.
SNAPSHOT_RETAIN_PLANS = int(os.getenv("SENTINAL_SNAPSHOT_RETAIN_PLANS", "10"))

# A single file larger than this is NOT copied into the snapshot (restore for
# that path degrades to "recorded, but not recoverable" and says so). Stops a
# multi-GB file from being duplicated into the snapshot store.
SNAPSHOT_MAX_FILE_BYTES = int(os.getenv("SENTINAL_SNAPSHOT_MAX_FILE_BYTES", str(64 * 1024 * 1024)))


def snapshot_root() -> str:
    """The directory snapshots are stored under, created on demand. Falls back
    to a temp path if the primary location can't be made."""
    for candidate in (SNAPSHOT_ROOT, _SNAPSHOT_ROOT_FALLBACK):
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except Exception:
            continue
    return SNAPSHOT_ROOT
