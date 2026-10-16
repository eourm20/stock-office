"""Process-wide log hygiene: no secrets in log output.

OpenDART takes its key as a query parameter, and httpx logs every request URL at INFO,
so without this a worker log contains `crtfc_key=<key>`. Two layers:
1. HTTP client loggers are raised to WARNING (request URLs are never logged).
2. Every handler gets a filter that redacts secret patterns from any record that slips through.
"""

from __future__ import annotations

import logging

from stock_office.events.sanitize import redact_text

_NOISY_HTTP_LOGGERS = ("httpx", "httpcore", "urllib3", "openai._base_client")


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_text(message, limit=10_000)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def install_log_redaction(*loggers: logging.Logger) -> None:
    for name in _NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    targets = [logging.getLogger(), *loggers]
    for logger in targets:
        for handler in logger.handlers:
            if not any(isinstance(f, RedactSecretsFilter) for f in handler.filters):
                handler.addFilter(RedactSecretsFilter())
