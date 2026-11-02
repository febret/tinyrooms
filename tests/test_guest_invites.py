"""Guest invite token retention rules."""

from __future__ import annotations

import unittest
from datetime import timedelta

from server.security import utc_now
from server.services.guest_invites import (
    GUEST_INVITES_PER_ACCOUNT,
    GuestInviteRecord,
    GuestInviteService,
)


class GuestInvitePruneTests(unittest.TestCase):
    def _service(self) -> GuestInviteService:
        service = object.__new__(GuestInviteService)
        service._invites = {}
        return service

    @staticmethod
    def _record(inviter: str, expires_at) -> GuestInviteRecord:
        return GuestInviteRecord(
            inviter_account_id=inviter,
            world_id="world",
            instance_id="",
            room_id="room",
            expires_at=expires_at,
        )

    def test_prune_keeps_newest_and_drops_expired(self) -> None:
        now = utc_now()
        service = self._service()
        for index in range(GUEST_INVITES_PER_ACCOUNT):
            service._invites[f"old-{index}"] = self._record("alice", now + timedelta(minutes=1))
        service._invites["new"] = self._record("alice", now + timedelta(minutes=1))
        service._invites["expired"] = self._record("alice", now - timedelta(minutes=1))
        service._invites["other"] = self._record("bob", now + timedelta(minutes=1))

        service._prune(now)

        self.assertIn("new", service._invites)
        self.assertIn("other", service._invites)
        self.assertNotIn("old-0", service._invites)
        self.assertNotIn("expired", service._invites)
        self.assertEqual(
            sum(1 for record in service._invites.values() if record.inviter_account_id == "alice"),
            GUEST_INVITES_PER_ACCOUNT,
        )


if __name__ == "__main__":
    unittest.main()
