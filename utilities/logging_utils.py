"""Shared logging configuration for Asset Automations.

This module configures:
  - a rotating file handler for automations logs
  - an optional stream handler for long-running scripts
  - an optional queue handler for UI log windows
It also exposes a settings loader so log level updates can be applied at runtime.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from typing import Optional

_CONFIGURED = False
_CURRENT_LEVEL = logging.DEBUG

UTILITIES_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.dirname(UTILITIES_DIR)
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE_NAME = "automations.log"
SETTINGS_PATH = os.path.join(UTILITIES_DIR, "settings.json")
DEFAULTS_PATH = os.path.join(UTILITIES_DIR, "defaultSettings.json")


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


def _safe_read_json(path: str) -> dict:
    """Read a JSON file and return a dict, or {} on failure.

    Args:
        path: JSON file path to read.

    Returns:
        Parsed dict or empty dict when read/parse fails.
    """
    try:
        # Read JSON from disk; return empty dict on any error.
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception:
        return {}


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
    return mapping.get(name, logging.DEBUG)


def _load_settings() -> dict:
    """Load settings.json over defaults, returning a merged dict.

    Returns:
        Merged settings dict with defaults overridden by settings.json.
    """
    # Start with defaults, then override with settings.json.
    settings = {}
    settings.update(_safe_read_json(DEFAULTS_PATH))
    settings.update(_safe_read_json(SETTINGS_PATH))
    return settings


def get_settings() -> dict:
    """Return merged settings.json/defaultSettings.json for callers.

    Returns:
        Combined settings dict (settings.json overrides defaults).
    """
    return _load_settings()


def _handler_exists(logger: logging.Logger, handler_type: type) -> bool:
    """Return True if the logger already has a handler of the exact given type."""
    return any(type(handler) is handler_type for handler in logger.handlers)


def _update_handler_levels(logger: logging.Logger, level: int) -> None:
    """Update levels on existing handlers to reflect current settings.

    Args:
        logger: Logger whose handlers should be updated.
        level: New logging level.
    """
    # Apply the new level across supported handler types.
    for handler in logger.handlers:
        if isinstance(handler, (logging.handlers.RotatingFileHandler, StderrStreamHandler, logging.StreamHandler, QueueLogHandler)):
            handler.setLevel(level)


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
    elif level != _CURRENT_LEVEL:
        _update_handler_levels(root_logger, level)
        _CURRENT_LEVEL = level

    # Optionally mirror logs to stderr for CLI scripts.
    if log_to_console and not _handler_exists(root_logger, logging.StreamHandler):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
    elif log_to_console:
        _update_handler_levels(root_logger, level)

    # Optionally mirror logs to a UI queue for display.
    if log_queue is not None and not _handler_exists(root_logger, QueueLogHandler):
        queue_handler = QueueLogHandler(log_queue)
        queue_handler.setLevel(level)
        queue_handler.setFormatter(formatter)
        root_logger.addHandler(queue_handler)
    elif log_queue is not None:
        _update_handler_levels(root_logger, level)
