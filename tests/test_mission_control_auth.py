"""Authentication, CSRF, origin, and rate-limit tests for mission control."""

from __future__ import annotations

import unittest

from server.mission_control.auth import McSessionStore
from tests.mc_helpers import McHttpTestCase


class McSessionStoreTests(unittest.TestCase):
    def test_login_issues_and_expires_sessions(self) -> None:
        store = McSessionStore()
        issued = store.login("secret", "secret")
        session = store.get(issued.token)
        self.assertIsNotNone(session)
        self.assertEqual(session.csrf_token, issued.csrf_token)
        store.logout(issued.token)
        self.assertIsNone(store.get(issued.token))

    def test_wrong_passphrase_rejected(self) -> None:
        store = McSessionStore()
        with self.assertRaises(PermissionError):
            store.login("nope", "secret")


class McAuthRouteTests(McHttpTestCase):
    def test_session_requires_login(self) -> None:
        response = self.client.get("/api/mission-control/session")
        self.assertTrue(response.json()["logged_in"] is False)
        self.assertEqual(self.client.get("/api/mission-control/servers").status_code, 401)

    def test_login_requires_origin(self) -> None:
        response = self.client.post("/api/mission-control/auth/login", json={"passphrase": "letmein"})
        self.assertEqual(response.status_code, 403)

    def test_login_wrong_passphrase(self) -> None:
        response = self.login("wrong")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["ok"])

    def test_login_success_and_csrf(self) -> None:
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(self.client.cookies.get("tr_mc_session"))
        session = self.client.get("/api/mission-control/session").json()
        self.assertTrue(session["logged_in"])

    def test_post_without_csrf_is_rejected(self) -> None:
        self.login()
        response = self.client.post(
            "/api/mission-control/auth/logout",
            headers={"origin": self.origin},
        )
        self.assertEqual(response.status_code, 403)

    def test_logout_clears_session(self) -> None:
        self.login()
        response = self.client.post("/api/mission-control/auth/logout", headers=self.csrf_headers())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.get("/api/mission-control/session").json()["logged_in"])


if __name__ == "__main__":
    unittest.main()
