# agentic_core/snapshot.py
# Pre-action filesystem snapshot + restore for SentinAL's S4 containment
# substrate (the T2 "reversal" half of the tier gate — the capability broker
# gives the tier, this makes a T2/T3 filesystem effect undoable).
#
# Not a union/overlay filesystem — Windows has no native one. This captures the
# prior state of the specific paths a step declares it will touch, then either
# discards the capture (plan succeeded) or restores from it (plan failed):
#
#   path was a FILE that existed  -> copied aside; restore = delete current, copy back
#   path was a FILE, absent       -> restore = delete it if the step created it
#   path was a DIR that existed   -> top-level entry manifest recorded; restore =
#                                    remove entries added since (additions only —
#                                    pre-existing content is never touched)
#   path was a DIR, absent        -> restore = rmtree it if the step created it
#
# Never raises: every restore operation is guarded, failures are logged and the
# rest continue. Same non-raising contract as postcondition_observer.py.

from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field

from config.snapshots import (
    SNAPSHOT_MAX_FILE_BYTES,
    SNAPSHOT_RETAIN_PLANS,
    snapshot_root,
)

_logger = logging.getLogger("Snapshot")


@dataclass
class PathSnapshot:
    """The captured prior state of one path."""
    path: str
    existed: bool
    was_dir: bool = False
    copy_path: str | None = None          # where a file copy lives (files only, if copied)
    copied: bool = False                  # False = existed but too big / uncopyable
    dir_entries: set[str] = field(default_factory=set)  # top-level names, dirs only
    note: str = ""


@dataclass
class Snapshot:
    """A plan's worth of PathSnapshots plus their backing store."""
    store_dir: str
    entries: list[PathSnapshot] = field(default_factory=list)
    restored_count: int = 0
    restore_errors: int = 0

    @property
    def taken_count(self) -> int:
        return len(self.entries)

    def restore(self) -> None:
        """Reverse every captured path, newest capture first. Best-effort."""
        for snap in reversed(self.entries):
            try:
                self._restore_one(snap)
                self.restored_count += 1
            except Exception as e:
                self.restore_errors += 1
                _logger.warning(f"[snapshot] restore failed for {snap.path}: {e}")

    def _restore_one(self, snap: PathSnapshot) -> None:
        p = snap.path
        if not snap.existed:
            # The step may have created it — remove what it created.
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p)
                _logger.info(f"[snapshot] removed step-created file: {p}")
            elif os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                _logger.info(f"[snapshot] removed step-created dir: {p}")
            return

        if snap.was_dir:
            # Restore = remove entries that appeared since the snapshot; leave
            # everything that was already there untouched.
            if not os.path.isdir(p):
                return
            for name in os.listdir(p):
                if name in snap.dir_entries:
                    continue
                child = os.path.join(p, name)
                if os.path.isdir(child) and not os.path.islink(child):
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        os.remove(child)
                    except OSError:
                        pass
            _logger.info(f"[snapshot] rolled back additions under: {p}")
            return

        # It was a file that existed.
        if not snap.copied or not snap.copy_path or not os.path.exists(snap.copy_path):
            _logger.warning(
                f"[snapshot] {p} existed but was not recoverable (too large / not copied); left as-is."
            )
            return
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.exists(p) or os.path.islink(p):
            os.remove(p)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        shutil.copy2(snap.copy_path, p)
        _logger.info(f"[snapshot] restored file from copy: {p}")

    def discard(self) -> None:
        """Delete the backing store — call on plan success."""
        try:
            shutil.rmtree(self.store_dir, ignore_errors=True)
        except Exception as e:
            _logger.debug(f"[snapshot] discard failed for {self.store_dir}: {e}")

    def summary(self) -> dict:
        return {
            "taken": self.taken_count,
            "restored": self.restored_count,
            "restore_errors": self.restore_errors,
        }


def _purge_old_stores(root: str) -> None:
    """Keep only the newest SNAPSHOT_RETAIN_PLANS store dirs."""
    try:
        stores = [
            os.path.join(root, d) for d in os.listdir(root)
            if d.startswith("plan_") and os.path.isdir(os.path.join(root, d))
        ]
        stores.sort(key=os.path.getmtime, reverse=True)
        for stale in stores[SNAPSHOT_RETAIN_PLANS:]:
            shutil.rmtree(stale, ignore_errors=True)
    except Exception:
        pass


def new_snapshot(plan_label: str = "plan") -> Snapshot:
    """Allocates an empty Snapshot with a fresh per-plan store directory."""
    root = snapshot_root()
    _purge_old_stores(root)
    safe = "".join(c for c in plan_label if c.isalnum() or c in "-_")[:32] or "plan"
    store = os.path.join(root, f"plan_{safe}_{int(time.time())}_{uuid.uuid4().hex[:8]}")
    try:
        os.makedirs(store, exist_ok=True)
    except Exception:
        store = os.path.join(root, f"plan_{uuid.uuid4().hex[:12]}")
        os.makedirs(store, exist_ok=True)
    return Snapshot(store_dir=store)


def capture(snapshot: Snapshot, paths: list[str]) -> None:
    """
    Adds a PathSnapshot for each path to `snapshot`. Idempotent per path within
    one Snapshot — a path already captured is not re-captured (its FIRST
    observed state is the one to restore to).
    """
    already = {e.path for e in snapshot.entries}
    for raw in paths or []:
        if not raw:
            continue
        p = os.path.abspath(raw)
        if p in already:
            continue
        already.add(p)
        snapshot.entries.append(_capture_one(snapshot.store_dir, p))


def _capture_one(store_dir: str, p: str) -> PathSnapshot:
    if not os.path.exists(p) and not os.path.islink(p):
        return PathSnapshot(path=p, existed=False)

    if os.path.isdir(p) and not os.path.islink(p):
        try:
            entries = set(os.listdir(p))
        except OSError as e:
            return PathSnapshot(path=p, existed=True, was_dir=True, note=f"listdir failed: {e}")
        return PathSnapshot(path=p, existed=True, was_dir=True, dir_entries=entries)

    # A file (or a link — treated as a file for copy purposes).
    try:
        size = os.path.getsize(p)
    except OSError:
        size = SNAPSHOT_MAX_FILE_BYTES + 1  # force "not copied"
    if size > SNAPSHOT_MAX_FILE_BYTES:
        return PathSnapshot(
            path=p, existed=True, was_dir=False, copied=False,
            note=f"file {size} bytes exceeds snapshot copy limit {SNAPSHOT_MAX_FILE_BYTES}",
        )
    copy_path = os.path.join(store_dir, uuid.uuid4().hex + "_" + os.path.basename(p))
    try:
        shutil.copy2(p, copy_path)
        return PathSnapshot(path=p, existed=True, was_dir=False, copy_path=copy_path, copied=True)
    except Exception as e:
        return PathSnapshot(path=p, existed=True, was_dir=False, copied=False, note=f"copy failed: {e}")
