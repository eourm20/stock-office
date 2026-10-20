"""The shared connection survives simultaneous use from many threads (API request threads)."""

from __future__ import annotations

import threading
from pathlib import Path

from stock_office.db import connect, transaction


def test_many_threads_read_and_write_one_connection(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            for i in range(40):
                with transaction(conn):
                    conn.execute("INSERT INTO company_settings (key, value) VALUES (?, ?)",
                                 (f"k{n}-{i}", "v"))
                rows = list(conn.execute("SELECT key, value FROM company_settings"))
                assert rows and conn.execute("SELECT COUNT(*) FROM company_settings").fetchone()[0]
        except BaseException as exc:   # noqa: BLE001 - any failure fails the test
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert conn.execute("SELECT COUNT(*) FROM company_settings WHERE key LIKE 'k%'").fetchone()[0] \
        == 8 * 40


def test_results_behave_like_cursors(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    cur = conn.execute("SELECT key FROM company_settings ORDER BY key")
    assert cur.fetchone() is not None   # the initial auto_approve row
    assert cur.fetchall() == []
    ins = conn.execute("INSERT INTO company_settings (key, value) VALUES ('x', 'y')")
    assert ins.rowcount == 1 and ins.lastrowid
    assert conn.execute("SELECT value FROM company_settings WHERE key='none'").fetchone() is None
