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
