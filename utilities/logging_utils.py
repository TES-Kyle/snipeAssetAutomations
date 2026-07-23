"""Shared logging configuration for Asset Automations.

This module configures:
  - a rotating file handler for automations logs
  - an optional stream handler for long-running scripts
  - an optional queue handler for UI log windows
It also exposes a settings loader so log level updates can be applied at runtime.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from typing import Optional
from utilities.settings import get_settings as _load_settings

logger = logging.getLogger(__name__)

_CONFIGURED = False
_CURRENT_LEVEL = logging.DEBUG

UTILITIES_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.dirname(UTILITIES_DIR)
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE_NAME = "automations.log"


class QueueLogHandler(logging.Handler):
    """Logging handler that writes formatted messages to a queue."""

    def __init__(self, log_queue):
        """Initialize the handler with the target queue."""
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        """Format and enqueue the log record without raising."""
        try:
            msg = self.format(record)
            self._queue.put(msg)
        except Exception:
            # Avoid raising from logging to prevent recursive failures.
            pass


class StderrStreamHandler(logging.StreamHandler):
    """StreamHandler writing to stderr — ensures launcher captures logs in launch.log."""
    pass


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file handler that fsyncs on error-level records."""

    def emit(self, record: logging.LogRecord) -> None:
        """Write the record and fsync if it is error-level or higher."""
        super().emit(record)
        if record.levelno >= logging.ERROR and self.stream:
            try:
                self.flush()
                os.fsync(self.stream.fileno())
            except Exception:
                pass


def _resolve_log_level(level_name: Optional[str]) -> int:
    """Resolve a log level name to a logging level, defaulting to DEBUG.

    Args:
        level_name: String level name (DEBUG/INFO/WARNING/ERROR/CRITICAL).

    Returns:
        logging level constant.
    """
    # Normalize the level name before mapping to constants.
    name = str(level_name or "DEBUG").strip().upper()
    mapping = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
    }
    resolved = mapping.get(name, logging.DEBUG)
    logger.debug("_resolve_log_level: level_name=%s resolved=%s", level_name, logging.getLevelName(resolved))
    return resolved


def _handler_exists(log: logging.Logger, handler_type: type) -> bool:
    """Return True if the logger already has a handler of the exact given type."""
    result = any(type(handler) is handler_type for handler in log.handlers)
    logger.debug("_handler_exists: handler_type=%s exists=%s", handler_type.__name__, result)
    return result


def _update_handler_levels(log: logging.Logger, level: int) -> None:
    """Update levels on existing handlers to reflect current settings.

    Args:
        log: Logger whose handlers should be updated.
        level: New logging level.
    """
    logger.debug("_update_handler_levels: updating handlers to level=%s", logging.getLevelName(level))
    # Apply the new level across supported handler types.
    updated = 0
    for handler in log.handlers:
        if isinstance(handler, (logging.handlers.RotatingFileHandler, logging.StreamHandler, QueueLogHandler)):
            handler.setLevel(level)
            updated += 1
    logger.debug("_update_handler_levels: updated %s handlers", updated)


def configure_logging(log_to_console: bool = False, log_queue=None) -> None:
    """Configure root logging for the app.

    Args:
        log_to_console: If True, also log to stderr for long-running scripts.
        log_queue: Optional queue to mirror logs into (e.g., UI log window).
    """
    global _CONFIGURED, _CURRENT_LEVEL
    # Load current settings so log level changes apply immediately.
    settings = _load_settings()
    # Resolve the effective logging level from settings.
    level = _resolve_log_level(settings.get("logLevel"))

    # Always set root logger to DEBUG; handlers control effective level.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Use a consistent timestamped formatter for all handlers.
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    # Configure file handler only once to avoid duplicates.
    if not _CONFIGURED:
        # Ensure the logs directory exists before creating file handlers.
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, LOG_FILE_NAME)
        file_handler = SafeRotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Always mirror to stderr so the macOS launcher script captures logs in launch.log.
        stderr_handler = StderrStreamHandler()
        stderr_handler.setLevel(level)
        stderr_handler.setFormatter(formatter)
        root_logger.addHandler(stderr_handler)

        _CONFIGURED = True
        _CURRENT_LEVEL = level
        logger.info("configure_logging: logging initialized level=%s log_path=%s", logging.getLevelName(level), log_path)
    elif level != _CURRENT_LEVEL:
        logger.debug("configure_logging: updating handler levels old=%s new=%s", logging.getLevelName(_CURRENT_LEVEL), logging.getLevelName(level))
        _update_handler_levels(root_logger, level)
        _CURRENT_LEVEL = level
    else:
        logger.debug("configure_logging: already configured at level=%s", logging.getLevelName(level))

    # Optionally mirror logs to stderr for CLI scripts.
    if log_to_console and not _handler_exists(root_logger, logging.StreamHandler):
        logger.debug("configure_logging: adding console StreamHandler")
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
    elif log_to_console:
        logger.debug("configure_logging: console handler already present, updating level")
        _update_handler_levels(root_logger, level)

    # Optionally mirror logs to a UI queue for display.
    if log_queue is not None and not _handler_exists(root_logger, QueueLogHandler):
        logger.debug("configure_logging: adding QueueLogHandler for UI display")
        queue_handler = QueueLogHandler(log_queue)
        queue_handler.setLevel(level)
        queue_handler.setFormatter(formatter)
        root_logger.addHandler(queue_handler)
    elif log_queue is not None:
        logger.debug("configure_logging: queue handler already present, updating level")
        _update_handler_levels(root_logger, level)
