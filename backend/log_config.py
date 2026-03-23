"""
Centralised structlog configuration for AleXiona.

Call configure_logging() once at startup (main.py).
All modules then do:

    import structlog
    log = structlog.get_logger(__name__)

    log.info("claim_created", claim_id=cid, session_id=sid, source="patient_report")
    log.error("db_write_failed",  error=str(e), session_id=sid)

Output format
    Development (LOG_FORMAT=text, default): human-readable coloured output
    Production  (LOG_FORMAT=json):          one JSON object per line
"""

import logging
import os
import sys
import structlog


def configure_logging() -> None:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "text").lower()   # "text" | "json"

    # ── shared processors ──────────────────────────────────────────────────────
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        # Production: newline-delimited JSON — ready for log aggregators
        renderer = structlog.processors.JSONRenderer()
    else:
        # Development: coloured, human-readable
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    # Quieten noisy third-party loggers
    for noisy in ("neo4j", "httpx", "openai", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
