"""Change descriptors for journal task progress.

The task service is a pure persistence layer; it reports what changed through
``TaskChange`` records so command and behavior callers can turn them into
client feedback (a cutscene and memory toasts) after their transaction commits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskChange:
    """One observable change to an account's task progress."""

    account_id: str
    task_id: str
    task_title: str
    kind: str
    step_id: str | None = None
    step_title: str | None = None
    memory_texts: tuple[str, ...] = ()
