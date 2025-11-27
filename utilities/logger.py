# utilities/logger.py
"""
Centralized logging configuration for NHL Prediction Pipeline.

Usage:
    from utilities.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Pipeline started")
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


# Default log level from environment
DEFAULT_LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# Log directory
LOG_DIR = Path(__file__).parent.parent / 'data' / 'logs'


def get_logger(name: str, level: str = None) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically __name__)
        level: Log level override (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Only configure if not already set up
    if not logger.handlers:
        log_level = getattr(logging, level or DEFAULT_LOG_LEVEL, logging.INFO)
        logger.setLevel(log_level)

        # Console handler with formatting
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)

        # Format: [2025-11-25 10:30:45] [INFO] [nhl_api] Message here
        console_format = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        # File handler (optional, only if LOG_DIR is writable)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                LOG_DIR / 'nhl_pipeline.log',
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5
            )
            file_handler.setLevel(logging.DEBUG)  # Always log everything to file
            file_format = logging.Formatter(
                '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_format)
            logger.addHandler(file_handler)
        except (OSError, PermissionError):
            # Skip file logging if we can't write
            pass

        # Don't propagate to root logger
        logger.propagate = False

    return logger


def configure_root_logging(level: str = None):
    """
    Configure the root logger for the entire application.

    Call this once at application startup.
    """
    log_level = getattr(logging, level or DEFAULT_LOG_LEVEL, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[logging.StreamHandler(sys.stdout)]
    )


# Convenience function for quick setup
def setup_logging(level: str = None):
    """Set up logging for the application."""
    configure_root_logging(level)
    return get_logger('nhl_pipeline')
