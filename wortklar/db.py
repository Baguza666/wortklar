"""
Database connection, schema, and metadata operations for Wortklar.
"""

import json
import os
import sqlite3
from typing import Optional, Dict, Any, List

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wortklar.db")


def get_db_connection(db_path: str = DEFAULT_DB_PATH, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection to the SQLite database with row factory and pragmas configured."""
    if read_only and not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file does not exist: {db_path}")

    if read_only:
        # Open in SQLite URI read-only mode.
        # mode=ro prevents writes; query_only pragma prevents internal modifications.
        # Cache size is capped at 16MB (-16000) for safe memory usage on Render Free (512MB RAM).
        abs_path = os.path.abspath(db_path)
        uri = f"file:{abs_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA cache_size = -16000")
        return conn

    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")  # 64 MB
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all required tables and indexes."""
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headword TEXT NOT NULL,
            part_of_speech TEXT NOT NULL,
            gender TEXT,
            article TEXT,
            source_edition TEXT NOT NULL,
            source_url TEXT,
            raw_tags TEXT,
            grammar_data TEXT,
            etymology_number INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS senses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
            sense_order INTEGER NOT NULL,
            gloss_en TEXT,
            gloss_de TEXT,
            tags TEXT,
            examples TEXT
        );

        CREATE TABLE IF NOT EXISTS forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form TEXT NOT NULL,
            lower_form TEXT NOT NULL,
            entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
            form_type TEXT,
            tags TEXT,
            article TEXT
        );

        CREATE TABLE IF NOT EXISTS search_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL,
            lower_term TEXT NOT NULL,
            folded_term TEXT NOT NULL,
            entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
            is_lemma INTEGER NOT NULL DEFAULT 1,
            form_label TEXT,
            rank_priority INTEGER NOT NULL DEFAULT 1,
            preview TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_entries_headword ON entries(headword);
        CREATE INDEX IF NOT EXISTS idx_entries_pos ON entries(part_of_speech);
        CREATE INDEX IF NOT EXISTS idx_senses_entry ON senses(entry_id);
        CREATE INDEX IF NOT EXISTS idx_forms_form ON forms(form);
        CREATE INDEX IF NOT EXISTS idx_forms_lower ON forms(lower_form);
        CREATE INDEX IF NOT EXISTS idx_forms_entry ON forms(entry_id);
        CREATE INDEX IF NOT EXISTS idx_search_term ON search_index(term);
        CREATE INDEX IF NOT EXISTS idx_search_lower ON search_index(lower_term);
        CREATE INDEX IF NOT EXISTS idx_search_folded ON search_index(folded_term);
        CREATE INDEX IF NOT EXISTS idx_search_entry ON search_index(entry_id);
        """)


def get_metadata(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Retrieve all metadata key-values as a dictionary."""
    try:
        cur = conn.execute("SELECT key, value FROM metadata")
        rows = cur.fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                result[r["key"]] = r["value"]
        return result
    except sqlite3.OperationalError:
        return {}


def set_metadata(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Store or update a metadata item."""
    val_str = json.dumps(value) if not isinstance(value, str) else value
    with conn:
        conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, val_str))


def check_integrity(conn: sqlite3.Connection, quick: bool = False) -> bool:
    """Run SQLite integrity check (or fast quick_check)."""
    cmd = "PRAGMA quick_check" if quick else "PRAGMA integrity_check"
    cur = conn.execute(cmd)
    row = cur.fetchone()
    return bool(row and row[0] == "ok")

