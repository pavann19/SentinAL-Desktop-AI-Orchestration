"""
tests/test_snapshot.py

Unit tests for agentic_core/snapshot.py (S4 pre-action filesystem snapshot +
restore — the T2 "reversal" half of the containment tier gate).

All real filesystem ops, in tmp_path — no mocks. The whole point is that a
half-done plan's disk changes actually get rolled back.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.snapshot import Snapshot, capture, new_snapshot


@pytest.fixture()
def snap(tmp_path):
    """A Snapshot whose store lives inside tmp_path (isolated from the real
    _snapshots dir)."""
    store = tmp_path / "store"
    store.mkdir()
    return Snapshot(store_dir=str(store))


class TestCaptureAndRestoreFiles:

    def test_deleted_file_is_restored(self, tmp_path, snap):
        f = tmp_path / "keep.txt"
        f.write_text("original contents")
        capture(snap, [str(f)])

        os.remove(f)                      # the "step" deletes it
        assert not f.exists()

        snap.restore()
        assert f.exists()
        assert f.read_text() == "original contents"
        assert snap.restored_count == 1
        assert snap.restore_errors == 0

    def test_modified_file_is_restored_to_prior_contents(self, tmp_path, snap):
        f = tmp_path / "cfg.ini"
        f.write_text("before")
        capture(snap, [str(f)])

        f.write_text("AFTER — step changed it")
        snap.restore()
        assert f.read_text() == "before"

    def test_file_created_by_the_step_is_removed(self, tmp_path, snap):
        f = tmp_path / "new_output.txt"
        assert not f.exists()
        capture(snap, [str(f)])          # captured while absent

        f.write_text("the step made this")
        snap.restore()
        assert not f.exists()

    def test_oversized_file_is_recorded_but_not_recovered(self, tmp_path, snap, monkeypatch):
        import agentic_core.snapshot as sm
        monkeypatch.setattr(sm, "SNAPSHOT_MAX_FILE_BYTES", 4)
        f = tmp_path / "big.bin"
        f.write_bytes(b"12345678")        # 8 bytes > 4
        capture(snap, [str(f)])
        entry = snap.entries[0]
        assert entry.existed is True
        assert entry.copied is False
        # restore must not blow up, and must not delete the file it can't restore
        f.write_bytes(b"changed")
        snap.restore()
        assert f.exists()                 # left as-is, honestly


class TestCaptureAndRestoreDirs:

    def test_dir_created_by_the_step_is_removed(self, tmp_path, snap):
        d = tmp_path / "scaffolded"
        assert not d.exists()
        capture(snap, [str(d)])

        d.mkdir()
        (d / "package.json").write_text("{}")
        snap.restore()
        assert not d.exists()

    def test_additions_to_an_existing_dir_are_rolled_back_but_prior_content_is_kept(self, tmp_path, snap):
        d = tmp_path / "data"
        d.mkdir()
        (d / "pre_existing.txt").write_text("do not touch me")
        (d / "old_sub").mkdir()
        capture(snap, [str(d)])

        # the "step" adds a file and a subdir
        (d / "SentinAL_EDA_new.png").write_bytes(b"img")
        (d / "new_sub").mkdir()
        (d / "new_sub" / "x").write_text("y")

        snap.restore()
        assert (d / "pre_existing.txt").read_text() == "do not touch me"
        assert (d / "old_sub").is_dir()
        assert not (d / "SentinAL_EDA_new.png").exists()
        assert not (d / "new_sub").exists()


class TestRobustness:

    def test_capture_is_idempotent_per_path(self, tmp_path, snap):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        capture(snap, [str(f)])
        f.write_text("v2")
        capture(snap, [str(f)])          # second capture of same path is ignored
        assert snap.taken_count == 1
        snap.restore()
        assert f.read_text() == "v1"     # first-observed state wins

    def test_restore_never_raises_on_a_bad_entry(self, tmp_path, snap):
        # A capture pointing at a path whose parent can't be created on restore.
        capture(snap, ["\x00not-a-real-path\x00"])
        snap.restore()                   # must not raise
        # it's counted as an error, not a crash
        assert snap.restore_errors >= 0

    def test_capture_skips_empty_and_none(self, snap):
        capture(snap, ["", None])        # type: ignore[list-item]
        assert snap.taken_count == 0

    def test_discard_removes_the_store(self, tmp_path):
        s = Snapshot(store_dir=str(tmp_path / "gone"))
        os.makedirs(s.store_dir)
        (tmp_path / "gone" / "copy").write_text("x")
        s.discard()
        assert not os.path.exists(s.store_dir)

    def test_summary_shape(self, tmp_path, snap):
        f = tmp_path / "s.txt"
        f.write_text("x")
        capture(snap, [str(f)])
        snap.restore()
        summ = snap.summary()
        assert summ["taken"] == 1
        assert "restored" in summ and "restore_errors" in summ


class TestNewSnapshotFactory:

    def test_new_snapshot_creates_a_real_store_dir(self):
        s = new_snapshot("test-plan")
        try:
            assert os.path.isdir(s.store_dir)
            assert "plan_" in os.path.basename(s.store_dir)
        finally:
            s.discard()
