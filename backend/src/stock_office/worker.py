"""Background worker. Long runs never execute inside an HTTP request.

    python -m stock_office.worker            # poll forever
    python -m stock_office.worker --once     # drain the queue and exit
"""

from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from stock_office.config import get_settings
from stock_office.runs.service import RunService
from stock_office.wiring import build_service

log = logging.getLogger("stock_office.worker")


class ThreadDispatcher:
    """In-process dispatcher for dev: one background thread executes runs in FIFO order."""

    def __init__(self, service: RunService) -> None:
        self.service = service
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="run-worker")

    def submit(self, run_id: str) -> None:
        self.pool.submit(self.service.execute, run_id)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True)


def drain(service: RunService) -> int:
    count = 0
    for run_id in service.repo.queued_run_ids():
        run = service.execute(run_id)
        log.info("run %s -> %s", run.id, run.status.value)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = build_service(get_settings())
    while True:
        drain(service)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
