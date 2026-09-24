"""Bounded in-memory logging handler used for mission-control log tails."""

from __future__ import annotations

from collections import deque
import logging
import threading


class LogRingHandler(logging.Handler):
    """Keep the most recent formatted log records in a bounded ring."""

    def __init__(self, limit: int = 1000, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self._lines: deque[str] = deque(maxlen=limit)
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)
            return
        with self._lock:
            self._lines.append(message)

    def lines(self, limit: int = 200) -> list[str]:
        """Return the newest *limit* lines in order."""

        with self._lock:
            return list(self._lines)[-limit:]


def install_log_ring(limit: int = 1000) -> LogRingHandler:
    """Attach a bounded ring handler to the root logger."""

    handler = LogRingHandler(limit=limit)
    logging.getLogger().addHandler(handler)
    return handler
