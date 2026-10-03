"""Structured logging utilities using structlog.

All log entries are JSON-formatted and include a trace_id and timestamp.
Never log secrets, tokens, or raw data contents.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog for structured JSON output.

    Call once at application startup. Subsequent calls are no-ops due to
    structlog's configuration being global.

    Parameters
    ----------
    level:
        Root log level (DEBUG, INFO, WARNING, ERROR).
    json_output:
        If True, output JSON lines. If False, pretty-print for development.
    """
    processors: list[Any]
    if json_output:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a bound logger with the given component name."""
    return structlog.get_logger(component=name)  # type: ignore[return-value]
