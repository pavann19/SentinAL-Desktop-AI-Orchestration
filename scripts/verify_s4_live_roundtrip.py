"""
scripts/verify_s4_live_roundtrip.py -- S4 live containment round-trip.

ROADMAP S4 has one open checkbox: "Live end-to-end round-trip NOT verified --
a full live `npm install <pkg>` through the actual container was not
completed" (Docker Desktop starts on this RAM-constrained machine dropped
available memory under 1 GB and Docker self-terminated).

This script performs that verification, once, with a memory watchdog so a
tight run produces a report instead of an ambiguous crash. It is meant to be
run from a plain terminal with Claude Desktop CLOSED (that frees ~1-1.5 GB
physical + ~2.2 GB commit -- see the session notes).

    python scripts/verify_s4_live_roundtrip.py
    python scripts/verify_s4_live_roundtrip.py --via-pipeline   # also drive the real npm_install()
    python scripts/verify_s4_live_roundtrip.py --keep           # leave the work dir for inspection

What it proves (or doesn't), each recorded as an independent check:

  1. docker_daemon_reachable       -- `docker info` returns 0
  2. routing_selects_sandbox       -- npm_install()'s own script builder picks the
                                     Docker path (`docker run --rm -v ...`)
  3. image_available               -- node:20-slim present (pulled if not)
  4. container_install_succeeded   -- the real `docker run --rm ... npm install <pkg>`
                                     exits 0
  5. written_through_mount         -- node_modules/<pkg>/package.json appears in the
                                     HOST work dir → the container wrote through the
                                     bind mount, i.e. the install really happened
                                     inside the throwaway container
  6. container_auto_removed        -- no leftover container (`--rm` honoured)
  7. no_linux_native_artifacts     -- informational: no *.node built for Linux
  8. via_pipeline_roundtrip        -- only with --via-pipeline: the real
                                     capabilities.developer.dependency_installer.npm_install()
                                     produces node_modules within the timeout

Overall PASS requires checks 1, 2, 4, 5 (and 8 when requested). 3 passes if the
image is present or was pulled. 6 and 7 are recorded but do not gate.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from capabilities.developer.dependency_installer import (  # noqa: E402
    _DOCKER_NODE_IMAGE,
    _docker_available,
    _sandboxed_npm_script_body,
)

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "results")
DEFAULT_PKG = "is-number"  # 2 KB, zero deps, no native build -- the cleanest probe


# ── memory sampling ─────────────────────────────────────────────────────────

def _free_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().available / (1024 ** 3), 2)
    except Exception:
        return -1.0


class MemWatch:
    """Samples available RAM on a background thread while a step runs."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[float] = []

    def __enter__(self):
        self.samples.append(_free_gb())
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(self.interval):
            self.samples.append(_free_gb())

    def __exit__(self, *_exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.samples.append(_free_gb())

    @property
    def min_gb(self) -> float:
        real = [s for s in self.samples if s >= 0]
        return min(real) if real else -1.0


# ── check plumbing ─────────────────────────────────────────────────────────

class Report:
    def __init__(self):
        self.checks: list[dict] = []
        self.meta: dict = {}

    def add(self, name: str, status: str, detail: str = "", **extra):
        self.checks.append({"check": name, "status": status, "detail": detail, **extra})
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "skip", "INFO": "info"}.get(status, status)
        print(f"  [{mark:>4}] {name:<28} {detail}")

    def status(self, name: str) -> str:
        for c in self.checks:
            if c["check"] == name:
                return c["status"]
        return "MISSING"


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


