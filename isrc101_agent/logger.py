"""Simple logging helpers for isrc101-agent."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Union

__all__ = ["setup_logger", "get_logger"]

DEFAULT_LOG_FILE = Path("~/.isrc101-agent/logs/agent.log").expanduser()
CONSOLE_FORMAT = "[%(levelname).1s] %(message)s"
FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5MB
LOG_BACKUP_COUNT = 3


def setup_logger(
    name: str,
    verbose: bool = False,
    log_file: Union[str, Path, bool, None] = None,
) -> logging.Logger:
    """Configure and return a logger for this project.

    Args:
        name: Logger name, usually ``__name__`` from the caller module.
        verbose: ``True`` enables INFO logs; ``False`` keeps output at WARNING+.
        log_file: File logging target.
            - ``None`` or ``True``: use ``~/.isrc101-agent/logs/agent.log``
            - ``False``: disable file logging
            - ``str``/``Path``: use a custom log file path
    """
    logger = logging.getLogger(name)
    level = logging.INFO if verbose else logging.WARNING

    # Reconfigure safely if setup_logger is called more than once.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(level)
    logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    logger.addHandler(console_handler)

    log_path = _resolve_log_path(log_file)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        logger.addHandler(file_handler)

    # Keep third-party libraries quiet unless they emit warnings or errors.
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a logger by name without changing its configuration."""
    return logging.getLogger(name)


def _resolve_log_path(log_file: Union[str, Path, bool, None]) -> Path | None:
    """Translate ``log_file`` input to a concrete path or disable file logging."""
    if log_file is False:
        return None
    if log_file is None or log_file is True:
        return DEFAULT_LOG_FILE
    return Path(log_file).expanduser()
