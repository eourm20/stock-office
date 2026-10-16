"""Regression: a worker log once contained an OpenDART key from httpx's request-URL log line."""

import io
import logging
from collections.abc import Iterator

import pytest

from stock_office.logging_setup import install_log_redaction

KEY = "f0e1d2c3b4a5968778695a4b3c2d1e0f12345678"
URL = (f"https://opendart.fss.or.kr/api/list.json?crtfc_key={KEY}"
       "&corp_code=00126380&bgn_de=20260916")


@pytest.fixture
def captured() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    install_log_redaction()
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def test_httpx_request_lines_are_suppressed(captured: io.StringIO) -> None:
    logging.getLogger("httpx").info('HTTP Request: GET %s "HTTP/1.1 200 OK"', URL)
    assert captured.getvalue() == ""


def test_any_logger_secret_is_redacted(captured: io.StringIO) -> None:
    logging.getLogger("tradingagents.something").warning("retrying %s", URL)
    logging.getLogger("x").error("bad key sk-ABCDEFGHIJKLMNOPQRSTUV")
    out = captured.getvalue()
    assert KEY not in out and "sk-ABCDEFGHIJ" not in out
    assert "[REDACTED]" in out and "corp_code=00126380" in out  # non-secret context kept
