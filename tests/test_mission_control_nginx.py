"""The deployed proxy is static and has no runtime management API."""

from __future__ import annotations

from tests.mc_helpers import McHttpTestCase


class RemovedNginxApiTests(McHttpTestCase):
    def test_preview_and_apply_are_not_registered(self) -> None:
        self.login()
        self.assertEqual(self.client.get("/api/mission-control/nginx").status_code, 404)
        self.assertEqual(
            self.client.post("/api/mission-control/nginx", headers=self.csrf_headers()).status_code,
            404,
        )