# ── the round-trip ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="S4 live containment round-trip verification")
    ap.add_argument("--package", default=DEFAULT_PKG, help=f"npm package to install (default: {DEFAULT_PKG})")
    ap.add_argument("--pull-timeout", type=float, default=240.0)
    ap.add_argument("--install-timeout", type=float, default=360.0)
    ap.add_argument("--via-pipeline", action="store_true",
                    help="also drive the real npm_install() and poll for node_modules")
    ap.add_argument("--keep", action="store_true", help="do not delete the work dir(s)")
    ap.add_argument("--output", help="report JSON path")
    args = ap.parse_args()

    pkg = args.package
    rep = Report()
    started = time.time()

    print("\n" + "=" * 74)
    print("S4 live containment round-trip".center(74))
    print("=" * 74)

    free_start = _free_gb()
    try:
        docker_ver = _run(["docker", "--version"], 10).stdout.strip()
    except Exception as e:
        docker_ver = f"docker --version failed: {e}"
    wslcfg = os.path.join(os.path.expanduser("~"), ".wslconfig")
    rep.meta = {
        "package": pkg,
        "docker_version": docker_ver,
        "wslconfig": open(wslcfg, encoding="utf-8").read() if os.path.isfile(wslcfg) else "(none)",
        "free_ram_gb_at_start": free_start,
        "image": _DOCKER_NODE_IMAGE,
    }
    print(f"  docker      {docker_ver}")
    print(f"  free RAM    {free_start} GB")
    print(f"  image       {_DOCKER_NODE_IMAGE}")
    print("-" * 74)

    # 1 ─ daemon reachable
    avail = _docker_available()
    info = _run(["docker", "info"], 15) if avail else None
    if avail and info and info.returncode == 0:
        rep.add("docker_daemon_reachable", "PASS", "docker info returned 0")
    else:
        rep.add("docker_daemon_reachable", "FAIL",
                "Docker daemon not reachable -- start Docker Desktop and retry")
        return _finish(rep, started, args, overall=False)

    # 2 ─ routing: npm_install()'s own builder picks the sandbox path
    probe_dir = tempfile.mkdtemp(prefix="sentinal_s4_probe_")
    body = _sandboxed_npm_script_body([pkg], False, probe_dir)
    routing_ok = (
        "docker run --rm" in body
        and f'-v "{probe_dir}:/workspace"' in body
        and _DOCKER_NODE_IMAGE in body
        and f"npm install {pkg}" in body
    )
    shutil.rmtree(probe_dir, ignore_errors=True)
    rep.add("routing_selects_sandbox", "PASS" if routing_ok else "FAIL",
            "npm_install() builds a `docker run --rm -v ...` command" if routing_ok
            else f"sandbox command not found in builder output: {body[:200]!r}")

    # 3 ─ image present (pull if not)
    have_img = _run(["docker", "image", "inspect", _DOCKER_NODE_IMAGE], 20).returncode == 0
    if have_img:
        rep.add("image_available", "PASS", "node:20-slim already present")
    else:
        print(f"  ... pulling {_DOCKER_NODE_IMAGE} (first run, ~75 MB) ...")
        try:
            with MemWatch() as mw:
                pull = _run(["docker", "pull", _DOCKER_NODE_IMAGE], args.pull_timeout)
            if pull.returncode == 0:
                rep.add("image_available", "PASS",
                        f"pulled ok (min free during pull: {mw.min_gb} GB)")
            else:
                rep.add("image_available", "FAIL", f"pull failed: {pull.stderr.strip()[:200]}")
                return _finish(rep, started, args, overall=False)
        except subprocess.TimeoutExpired:
            rep.add("image_available", "FAIL", f"pull timed out after {args.pull_timeout}s")
            return _finish(rep, started, args, overall=False)

    # 4 ─ the real container install, synchronous, with a memory watchdog
    work = tempfile.mkdtemp(prefix="sentinal_s4_run_")
    with open(os.path.join(work, "package.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "s4-roundtrip", "version": "1.0.0", "private": True}, fh)

    docker_cmd = [
        "docker", "run", "--rm", "-v", f"{work}:/workspace", "-w", "/workspace",
        _DOCKER_NODE_IMAGE, "npm", "install", pkg,
    ]
    print(f"  ... {' '.join(docker_cmd)}")
    install_rc = None
    install_tail = ""
    try:
        with MemWatch() as mw:
            t0 = time.time()
            cp = _run(docker_cmd, args.install_timeout)
            install_secs = round(time.time() - t0, 1)
        install_rc = cp.returncode
        install_tail = (cp.stdout + cp.stderr).strip().splitlines()[-6:]
        rep.meta["install_seconds"] = install_secs
        rep.meta["min_free_ram_gb_during_install"] = mw.min_gb
        if install_rc == 0:
            rep.add("container_install_succeeded", "PASS",
                    f"exit 0 in {install_secs}s (min free RAM: {mw.min_gb} GB)")
        else:
            rep.add("container_install_succeeded", "FAIL",
                    f"exit {install_rc}; tail: {' | '.join(install_tail)}")
    except subprocess.TimeoutExpired:
        rep.add("container_install_succeeded", "FAIL",
                f"timed out after {args.install_timeout}s (min free RAM: {mw.min_gb} GB) "
                "-- likely memory pressure; close other apps and retry")

    # 5 ─ written through the bind mount (the actual containment proof)
    marker = os.path.join(work, "node_modules", pkg, "package.json")
    if os.path.isfile(marker):
        rep.add("written_through_mount", "PASS",
                f"node_modules/{pkg}/package.json present in the host work dir")
    else:
        rep.add("written_through_mount", "FAIL",
                f"{marker} missing -- the container did not write through the mount")

    # 6 ─ --rm honoured
    leftovers = _run(
        ["docker", "ps", "-a", "--filter", f"ancestor={_DOCKER_NODE_IMAGE}", "--format", "{{.ID}} {{.Command}}"],
        15,
    ).stdout.strip()
    rep.add("container_auto_removed", "PASS" if not leftovers else "INFO",
            "no leftover container" if not leftovers else f"containers still listed: {leftovers}")

    # 7 ─ informational: Linux-native artifacts (is-number has none)
    native = []
    for root, _dirs, files in os.walk(os.path.join(work, "node_modules")):
        native += [os.path.join(root, f) for f in files if f.endswith(".node")]
    rep.add("no_linux_native_artifacts", "PASS" if not native else "INFO",
            "none" if not native else f"{len(native)} .node file(s) -- pipeline's host-fallback path covers this")

    # 8 ─ optional: the real production entry point
    if args.via_pipeline:
        from capabilities.developer.dependency_installer import npm_install
        work2 = tempfile.mkdtemp(prefix="sentinal_s4_pipe_")
        with open(os.path.join(work2, "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "s4-pipe", "version": "1.0.0", "private": True}, fh)
        print(f"  ... npm_install({pkg!r}, cwd={work2!r})  [spawns a console window]")
        launch_msg = npm_install(pkg, cwd=work2)
        rep.meta["pipeline_launch_message"] = launch_msg
        pipe_marker = os.path.join(work2, "node_modules", pkg, "package.json")
        deadline = time.time() + args.install_timeout
        while time.time() < deadline and not os.path.isfile(pipe_marker):
            time.sleep(2.0)
        if os.path.isfile(pipe_marker):
            rep.add("via_pipeline_roundtrip", "PASS",
                    f"npm_install() produced node_modules/{pkg} within {args.install_timeout}s")
        else:
            rep.add("via_pipeline_roundtrip", "FAIL",
                    f"node_modules/{pkg} not present after {args.install_timeout}s")
        if not args.keep:
            shutil.rmtree(work2, ignore_errors=True)

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        rep.meta["work_dir_kept"] = work

    gating = ["docker_daemon_reachable", "routing_selects_sandbox",
              "container_install_succeeded", "written_through_mount"]
    if args.via_pipeline:
        gating.append("via_pipeline_roundtrip")
    overall = all(rep.status(g) == "PASS" for g in gating)
    return _finish(rep, started, args, overall=overall)


def _finish(rep: Report, started: float, args, overall: bool) -> int:
    rep.meta["free_ram_gb_at_end"] = _free_gb()
    rep.meta["duration_seconds"] = round(time.time() - started, 1)

    print("-" * 74)
    print(f"  RESULT: {'PASS -- S4 live round-trip verified' if overall else 'FAIL -- see checks above'}")
    print("=" * 74 + "\n")

    payload = {
        "schema": 1,
        "kind": "s4_live_roundtrip",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "overall_pass": overall,
        "meta": rep.meta,
        "checks": rep.checks,
    }
    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = args.output or os.path.join(REPORT_DIR, f"s4_live_roundtrip_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"  report: {os.path.abspath(path)}\n")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
