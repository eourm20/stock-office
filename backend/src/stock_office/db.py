"""SQLite store for office operations: the CEO inbox and its approval plans now; jobs, watchlist and
the paper ledger in later steps. One file, WAL mode, UTC ISO timestamps, money as Decimal text.

Analysis runs keep their file storage (runs/repository.py); this database holds what needs
transactions and queries across runs. Migrations are append-only and tracked by `user_version`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: inbox (reports and approval requests), approval plans, CEO decisions
    """
    CREATE TABLE inbox_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK (kind IN
            ('approval', 'daily', 'adhoc', 'execution', 'closing', 'research')),
        run_id TEXT,
        instrument_id TEXT,
        title TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL CHECK (status IN
            ('PENDING', 'APPROVED', 'REJECTED', 'DEFERRED', 'EXPIRED', 'INFO')),
        expires_at TEXT,
        read_at TEXT,
        dedupe_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        decided_at TEXT
    );
    CREATE INDEX inbox_status ON inbox_items (status, created_at);
    CREATE TABLE plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL UNIQUE REFERENCES inbox_items (id),
        run_id TEXT NOT NULL UNIQUE,
        instrument_id TEXT NOT NULL,
        side TEXT NOT NULL,
        body TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        valid_until TEXT
    );
    CREATE TABLE approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES inbox_items (id),
        action TEXT NOT NULL CHECK (action IN ('approve', 'reject', 'defer')),
        comment TEXT NOT NULL DEFAULT '',
        client_request_id TEXT NOT NULL UNIQUE,
        decided_at TEXT NOT NULL
    );
    """,
]


def db_path(data_dir: Path) -> Path:
    return Path(data_dir) / "office.db"


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open (and migrate) the office database. Callers own the connection."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path(data_dir), timeout=5, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        with transaction(conn):
            # executescript() would commit the surrounding transaction; run statements one by one.
            for statement in (s.strip() for s in sql.split(";")):
                if statement:
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version={number}")
    return len(MIGRATIONS)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
