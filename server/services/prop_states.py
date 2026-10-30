"""In-memory per-instance active prop-state selection.

State definitions and each prop's authored default live in YAML; this service
only tracks runtime switches made through the service API. The state is
intentionally transient: a process restart, or a world reload that drops the
room, falls back to the authored default.
"""

from __future__ import annotations

from server.services.transient_maps import TransientRoomMap


class PropStateService(TransientRoomMap[str]):
    """Track the active mesh state chosen for each prop instance."""

    def state_for(self, room_id: str, prop_instance_id: str, default: str | None) -> str | None:
        """Return the runtime override, or the authored default when none."""

        return self.get(room_id, prop_instance_id, default)
