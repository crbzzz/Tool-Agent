"""Central logging configuration.

Goals:
- Safe defaults for local dev + production
- Optional rotating file logs (disabled unless LOG_TO_FILE=true)

Env:
- LOG_LEVEL (default: INFO)
- LOG_TO_FILE (default: false)
- LOG_DIR (default: .secrets/logs)
- LOG_FILE (default: app.log)
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging() -> None:
    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")

    # Ensure we have at least one stream handler.
    has_stream = any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    if not has_stream:
        stream = logging.StreamHandler()
        stream.setLevel(level)
        stream.setFormatter(fmt)
        root.addHandler(stream)

    # Optional rotating file logs.
    if (os.getenv("LOG_TO_FILE") or "").strip().lower() in {"1", "true", "yes", "y"}:
        log_dir = Path(os.getenv("LOG_DIR") or ".secrets/logs").resolve()
        log_file = (os.getenv("LOG_FILE") or "app.log").strip() or "app.log"
        log_dir.mkdir(parents=True, exist_ok=True)

        target = str(log_dir / log_file)
        has_file = any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == target for h in root.handlers)
        if not has_file:
            fh = RotatingFileHandler(
                filename=target,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            fh.setLevel(level)
            fh.setFormatter(fmt)
            root.addHandler(fh)
