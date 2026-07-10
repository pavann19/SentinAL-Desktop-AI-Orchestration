# capability_registry.py
# SQLite-backed Registry for OS Capabilities, Apps, and Web Routes.

import sqlite3
import os
import threading

from config.paths import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "capabilities.db")

class CapabilityRegistry:
    """
    Manages a persistent registry of what SentinAL is capable of.
    Supports deterministic mapping of names to executable values or URLs.
    """
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    name  TEXT PRIMARY KEY,
                    type  TEXT NOT NULL,
                    value TEXT NOT NULL
                )
            """)
            self.conn.commit()

    def seed_defaults(self, app_map: dict):
        """
        Idempotent bootstrap. Seeds the DB with default application mappings.
        Uses INSERT OR IGNORE to prevent duplicate entries on reboot.
        """
        with self._lock:
            # Prepare standard app mappings
            data = [(name, "application", val) for name, val in app_map.items()]
            
            # Add some default web routes
            data.extend([
                ("youtube", "web", "https://youtube.com"),
                ("google", "web", "https://google.com"),
                ("github", "web", "https://github.com"),
                ("chatgpt", "web", "https://chat.openai.com")
            ])
            
            self.conn.executemany(
                "INSERT OR IGNORE INTO capabilities (name, type, value) VALUES (?, ?, ?)",
                data
            )
            self.conn.commit()
            print(f"[Registry] Seeded {len(data)} capabilities into DB.")

    def lookup(self, name: str):
        """Returns (type, value) for a matched capability or None."""
        name_clean = name.strip().lower()
        with self._lock:
            cursor = self.conn.execute(
                "SELECT type, value FROM capabilities WHERE name = ?", 
                (name_clean,)
            )
            return cursor.fetchone()

    def add_capability(self, name: str, cap_type: str, value: str):
        """Enables runtime expansion of OS capabilities."""
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO capabilities (name, type, value) VALUES (?, ?, ?)",
                (name.strip().lower(), cap_type, value)
            )
            self.conn.commit()
            print(f"[Registry] Registered: {name} ({cap_type}) -> {value}")

    def get_by_type(self, cap_type: str):
        """Retrieves all capabilities of a specific type (e.g., 'application')."""
        with self._lock:
            cursor = self.conn.execute(
                "SELECT name, value FROM capabilities WHERE type = ?", 
                (cap_type,)
            )
            return dict(cursor.fetchall())

    def close(self):
        self.conn.close()

# Singleton Instance
registry = CapabilityRegistry()
