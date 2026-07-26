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

    def get_url_template(self, platform: str) -> str:
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
        params = []
        
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

    def get_cached_path(self, folder_name: str) -> str:
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

    def close(self):
        """Closes the database connection cleanly."""
        with self._lock:
            self.conn.close()
