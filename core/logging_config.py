"""Centralized logging configuration for TradeScanner."""
import logging
import sys
from typing import Optional, Dict


def setup_logging(
    level: str = "INFO",
    component_filters: Optional[Dict[str, str]] = None,
    log_file: Optional[str] = None,
    verbose: bool = False
) -> None:
    """Centralized logging configuration.

    Replaces ad-hoc logging.basicConfig() calls across entry points.

    Args:
        level: Root log level (default "INFO")
        component_filters: Per-component overrides, e.g. {"core.screener": "DEBUG"}
        log_file: Optional file path for file logging
        verbose: If True, include more detail in log format
    """
    fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    if verbose:
        fmt = '%(asctime)s - %(name)s - %(levelname)s [%(filename)s:%(lineno)d] - %(message)s'

    # Reset any existing handlers to avoid duplicates on re-init
    root = logging.getLogger()
    root.handlers.clear()

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Apply per-component overrides
    if component_filters:
        for component, lvl in component_filters.items():
            logging.getLogger(component).setLevel(
                getattr(logging, lvl.upper(), logging.INFO)
            )

    # Add file handler if requested
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(fmt))
        root.addHandler(file_handler)
