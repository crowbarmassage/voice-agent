"""Structured JSON logging with correlation IDs.

Every log entry carries: work_item_id, call_sid, session_id (when available).
Uses structlog for JSON output with consistent field ordering.

Usage:
    from voice_agent.logging import get_logger

    log = get_logger()
    log.info("call_placed", call_sid="CA123", payor="UHC")

    # Bind correlation IDs for a session
    log = get_logger().bind(
        session_id="sess_abc",
        work_item_id="wi_123",
        call_sid="CA456",
    )
    log.info("ivr_navigated", dtmf="1")
"""
from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, json: bool = True, level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for the application.

    Call once at startup. json=True for production, False for dev (console).
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger, optionally named."""
    return structlog.get_logger(name)
