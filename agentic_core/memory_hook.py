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
            self.conn.commit()

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
