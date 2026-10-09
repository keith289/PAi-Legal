"""
PAi-Legal Database Manager
Handles secure local SQLite database storage for legal matters, documents, research notes, and jurisdiction rules.
"""

import os
import sqlite3
import json
from typing import List, Dict, Any, Optional
from pathlib import Path


class LegalDatabaseManager:
    """Manager for encrypted local database operations in PAi-Legal."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            user_data_dir = Path.home() / ".pai_legal"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(user_data_dir / "pai_legal.db")
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Matters / Cases table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS matters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    case_number TEXT,
                    client_name TEXT,
                    jurisdiction TEXT,
                    status TEXT DEFAULT 'Active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Documents table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    matter_id INTEGER,
                    title TEXT NOT NULL,
                    file_path TEXT,
                    content TEXT,
                    doc_type TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (matter_id) REFERENCES matters (id) ON DELETE CASCADE
                )
            """)
            # Legal Drafts / Templates table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    matter_id INTEGER,
                    title TEXT NOT NULL,
                    content_html TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (matter_id) REFERENCES matters (id) ON DELETE CASCADE
                )
            """)
            # Jurisdictions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jurisdictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    rules_json TEXT
                )
            """)
            conn.commit()

    def create_matter(self, title: str, case_number: str = "", client_name: str = "", jurisdiction: str = "US-FED") -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO matters (title, case_number, client_name, jurisdiction) VALUES (?, ?, ?, ?)",
                (title, case_number, client_name, jurisdiction),
            )
            conn.commit()
            return cursor.lastrowid

    def list_matters(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM matters ORDER BY updated_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_matter(self, matter_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM matters WHERE id = ?", (matter_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_document(self, matter_id: int, title: str, content: str = "", file_path: str = "", doc_type: str = "general", metadata: Optional[Dict] = None) -> int:
        metadata_str = json.dumps(metadata or {})
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO documents (matter_id, title, content, file_path, doc_type, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                (matter_id, title, content, file_path, doc_type, metadata_str),
            )
            conn.commit()
            return cursor.lastrowid

    def list_documents(self, matter_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if matter_id:
                cursor.execute("SELECT * FROM documents WHERE matter_id = ? ORDER BY created_at DESC", (matter_id,))
            else:
                cursor.execute("SELECT * FROM documents ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def add_draft(self, matter_id: int, title: str, content_html: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO drafts (matter_id, title, content_html) VALUES (?, ?, ?)",
                (matter_id, title, content_html),
            )
            conn.commit()
            return cursor.lastrowid

    def get_drafts(self, matter_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM drafts WHERE matter_id = ? ORDER BY updated_at DESC", (matter_id,))
            return [dict(row) for row in cursor.fetchall()]
