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
    # 2: company settings, the paper book (KRW cash ledger, simulated orders and fills, positions)
    # and one row per settled exchange session
    """
    CREATE TABLE company_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT
    );
    INSERT INTO company_settings (key, value) VALUES ('auto_approve', '1');
    CREATE TABLE paper_cash (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount_krw TEXT NOT NULL,
        reason TEXT NOT NULL,
        ref TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    );
    CREATE TABLE paper_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER REFERENCES inbox_items (id),
        parent_id INTEGER REFERENCES paper_orders (id),
        instrument_id TEXT NOT NULL,
        market TEXT NOT NULL,
        currency TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('entry', 'take_profit', 'stop', 'exit')),
        side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
        qty TEXT NOT NULL,
        price TEXT,
        reserved_krw TEXT NOT NULL DEFAULT '0',
        status TEXT NOT NULL CHECK (status IN
            ('OPEN', 'FILLED', 'CANCELLED', 'EXPIRED', 'REJECTED')),
        reason TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '{}',
        active_from TEXT NOT NULL,
        valid_until TEXT,
        idempotency_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        closed_at TEXT
    );
    CREATE INDEX paper_orders_open ON paper_orders (status, market, active_from);
    CREATE TABLE paper_fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL UNIQUE REFERENCES paper_orders (id),
        session TEXT NOT NULL,
        price TEXT NOT NULL,
        qty TEXT NOT NULL,
        gross TEXT NOT NULL,
        fee TEXT NOT NULL,
        tax TEXT NOT NULL,
        fx TEXT NOT NULL,
        amount_krw TEXT NOT NULL,
        realized_krw TEXT,
        rule TEXT NOT NULL,
        filled_at TEXT NOT NULL
    );
    CREATE TABLE paper_positions (
        instrument_id TEXT PRIMARY KEY,
        market TEXT NOT NULL,
        currency TEXT NOT NULL,
        qty TEXT NOT NULL,
        avg_price TEXT NOT NULL,
        cost_krw TEXT NOT NULL,
        last_price TEXT NOT NULL,
        last_fx TEXT NOT NULL,
        marked_session TEXT NOT NULL,
        opened_at TEXT NOT NULL
    );
    CREATE TABLE settle_runs (
        market TEXT NOT NULL,
        session TEXT NOT NULL,
        status TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        nav_krw TEXT NOT NULL,
        cash_krw TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (market, session)
    );
    """,
    # 3: CEO opinions on auto-approved requests, kept apart from the decision that booked the order
    """
    ALTER TABLE approvals ADD COLUMN kind TEXT NOT NULL DEFAULT 'decision'
        CHECK (kind IN ('decision', 'opinion'))
    """,
    # 4: phone notifications: the owner's push subscriptions and an outbox (one row per event)
    """
    CREATE TABLE push_subscriptions (
        endpoint TEXT PRIMARY KEY,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_sent_at TEXT,
        failures INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dedupe_key TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL CHECK (category IN ('meeting_start', 'meeting_end', 'approval')),
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        sent_at TEXT,
        outcome TEXT
    )
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
