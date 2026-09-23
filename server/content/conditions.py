"""Shared counter-condition vocabulary for statuses and dialogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.content.common import ContentError


@dataclass(frozen=True, slots=True)
class StatusCondition:
    """A single counter predicate that applies or clears a status."""

    counter: str
    at_or_below: float | None = None
    at_or_above_fraction: float | None = None
    above: float | None = None

    def matches(self, value: float, maximum: float | None = None) -> bool:
        """Return whether *value* satisfies this condition."""

        if self.at_or_below is not None and value <= self.at_or_below:
            return True
        if self.above is not None and value > self.above:
            return True
        if self.at_or_above_fraction is not None and maximum is not None:
            return value >= maximum * self.at_or_above_fraction
        return False


def parse_status_condition(raw_value: Any, label: str, *, required: bool = False) -> StatusCondition | None:
    """Parse an authored condition mapping into a :class:`StatusCondition`.

    *label* prefixes validation errors. A missing mapping is rejected when
    *required* is set and otherwise returns ``None``.
    """

    if raw_value is None:
        if required:
            raise ContentError(f"{label} must be a mapping.")
        return None
    if not isinstance(raw_value, dict):
        raise ContentError(f"{label} must be a mapping.")
    counter = str(raw_value.get("counter", "")).strip()
    if not counter:
        raise ContentError(f"{label} is missing a counter.")
    at_or_below = raw_value.get("at_or_below")
    above = raw_value.get("above")
    at_or_above_fraction = raw_value.get("at_or_above_fraction")
    provided = [value for value in (at_or_below, above, at_or_above_fraction) if value is not None]
    if len(provided) != 1:
        raise ContentError(f"{label} must define exactly one comparison.")
    return StatusCondition(
        counter=counter,
        at_or_below=float(at_or_below) if at_or_below is not None else None,
        at_or_above_fraction=float(at_or_above_fraction) if at_or_above_fraction is not None else None,
        above=float(above) if above is not None else None,
    )
