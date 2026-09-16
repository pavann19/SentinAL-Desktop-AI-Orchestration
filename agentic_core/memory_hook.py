# memory_manager.py
# Dynamic Intent Memory & URL Cache for SentinAL.
# Uses SQLite to persist learned user preferences and platform route templates.

import os
import sqlite3
import threading

from config.paths import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "sentinal_memory.db")


class MemoryManager:
    """
    Manages a local SQLite database for SentinAL's dynamic memory.
    Stores:
      - Interaction history (intents, targets, timestamps)
      - URL cache (platform -> url_template) for learned platform routes
    """
    def __init__(self, db_path=DB_PATH):
        """Initializes the database and ensures all required tables exist."""
        self.db_path = db_path
        self._lock = threading.Lock()
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_tables()

    def _init_tables(self):
        """Creates all required tables if they do not already exist."""
        with self._lock:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS interaction_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    intent      TEXT    NOT NULL,
                    target      TEXT,
                    result      TEXT,
                    platform    TEXT
                )
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS url_cache (
                    platform     TEXT PRIMARY KEY,
                    url_template TEXT
                )
            """)
            # Fix 2.9: Thread-safe path cache — replaces raw sqlite3.connect in executor
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS path_cache (
                    folder_name   TEXT PRIMARY KEY,
                    absolute_path TEXT NOT NULL
                )
            """)
            # Process watches: detached, long-running work (CodeAct scripts,
            # dependency installs) that cannot be verified synchronously because
            # the request returns long before the work finishes. Persisted rather
            # than held in memory so a watch survives a backend restart — the
            # spawned process does not die with us, so neither should the record
            # that something is still outstanding.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS process_watches (
                    watch_id      TEXT PRIMARY KEY,
                    label         TEXT NOT NULL,
                    sentinel_path TEXT,
                    pid           INTEGER,
                    expected_state TEXT,
                    registered_at REAL NOT NULL,
                    status        TEXT NOT NULL,
                    resolved_at   REAL,
                    detail        TEXT
                )
            """)
            # Scheduled tasks / reminders for SchedulerIntent. Replaces the
            # earlier fabricated-success stub (see MERGE_LOG.md / git history)
            # that told users "I will remind you" while writing nothing
            # anywhere. due_at is nullable: a plain task ("add X to my list")
            # has no due time, only a reminder ("remind me to X at 5pm") does.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    task_id      TEXT PRIMARY KEY,
                    description  TEXT NOT NULL,
                    due_at       REAL,
                    created_at   REAL NOT NULL,
                    completed    INTEGER NOT NULL DEFAULT 0,
                    completed_at REAL
                )
            """)
            # S6 event bus (increment 1): notified_at records when the resident
            # event-bus loop fired a "reminder due" notification for a row, so a
            # due reminder is announced exactly once, not every poll tick.
            # Additive migration — SQLite has no ADD COLUMN IF NOT EXISTS, so
            # check PRAGMA first (older DBs created before this column exists).
            cols = {r[1] for r in self.cursor.execute("PRAGMA table_info(scheduled_tasks)").fetchall()}
            if "notified_at" not in cols:
                self.cursor.execute("ALTER TABLE scheduled_tasks ADD COLUMN notified_at REAL")
            # S6 event bus (increment 2): kind distinguishes a plain reminder
            # (default — the event bus just notifies) from an autonomous goal
            # (the event bus runs it through process_command(autonomous=True),
            # only when SENTINAL_AUTONOMOUS_GOALS_ENABLED). Nothing sets 'goal'
            # yet — there is no user-facing way to create one; increment 2
            # ships the execution capability, inert by default.
            if "kind" not in cols:
                self.cursor.execute(
                    "ALTER TABLE scheduled_tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'reminder'"
                )

            # S6 semantic memory (increment 1): past interactions embedded with
            # the router's all-MiniLM-L6-v2, for retrieval by MEANING rather
            # than only recency (interaction_history / get_context_for_prompt
            # give recency). embedding is a raw float32 array as BLOB — a
            # brute-force cosine scan over recent rows, no vector server (per
            # SENTINAL_V2_RECONCILED_ARCHITECTURE.md §7).
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_semantic (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    text      TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    intent    TEXT,
                    target    TEXT,
                    result    TEXT,
                    ts        REAL NOT NULL
                )
            """)
            # S6 semantic memory (increment 2): plan holds the JSON step-shape
            # ([{intent, target}, ...]) of a SUCCESSFUL multi-step run, so the
            # planner can be shown how a similar past goal was decomposed.
            # NULL for single-step and failed runs, and for rows written by
            # increment 1. Additive migration — same PRAGMA-first pattern.
            sem_cols = {r[1] for r in self.cursor.execute("PRAGMA table_info(memory_semantic)").fetchall()}
            if "plan" not in sem_cols:
                self.cursor.execute("ALTER TABLE memory_semantic ADD COLUMN plan TEXT")

            # S6 procedural memory: a recipe is the STRUCTURE of a multi-step
            # plan that has succeeded organically several times. When a new goal
            # is a near-verbatim match, the planner replays the stored graph
            # instead of calling the planning LLM. fingerprint is a hash of the
            # canonical node structure; graph_json is GoalGraph.to_dict() reduced
            # to structural fields. success_count promotes; a single failed
            # replay retires the recipe (failure_count > 0).
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_procedural (
                    fingerprint     TEXT PRIMARY KEY,
                    goal_text       TEXT NOT NULL,
                    embedding       BLOB NOT NULL,
                    graph_json      TEXT NOT NULL,
                    success_count   INTEGER NOT NULL DEFAULT 0,
                    failure_count   INTEGER NOT NULL DEFAULT 0,
                    created_ts      REAL NOT NULL,
                    last_success_ts REAL NOT NULL
                )
            """)

            # S7 world model (increment A1): a rolling record of the digital
            # environment — running processes + foreground window — sampled by
            # the resident event-bus loop. Turns memory from a log into a
            # queryable "what's open now / what changed" model. Retention is
            # bounded (row count + age) and pruned on every write.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS env_state (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         REAL NOT NULL,
                    proc_hash  TEXT NOT NULL,
                    proc_count INTEGER NOT NULL,
                    fg_app     TEXT,
                    fg_title   TEXT,
                    procs_json TEXT NOT NULL
                )
            """)

            # S7 world model (Half B): one row per executed capability per run —
            # verified (did the run succeed), failure_category, whole-command
            # latency, containment tier. A sustained drop in one capability's
            # rolling success rate is the drift signal (an app updated its UI, a
            # site redesigned) — independent of everything else. S7 produces the
            # signal; acting on it (targeted re-learning) is S8.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS capability_outcomes (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts               REAL NOT NULL,
                    intent           TEXT NOT NULL,
                    verified         INTEGER NOT NULL,
                    failure_category TEXT,
                    latency_ms       REAL,
                    tier             TEXT
                )
            """)

            # S8 skill learning: a learned skill is a validated capability
            # recipe originated from observed successes rather than hand-
            # written. skeleton_json + slots_json are the abstracted
            # (typed-slot) recipe; state moves candidate -> active -> demoted
            # / retired; tier is ALWAYS T1 for origin='learned' (a learned
            # skill starts more restricted than a hand-authored one and earns
            # trust). learned_skill_events is the append-only audit trail.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS learned_skills (
                    skill_id          TEXT PRIMARY KEY,
                    fingerprint       TEXT NOT NULL,
                    skeleton_json     TEXT NOT NULL,
                    slots_json        TEXT NOT NULL,
                    goal_examples_json TEXT NOT NULL DEFAULT '[]',
                    postcondition_kind TEXT,
                    origin            TEXT NOT NULL DEFAULT 'learned',
                    tier              TEXT NOT NULL DEFAULT 'T1',
                    confidence        REAL NOT NULL DEFAULT 0.0,
                    state             TEXT NOT NULL DEFAULT 'candidate',
                    n_instances       INTEGER NOT NULL DEFAULT 0,
                    created_ts        REAL NOT NULL,
                    validated_ts      REAL,
                    activated_ts      REAL
                )
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS learned_skill_events (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    ts       REAL NOT NULL,
                    event    TEXT NOT NULL,
                    detail   TEXT
                )
            """)
            # S8-5: per-skill live outcomes, for drift-based demotion — the
            # same signal shape as capability_outcomes (S7 Half B) but keyed
            # by skill_id instead of intent.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS learned_skill_outcomes (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    ts       REAL NOT NULL,
                    verified INTEGER NOT NULL
                )
            """)

            # S9-1: versioned self-improvement changes. Every applied tuning
            # change is a new row; revert = mark the latest promoted one
            # reverted so the previous value becomes current. state:
            # proposed | shadow_passed | shadow_failed | promoted | rejected |
            # reverted.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS tuning_versions (
                    version_id   TEXT PRIMARY KEY,
                    target       TEXT NOT NULL,
                    from_value   TEXT,
                    to_value     TEXT NOT NULL,
                    proposed_by  TEXT,
                    rationale    TEXT,
                    state        TEXT NOT NULL DEFAULT 'proposed',
                    evidence_json TEXT,
                    created_ts   REAL NOT NULL,
                    decided_ts   REAL
                )
            """)

            self.conn.commit()

    # ── Scheduled Tasks / Reminders ───────────────────────────────────────────

    def register_scheduled_task(self, task_id: str, description: str,
                                due_at: float | None, created_at: float,
                                kind: str = "reminder") -> None:
        """Persists a new task/reminder. due_at is None for a plain to-do
        item with no specific time attached. kind is 'reminder' (default) or
        'goal' (S6 increment 2 — an autonomous goal the event bus may run)."""
        with self._lock:
            self.cursor.execute(
                """INSERT OR REPLACE INTO scheduled_tasks
                   (task_id, description, due_at, created_at, completed, completed_at, kind)
                   VALUES (?, ?, ?, ?, 0, NULL, ?)""",
                (task_id, description, due_at, created_at, kind)
            )
            self.conn.commit()

    def get_pending_scheduled_tasks(self) -> list:
        """Returns every not-yet-completed task, soonest due_at first (tasks
        with no due_at sort last, not first — an undated to-do shouldn't
        visually outrank something with an actual deadline)."""
        with self._lock:
            self.cursor.execute(
                """SELECT task_id, description, due_at, created_at
                   FROM scheduled_tasks WHERE completed = 0
                   ORDER BY (due_at IS NULL), due_at, created_at"""
            )
            rows = self.cursor.fetchall()
        return [
            {"task_id": r[0], "description": r[1], "due_at": r[2], "created_at": r[3]}
            for r in rows
        ]

    def find_pending_tasks_by_keyword(self, keyword: str) -> list:
        """Case-insensitive substring match against pending task descriptions
        — used to resolve "cancel my dentist reminder" to a specific stored
        row without requiring the user to know its internal id."""
        with self._lock:
            self.cursor.execute(
                """SELECT task_id, description, due_at, created_at
                   FROM scheduled_tasks
                   WHERE completed = 0 AND description LIKE ?
                   ORDER BY (due_at IS NULL), due_at, created_at""",
                (f"%{keyword}%",)
            )
            rows = self.cursor.fetchall()
        return [
            {"task_id": r[0], "description": r[1], "due_at": r[2], "created_at": r[3]}
            for r in rows
        ]

    def complete_scheduled_task(self, task_id: str, completed_at: float) -> None:
        """Marks a task done. Kept, not deleted, so history is inspectable."""
        with self._lock:
            self.cursor.execute(
                """UPDATE scheduled_tasks SET completed = 1, completed_at = ?
                   WHERE task_id = ?""",
                (completed_at, task_id)
            )
            self.conn.commit()

    def get_due_scheduled_tasks(self, now: float) -> list:
        """Rows whose due time has passed and that have NOT yet been notified —
        the S6 event bus's per-tick work list. A completed row, an undated row,
        and an already-notified row are all excluded."""
        with self._lock:
            self.cursor.execute(
                """SELECT task_id, description, due_at, created_at, kind
                   FROM scheduled_tasks
                   WHERE completed = 0
                     AND due_at IS NOT NULL
                     AND due_at <= ?
                     AND notified_at IS NULL
                   ORDER BY due_at, created_at""",
                (now,)
            )
            rows = self.cursor.fetchall()
        return [
            {"task_id": r[0], "description": r[1], "due_at": r[2], "created_at": r[3],
             "kind": r[4] if len(r) > 4 else "reminder"}
            for r in rows
        ]

    def mark_scheduled_task_notified(self, task_id: str, notified_at: float) -> None:
        """Stamps a row as announced so the event bus does not re-fire it. Does
        not mark it completed — the user still has to act on the reminder."""
        with self._lock:
            self.cursor.execute(
                "UPDATE scheduled_tasks SET notified_at = ? WHERE task_id = ?",
                (notified_at, task_id)
            )
            self.conn.commit()

    # ── Semantic Memory (S6 increment 1) ─────────────────────────────────────

    def add_semantic_memory(self, text: str, embedding_blob: bytes, intent: str | None,
                            target: str | None, result: str | None, ts: float,
                            plan: str | None = None) -> None:
        """Stores one embedded interaction. embedding_blob is a raw float32
        array (np.ndarray.tobytes()). plan is a JSON string of the step-shape
        for a successful multi-step run, else None (increment 2)."""
        with self._lock:
            self.cursor.execute(
                """INSERT INTO memory_semantic (text, embedding, intent, target, result, ts, plan)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (text, embedding_blob, intent, target, result, ts, plan)
            )
            self.conn.commit()

    def recent_semantic_memories(self, limit: int = 5000) -> list:
        """Newest-first rows for a brute-force similarity scan. `limit` caps the
        scan so an old, large store can't make retrieval slow."""
        with self._lock:
            self.cursor.execute(
                """SELECT text, embedding, intent, target, result, ts, plan
                   FROM memory_semantic ORDER BY id DESC LIMIT ?""",
                (limit,)
            )
            rows = self.cursor.fetchall()
        return [
            {"text": r[0], "embedding": r[1], "intent": r[2], "target": r[3],
             "result": r[4], "ts": r[5], "plan": r[6] if len(r) > 6 else None}
            for r in rows
        ]

    # ── Procedural Memory (S6) ──────────────────────────────────────────────

    def upsert_procedural_recipe(self, fingerprint: str, goal_text: str,
                                 embedding_blob: bytes, graph_json: str,
                                 ts: float) -> None:
        """Records one organic success for a plan structure. First sight
        inserts with success_count=1; a repeat bumps the count and refreshes
        goal_text / embedding / last_success_ts to the most recent phrasing."""
        with self._lock:
            self.cursor.execute(
                """INSERT INTO memory_procedural
                     (fingerprint, goal_text, embedding, graph_json,
                      success_count, failure_count, created_ts, last_success_ts)
                   VALUES (?, ?, ?, ?, 1, 0, ?, ?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                     success_count   = success_count + 1,
                     goal_text       = excluded.goal_text,
                     embedding       = excluded.embedding,
                     graph_json      = excluded.graph_json,
                     last_success_ts = excluded.last_success_ts""",
                (fingerprint, goal_text, embedding_blob, graph_json, ts, ts)
            )
            self.conn.commit()

    def bump_procedural_failure(self, fingerprint: str) -> None:
        """A replay of this recipe then failed. One failure retires it — the
        recall gate refuses any recipe with failure_count > 0 until fresh
        organic successes would re-promote a (re-fingerprinted) structure."""
        with self._lock:
            self.cursor.execute(
                "UPDATE memory_procedural SET failure_count = failure_count + 1 WHERE fingerprint = ?",
                (fingerprint,)
            )
            self.conn.commit()

    def get_procedural_recipe(self, fingerprint: str) -> dict | None:
        with self._lock:
            self.cursor.execute(
                """SELECT fingerprint, goal_text, embedding, graph_json,
                          success_count, failure_count, created_ts, last_success_ts
                   FROM memory_procedural WHERE fingerprint = ?""",
                (fingerprint,)
            )
            r = self.cursor.fetchone()
        if not r:
            return None
        return {"fingerprint": r[0], "goal_text": r[1], "embedding": r[2],
                "graph_json": r[3], "success_count": r[4], "failure_count": r[5],
                "created_ts": r[6], "last_success_ts": r[7]}

    def recent_procedural_recipes(self, limit: int = 2000) -> list:
        """Most-recently-successful recipes first, for a brute-force similarity
        scan at recall time."""
        with self._lock:
            self.cursor.execute(
                """SELECT fingerprint, goal_text, embedding, graph_json,
                          success_count, failure_count, created_ts, last_success_ts
                   FROM memory_procedural ORDER BY last_success_ts DESC LIMIT ?""",
                (limit,)
            )
            rows = self.cursor.fetchall()
        return [
            {"fingerprint": r[0], "goal_text": r[1], "embedding": r[2],
             "graph_json": r[3], "success_count": r[4], "failure_count": r[5],
             "created_ts": r[6], "last_success_ts": r[7]}
            for r in rows
        ]

    # ── World Model (S7) ──────────────────────────────────────────────────

    def add_env_state(self, ts: float, proc_hash: str, proc_count: int,
                      fg_app: str | None, fg_title: str | None,
                      procs_json: str) -> None:
        """Append one environment sample."""
        with self._lock:
            self.cursor.execute(
                """INSERT INTO env_state
                     (ts, proc_hash, proc_count, fg_app, fg_title, procs_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, proc_hash, proc_count, fg_app, fg_title, procs_json)
            )
            self.conn.commit()

    def recent_env_states(self, limit: int = 500) -> list:
        """Newest-first environment samples."""
        with self._lock:
            self.cursor.execute(
                """SELECT ts, proc_hash, proc_count, fg_app, fg_title, procs_json
                   FROM env_state ORDER BY id DESC LIMIT ?""",
                (limit,)
            )
            rows = self.cursor.fetchall()
        return [
            {"ts": r[0], "proc_hash": r[1], "proc_count": r[2],
             "fg_app": r[3], "fg_title": r[4], "procs_json": r[5]}
            for r in rows
        ]

    def prune_env_state(self, max_rows: int, max_age_seconds: float,
                        now: float | None = None) -> int:
        """Drop samples beyond the row-count cap or older than the age cap.
        Returns the number of rows removed."""
        import time as _t
        now = _t.time() if now is None else now
        with self._lock:
            before = self.cursor.execute("SELECT COUNT(*) FROM env_state").fetchone()[0]
            self.cursor.execute(
                """DELETE FROM env_state WHERE id NOT IN (
                       SELECT id FROM env_state ORDER BY id DESC LIMIT ?
                   )""",
                (max(1, max_rows),)
            )
            self.cursor.execute(
                "DELETE FROM env_state WHERE ts < ?",
                (now - max_age_seconds,)
            )
            after = self.cursor.execute("SELECT COUNT(*) FROM env_state").fetchone()[0]
            self.conn.commit()
        return before - after

    def add_capability_outcome(self, ts: float, intent: str, verified: bool,
                               failure_category: str | None = None,
                               latency_ms: float | None = None,
                               tier: str | None = None) -> None:
        """Append one capability outcome (S7 Half B)."""
        with self._lock:
            self.cursor.execute(
                """INSERT INTO capability_outcomes
                     (ts, intent, verified, failure_category, latency_ms, tier)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, intent, 1 if verified else 0, failure_category, latency_ms, tier)
            )
            self.conn.commit()

    def recent_capability_outcomes(self, intent: str | None = None,
                                   limit: int = 5000) -> list:
        """Newest-first outcomes, optionally filtered to one intent."""
        with self._lock:
            if intent is None:
                self.cursor.execute(
                    """SELECT ts, intent, verified, failure_category, latency_ms, tier
                       FROM capability_outcomes ORDER BY id DESC LIMIT ?""",
                    (limit,)
                )
            else:
                self.cursor.execute(
                    """SELECT ts, intent, verified, failure_category, latency_ms, tier
                       FROM capability_outcomes WHERE intent = ?
                       ORDER BY id DESC LIMIT ?""",
                    (intent, limit)
                )
            rows = self.cursor.fetchall()
        return [
            {"ts": r[0], "intent": r[1], "verified": bool(r[2]),
             "failure_category": r[3], "latency_ms": r[4], "tier": r[5]}
            for r in rows
        ]

    def prune_capability_outcomes(self, max_rows: int, max_age_seconds: float,
                                  now: float | None = None) -> int:
        """Drop outcomes beyond the row cap or older than the age cap. Returns
        the number removed."""
        import time as _t
        now = _t.time() if now is None else now
        with self._lock:
            before = self.cursor.execute("SELECT COUNT(*) FROM capability_outcomes").fetchone()[0]
            self.cursor.execute(
                """DELETE FROM capability_outcomes WHERE id NOT IN (
                       SELECT id FROM capability_outcomes ORDER BY id DESC LIMIT ?
                   )""",
                (max(1, max_rows),)
            )
            self.cursor.execute(
                "DELETE FROM capability_outcomes WHERE ts < ?",
                (now - max_age_seconds,)
            )
            after = self.cursor.execute("SELECT COUNT(*) FROM capability_outcomes").fetchone()[0]
            self.conn.commit()
        return before - after

    # ── Learned Skills (S8) ───────────────────────────────────────────────

    def upsert_learned_skill(self, skill_id: str, fingerprint: str,
                             skeleton_json: str, slots_json: str,
                             goal_examples_json: str,
                             postcondition_kind: str | None, n_instances: int,
                             ts: float) -> None:
        """Insert a candidate skill, or refresh its abstracted recipe +
        instance count if it is already registered. Never changes state,
        tier, origin, confidence or the timestamps of an existing row."""
        with self._lock:
            self.cursor.execute(
                """INSERT INTO learned_skills
                     (skill_id, fingerprint, skeleton_json, slots_json,
                      goal_examples_json, postcondition_kind, n_instances, created_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(skill_id) DO UPDATE SET
                     skeleton_json      = excluded.skeleton_json,
                     slots_json         = excluded.slots_json,
                     goal_examples_json = excluded.goal_examples_json,
                     n_instances        = excluded.n_instances""",
                (skill_id, fingerprint, skeleton_json, slots_json,
                 goal_examples_json, postcondition_kind, n_instances, ts),
            )
            self.conn.commit()

    def set_learned_skill_state(self, skill_id: str, state: str,
                                ts_field: str | None = None, ts: float | None = None,
                                confidence: float | None = None) -> None:
        """Move a skill to a new lifecycle state. `ts_field` (validated_ts /
        activated_ts) and `confidence` are set only when provided."""
        sets = ["state = ?"]
        params: list = [state]
        if ts_field in ("validated_ts", "activated_ts") and ts is not None:
            sets.append(f"{ts_field} = ?")
            params.append(ts)
        if confidence is not None:
            sets.append("confidence = ?")
            params.append(confidence)
        params.append(skill_id)
        with self._lock:
            self.cursor.execute(
                f"UPDATE learned_skills SET {', '.join(sets)} WHERE skill_id = ?",
                params,
            )
            self.conn.commit()

    def get_learned_skill(self, skill_id: str) -> dict | None:
        with self._lock:
            self.cursor.execute(
                "SELECT * FROM learned_skills WHERE skill_id = ?", (skill_id,)
            )
            row = self.cursor.fetchone()
            cols = [d[0] for d in self.cursor.description] if row else []
        return dict(zip(cols, row)) if row else None

    def list_learned_skills(self, state: str | None = None) -> list:
        with self._lock:
            if state is None:
                self.cursor.execute("SELECT * FROM learned_skills ORDER BY created_ts DESC")
            else:
                self.cursor.execute(
                    "SELECT * FROM learned_skills WHERE state = ? ORDER BY created_ts DESC",
                    (state,),
                )
            rows = self.cursor.fetchall()
            cols = [d[0] for d in self.cursor.description]
        return [dict(zip(cols, r)) for r in rows]

    def add_learned_skill_event(self, skill_id: str, event: str,
                                detail: str | None, ts: float) -> None:
        with self._lock:
            self.cursor.execute(
                "INSERT INTO learned_skill_events (skill_id, ts, event, detail) VALUES (?, ?, ?, ?)",
                (skill_id, ts, event, detail),
            )
            self.conn.commit()

    def learned_skill_events(self, skill_id: str) -> list:
        with self._lock:
            self.cursor.execute(
                "SELECT ts, event, detail FROM learned_skill_events WHERE skill_id = ? ORDER BY id",
                (skill_id,),
            )
            return [{"ts": r[0], "event": r[1], "detail": r[2]} for r in self.cursor.fetchall()]

    def add_learned_skill_outcome(self, skill_id: str, verified: bool, ts: float) -> None:
        with self._lock:
            self.cursor.execute(
                "INSERT INTO learned_skill_outcomes (skill_id, ts, verified) VALUES (?, ?, ?)",
                (skill_id, ts, 1 if verified else 0),
            )
            self.conn.commit()

    def recent_learned_skill_outcomes(self, skill_id: str, limit: int = 100) -> list:
        with self._lock:
            self.cursor.execute(
                """SELECT ts, verified FROM learned_skill_outcomes
                   WHERE skill_id = ? ORDER BY id DESC LIMIT ?""",
                (skill_id, limit),
            )
            return [{"ts": r[0], "verified": bool(r[1])} for r in self.cursor.fetchall()]

    # ── Self-improvement / tuning versions (S9) ───────────────────────────

    def add_tuning_version(self, version_id: str, target: str, from_value: str | None,
                           to_value: str, proposed_by: str | None, rationale: str | None,
                           ts: float) -> None:
        with self._lock:
            self.cursor.execute(
                """INSERT INTO tuning_versions
                     (version_id, target, from_value, to_value, proposed_by,
                      rationale, state, created_ts)
                   VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?)""",
                (version_id, target, from_value, to_value, proposed_by, rationale, ts),
            )
            self.conn.commit()

    def set_tuning_version_state(self, version_id: str, state: str,
                                 evidence_json: str | None = None,
                                 decided_ts: float | None = None) -> None:
        sets = ["state = ?"]
        params: list = [state]
        if evidence_json is not None:
            sets.append("evidence_json = ?")
            params.append(evidence_json)
        if decided_ts is not None:
            sets.append("decided_ts = ?")
            params.append(decided_ts)
        params.append(version_id)
        with self._lock:
            self.cursor.execute(
                f"UPDATE tuning_versions SET {', '.join(sets)} WHERE version_id = ?",
                params,
            )
            self.conn.commit()

    def get_tuning_version(self, version_id: str) -> dict | None:
        with self._lock:
            self.cursor.execute("SELECT * FROM tuning_versions WHERE version_id = ?", (version_id,))
            row = self.cursor.fetchone()
            cols = [d[0] for d in self.cursor.description] if row else []
        return dict(zip(cols, row)) if row else None

    def list_tuning_versions(self, target: str | None = None, state: str | None = None) -> list:
        q = "SELECT * FROM tuning_versions"
        clauses, params = [], []
        if target is not None:
            clauses.append("target = ?")
            params.append(target)
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_ts DESC"
        with self._lock:
            self.cursor.execute(q, params)
            rows = self.cursor.fetchall()
            cols = [d[0] for d in self.cursor.description]
        return [dict(zip(cols, r)) for r in rows]

    # ── URL Cache Methods ──────────────────────────────────────────────────────

    def save_url_template(self, platform: str, url_template: str):
        """
        Saves or updates a URL template for a given platform.
        Uses INSERT OR REPLACE to upsert the record.

        Raises ValueError if the url_template does not match the expected
        safe pattern (https:// only, must contain {query} placeholder).
        Prevents cache poisoning via malicious LLM-generated templates.

        Args:
            platform (str):     The platform identifier (e.g., 'spotify', 'youtube').
            url_template (str): The URL template string (e.g., 'https://open.spotify.com/search/{query}').
        """
        import re
        # ── Security: URL Template Sanitization (Tests 2.1-2.3 fix) ────────────
        # Only accept https:// URLs that contain the {query} placeholder.
        # Rejects: http://, file://, javascript:, data:, phishing URLs.
        SAFE_TEMPLATE_PATTERN = re.compile(
            r'^https://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%{}]+$'
        )
        if not url_template or "{query}" not in url_template:
            raise ValueError(f"[MemoryManager] Rejected: url_template must contain '{{query}}' placeholder. Got: '{url_template}'")
        if not SAFE_TEMPLATE_PATTERN.match(url_template):
            raise ValueError(f"[MemoryManager] Rejected: Unsafe url_template blocked by security policy. Got: '{url_template}'")

        with self._lock:
            self.cursor.execute(
                "INSERT OR REPLACE INTO url_cache (platform, url_template) VALUES (?, ?)",
                (platform.lower(), url_template)
            )
            self.conn.commit()
        print(f"[SRE] URL template saved: '{platform}' -> '{url_template}'")

    def get_url_template(self, platform: str) -> str | None:
        """
        Retrieves the URL template for a given platform from the cache.

        Args:
            platform (str): The platform identifier to look up.

        Returns:
            str | None: The URL template if found, otherwise None.
        """
        with self._lock:
            self.cursor.execute(
                "SELECT url_template FROM url_cache WHERE platform = ?",
                (platform.lower(),)
            )
            row = self.cursor.fetchone()
        if row:
            print(f"[SRE] URL Cache HIT: '{platform}' -> '{row[0]}'")
            return row[0]
        print(f"[SRE] URL Cache MISS: '{platform}'.")
        return None

    # ── Interaction History Methods ────────────────────────────────────────────

    def log_interaction(self, timestamp: str, intent: str, target: str | None = None,
                        result: str | None = None, platform: str | None = None):
        """
        Logs a completed intent execution to the interaction history table.

        Args:
            timestamp (str): ISO timestamp of the interaction.
            intent    (str): The Enterprise NLP Intent class name.
            target    (str): The primary target of the intent.
            result    (str): The execution result (e.g., 'Success', 'Error').
            platform  (str): Optional platform context (e.g., 'spotify').
        """
        with self._lock:
            self.cursor.execute(
                """INSERT INTO interaction_history (timestamp, intent, target, result, platform)
                   VALUES (?, ?, ?, ?, ?)""",
                (timestamp, intent, target, result, platform)
            )
            self.conn.commit()

    def get_recent_interactions(self, limit: int = 10) -> list:
        """
        Fetches the most recent interaction records.

        Args:
            limit (int): Number of records to return (default 10).

        Returns:
            list: A list of row tuples ordered by most recent first.
        """
        with self._lock:
            self.cursor.execute(
                "SELECT timestamp, intent, target, result, platform FROM interaction_history ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return self.cursor.fetchall()

    def get_context_for_prompt(self, intent_filter: str | None = None, limit: int = 5) -> str:
        """
        Retrieves recent history and formats it as a string for LLM injection.
        
        Args:
            intent_filter (str): If provided, only returns history for this intent 
                                 (e.g., 'InformationRetrievalIntent').
            limit (int): Max number of records to retrieve.
            
        Returns:
            str: Formatted context block. Returns empty string if no history found.
        """
        query = "SELECT intent, target, result FROM interaction_history"
        params: list[str | int] = []

        if intent_filter:
            query += " WHERE intent = ?"
            params.append(intent_filter)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        
        with self._lock:
            try:
                self.cursor.execute(query, params)
                rows = self.cursor.fetchall()
            except Exception as e:
                print(f"[Memory] Context retrieval fault: {e}")
                return ""
        
        if not rows:
            return ""
            
        context_lines = ["[PAST INTERACTION CONTEXT]"]
        for intent, target, result in rows:
            line = f"- {intent}: {target} -> Result: {result}"
            # Safety: Hard ceiling on line length to prevent LLM bloat
            context_lines.append(line[:150]) 
            
        # Safety: Respect total token limit (approximate via characters)
        full_context = "\n".join(context_lines)
        if len(full_context) > 1000:
            full_context = full_context[:1000] + "... [context truncated]"
            
        return full_context

    def get_cached_path(self, folder_name: str) -> str | None:
        """
        Retrieves a cached absolute path for a folder name (Fix 2.9).
        Returns None if not cached or if the cached path no longer exists.
        """
        name_lower = folder_name.strip().lower()
        with self._lock:
            self.cursor.execute(
                "SELECT absolute_path FROM path_cache WHERE folder_name = ?",
                (name_lower,)
            )
            row = self.cursor.fetchone()
        if row and os.path.exists(row[0]):
            return row[0]
        return None

    def save_cached_path(self, folder_name: str, absolute_path: str) -> None:
        """
        Persists an absolute path for a folder name (Fix 2.9).
        Thread-safe — uses the shared MemoryManager lock.
        """
        name_lower = folder_name.strip().lower()
        with self._lock:
            self.cursor.execute(
                "INSERT OR REPLACE INTO path_cache (folder_name, absolute_path) VALUES (?, ?)",
                (name_lower, absolute_path)
            )
            self.conn.commit()

    # ── Process Watch Methods (Option C: async completion supervision) ─────────

    def register_process_watch(self, watch_id: str, label: str, registered_at: float,
                               sentinel_path: str | None = None, pid: int | None = None,
                               expected_state: str | None = None) -> None:
        """
        Records a detached process whose completion cannot be observed
        synchronously. Either sentinel_path (preferred — a marker file the
        launched script writes when its body finishes) or pid (fallback — watch
        for the process to disappear) identifies completion.

        Both mechanisms exist because they suit different launch styles: a
        script SentinAL generates itself can be given a completion footer, but a
        raw user command handed to a terminal cannot, so that case can only be
        watched by process liveness.
        """
        with self._lock:
            self.cursor.execute(
                """INSERT OR REPLACE INTO process_watches
                   (watch_id, label, sentinel_path, pid, expected_state,
                    registered_at, status, resolved_at, detail)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, NULL)""",
                (watch_id, label, sentinel_path, pid, expected_state, registered_at)
            )
            self.conn.commit()

    def get_pending_watches(self) -> list:
        """Returns every unresolved watch as a list of dicts."""
        with self._lock:
            self.cursor.execute(
                """SELECT watch_id, label, sentinel_path, pid, expected_state, registered_at
                   FROM process_watches WHERE status = 'pending' ORDER BY registered_at"""
            )
            rows = self.cursor.fetchall()
        return [
            {
                "watch_id": r[0], "label": r[1], "sentinel_path": r[2],
                "pid": r[3], "expected_state": r[4], "registered_at": r[5],
            }
            for r in rows
        ]

    def resolve_process_watch(self, watch_id: str, status: str, resolved_at: float,
                              detail: str = "") -> None:
        """Marks a watch finished. status is one of: completed, failed, timed_out."""
        with self._lock:
            self.cursor.execute(
                """UPDATE process_watches
                   SET status = ?, resolved_at = ?, detail = ?
                   WHERE watch_id = ?""",
                (status, resolved_at, detail[:500], watch_id)
            )
            self.conn.commit()

    def get_process_watch(self, watch_id: str) -> dict | None:
        """Fetches a single watch by id, resolved or not. Returns None if absent."""
        with self._lock:
            self.cursor.execute(
                """SELECT watch_id, label, sentinel_path, pid, expected_state,
                          registered_at, status, resolved_at, detail
                   FROM process_watches WHERE watch_id = ?""",
                (watch_id,)
            )
            row = self.cursor.fetchone()
        if not row:
            return None
        return {
            "watch_id": row[0], "label": row[1], "sentinel_path": row[2],
            "pid": row[3], "expected_state": row[4], "registered_at": row[5],
            "status": row[6], "resolved_at": row[7], "detail": row[8],
        }

    def list_recent_process_watches(self, limit: int = 50) -> list:
        """Every pending watch (oldest first) followed by the most recently
        resolved ones, newest first, capped at `limit` total. Background-task
        polling surface: a caller wants 'what's running' before 'what finished
        a while ago'."""
        with self._lock:
            self.cursor.execute(
                """SELECT watch_id, label, sentinel_path, pid, expected_state,
                          registered_at, status, resolved_at, detail
                   FROM process_watches WHERE status = 'pending'
                   ORDER BY registered_at"""
            )
            pending = self.cursor.fetchall()
            remaining = max(0, limit - len(pending))
            resolved = []
            if remaining:
                self.cursor.execute(
                    """SELECT watch_id, label, sentinel_path, pid, expected_state,
                              registered_at, status, resolved_at, detail
                       FROM process_watches WHERE status != 'pending'
                       ORDER BY resolved_at DESC LIMIT ?""",
                    (remaining,)
                )
                resolved = self.cursor.fetchall()
        rows = list(pending[:limit]) + list(resolved)
        return [
            {
                "watch_id": r[0], "label": r[1], "sentinel_path": r[2],
                "pid": r[3], "expected_state": r[4], "registered_at": r[5],
                "status": r[6], "resolved_at": r[7], "detail": r[8],
            }
            for r in rows
        ]

    def purge_resolved_watches(self, older_than_epoch: float) -> int:
        """Deletes resolved watches older than the given epoch. Returns the count
        removed. Keeps the table from growing without bound across sessions."""
        with self._lock:
            self.cursor.execute(
                """DELETE FROM process_watches
                   WHERE status != 'pending' AND resolved_at IS NOT NULL
                     AND resolved_at < ?""",
                (older_than_epoch,)
            )
            removed = self.cursor.rowcount
            self.conn.commit()
        return removed

    def close(self):
        """Closes the database connection cleanly."""
        with self._lock:
            self.conn.close()
