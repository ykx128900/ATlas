"""
SQLite persistence layer for ATLAS.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Dict, List, Optional


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                entry_price REAL,
                size INTEGER,
                outcome TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS intelligence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                kimi_analysis_text TEXT,
                raw_transcript_summary TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.commit()


def get_state(db_path: str, key: str) -> Optional[str]:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_state WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None


def set_state(db_path: str, key: str, value: str) -> None:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO system_state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        conn.commit()


def load_state_dict(db_path: str) -> Dict[str, str]:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM system_state")
        rows = cur.fetchall()
        return {row["key"]: row["value"] for row in rows}


def insert_trade(db_path: str, symbol: str, entry_price: float, size: int, outcome: Optional[str] = None) -> int:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO trades(symbol, entry_price, size, outcome) VALUES(?, ?, ?, ?)",
            (symbol, entry_price, size, outcome)
        )
        conn.commit()
        return cur.lastrowid


def update_trade_outcome(db_path: str, trade_id: int, outcome: str) -> None:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE trades SET outcome = ? WHERE id = ?", (outcome, trade_id))
        conn.commit()


def insert_intelligence(db_path: str, symbol: str, kimi_analysis_text: str, raw_transcript_summary: str) -> int:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO intelligence(symbol, kimi_analysis_text, raw_transcript_summary) VALUES(?, ?, ?)",
            (symbol, kimi_analysis_text, raw_transcript_summary)
        )
        conn.commit()
        return cur.lastrowid


def load_all_trades(db_path: str) -> List[Dict]:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, symbol, entry_price, size, outcome FROM trades ORDER BY id ASC")
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def _table_empty(db_path: str, table: str) -> bool:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) as count FROM {table}")
        row = cur.fetchone()
        return (row["count"] == 0) if row else True


def migrate_json_if_needed(db_path: str, state_path: str, history_path: str) -> None:
    """
    Idempotent migration: migrate state/trades independently and mark completion.
    """
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_state WHERE key = ?", ("migration_v1_completed",))
        guard_row = cur.fetchone()
        if guard_row and guard_row["value"] == "true":
            return

        cur.execute("SELECT COUNT(*) as count FROM system_state WHERE key != ?", ("migration_v1_completed",))
        state_count = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM trades")
        trades_count = cur.fetchone()["count"]

        # Migrate state only if empty.
        if state_count == 0 and os.path.exists(state_path):
            try:
                with open(state_path, "r") as f:
                    state = json.load(f)
                if isinstance(state, dict):
                    for k, v in state.items():
                        cur.execute(
                            "INSERT INTO system_state(key, value) VALUES(?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (k, json.dumps(v))
                        )
            except Exception:
                pass

        # Migrate trade history only if empty.
        if trades_count == 0 and os.path.exists(history_path):
            try:
                with open(history_path, "r") as f:
                    history = json.load(f)
                if isinstance(history, list):
                    for item in history:
                        symbol = item.get("symbol", "")
                        entry_price = item.get("entry_price", 0.0) or item.get("price", 0.0) or 0.0
                        size = item.get("size")
                        if size is None:
                            size = item.get("contracts", 0) or 0
                        outcome = item.get("outcome") or item.get("exit_reason")
                        if symbol:
                            cur.execute(
                                "INSERT INTO trades(symbol, entry_price, size, outcome) VALUES(?, ?, ?, ?)",
                                (symbol, float(entry_price), int(size), outcome)
                            )
            except Exception:
                pass

        cur.execute(
            "INSERT INTO system_state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("migration_v1_completed", "true")
        )
        conn.commit()
