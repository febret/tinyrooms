"""Custom sticker designer persistence, validation, and serving tests."""

from __future__ import annotations

import base64
from dataclasses import replace
import io
import os
from pathlib import Path
import unittest

from tests.test_milestone1 import RuntimeTestCase, auth_cookies, auth_headers

DESIGN = {
    "version": 1,
    "body": "body-tee",
    "hair": "hair-short",
    "shoes": "shoes-sneakers",
    "back": "back-none",
    "face": "face-none",
    "colors": {
        "skin": "#fbe9d7",
        "skinDark": "#e4c6a8",
        "shirt": "#3f5a72",
        "shirtDark": "#2a3f52",
        "pants": "#3f6b3f",
        "pantsDark": "#294a29",
        "hair": "#6b3f22",
        "hairDark": "#482814",
        "shoes": "#3a3a42",
        "shoesDark": "#232329",
        "accent": "#c79a3a",
        "accentDark": "#936f24",
        "face": "#e07a7a",
    },
}


def png_data_url(size: int, color: tuple[int, int, int, int] = (120, 90, 70, 255)) -> str:
    """Build a base64 PNG data URL for tests."""

    from PIL import Image

    image = Image.new("RGBA", (size, size), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def noisy_png_data_url(size: int) -> str:
    """Build an incompressible PNG data URL large enough to exceed the size cap."""

    from PIL import Image

    image = Image.frombytes("RGBA", (size, size), os.urandom(size * size * 4))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


class StickerDesignerTestCase(RuntimeTestCase):
    """Run the app with an isolated custom-sticker directory."""

    def setUp(self) -> None:
        super().setUp()
        stickers_dir = self.runtime_path / "custom-stickers"
        stickers_dir.mkdir(parents=True, exist_ok=True)
        self.config = replace(self.config, custom_stickers_path=stickers_dir)
        self._close_client()
        self._open_client()

    def confirm(self, credentials, payload: dict[str, object]):
        """POST an authenticated sticker confirmation payload."""

        return self.client.post(
            "/api/stickers/confirm",
            json=payload,
            headers=auth_headers(credentials["csrf_token"]),
            cookies=auth_cookies(credentials["session_token"], credentials["csrf_token"]),
        )

    def bootstrap(self, credentials):
        """Fetch the authenticated bootstrap payload."""

        return self.client.get(
            "/api/bootstrap",
            cookies=auth_cookies(credentials["session_token"], credentials["csrf_token"]),
        )

    def set_bops(self, username: str, bops: int) -> None:
        """Set an account's Bops balance directly for swap-cost tests."""

        runtime = self.client.app.state.runtime
        account = runtime.profiles.get_account_by_username(username)
        with runtime.hub.transaction() as connection:
            runtime.profiles.update_progress(connection, account, bops=bops)

    def test_custom_sticker_is_saved_served_and_serialized(self) -> None:
        credentials = self.create_account("painter")
        response = self.confirm(credentials, {"sticker": "", "image": png_data_url(96), "design": DESIGN})
        self.assertEqual(response.status_code, 200, response.text)
        user = response.json()["user"]
        self.assertTrue(user["initial_sticker_complete"])
        self.assertEqual(user["sticker"], f"custom-{user['id']}.png")
        self.assertEqual(user["sticker_design"]["hair"], "hair-short")
        self.assertEqual(user["sticker_design"]["colors"]["skin"], "#fbe9d7")

        asset = self.client.get(f"/assets/stickers/{user['sticker']}")
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers["content-type"], "image/png")

        bootstrap = self.bootstrap(credentials).json()["user"]
        self.assertEqual(bootstrap["sticker"], user["sticker"])
        self.assertEqual(bootstrap["sticker_design"]["body"], "body-tee")

    def test_custom_swap_charges_once_and_is_idempotent(self) -> None:
        credentials = self.create_ready_account("swapper")
        before = self.bootstrap(credentials).json()["user"]
        self.assertEqual(before["sticker"], "s1.png")
        self.assertIsNone(before["sticker_design"])

        image = png_data_url(96)
        first = self.confirm(credentials, {"sticker": "", "image": image, "design": DESIGN})
        self.assertEqual(first.status_code, 200, first.text)
        after_first = first.json()["user"]
        self.assertEqual(after_first["bops"], before["bops"] - before["sticker_swap_cost"])

        second = self.confirm(credentials, {"sticker": "", "image": image, "design": DESIGN})
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["user"]["bops"], after_first["bops"])

    def test_rejected_custom_swap_leaves_image_and_design(self) -> None:
        credentials = self.create_ready_account("blocked")
        first = self.confirm(
            credentials,
            {"sticker": "", "image": png_data_url(96, (10, 20, 30, 255)), "design": DESIGN},
        )
        self.assertEqual(first.status_code, 200, first.text)
        user = first.json()["user"]
        original = self.client.get(f"/assets/stickers/{user['sticker']}").content

        changed = {**DESIGN, "hair": "hair-long", "colors": {**DESIGN["colors"], "hair": "#b83a3a"}}
        rejected = self.confirm(
            credentials,
            {"sticker": "", "image": png_data_url(96, (200, 30, 30, 255)), "design": changed},
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(self.client.get(f"/assets/stickers/{user['sticker']}").content, original)
        bootstrap = self.bootstrap(credentials).json()["user"]
        self.assertEqual(bootstrap["sticker_design"]["hair"], "hair-short")

    def test_swap_back_to_preset_clears_design(self) -> None:
        credentials = self.create_ready_account("reverter")
        self.set_bops("reverter", 50)
        custom = self.confirm(credentials, {"sticker": "", "image": png_data_url(96), "design": DESIGN})
        self.assertEqual(custom.status_code, 200, custom.text)
        reverted = self.confirm(credentials, {"sticker": "s2.png", "design": None})
        self.assertEqual(reverted.status_code, 200, reverted.text)
        user = reverted.json()["user"]
        self.assertEqual(user["sticker"], "s2.png")
        self.assertIsNone(user["sticker_design"])

    def test_invalid_custom_payloads_are_rejected(self) -> None:
        credentials = self.create_account("clumsy")
        cases = [
            {"sticker": "", "image": "not-a-data-url", "design": DESIGN},
            {"sticker": "", "image": "data:image/png;base64,aGVsbG8=", "design": DESIGN},
            {"sticker": "", "image": png_data_url(96)},
            {"sticker": "", "image": png_data_url(96), "design": {**DESIGN, "colors": {**DESIGN["colors"], "skin": "red"}}},
            {"sticker": "", "image": png_data_url(96), "design": {**DESIGN, "hair": "not a valid id"}},
        ]
        for payload in cases:
            response = self.confirm(credentials, payload)
            self.assertEqual(response.status_code, 400, f"{payload} -> {response.text}")

    def test_oversized_custom_image_is_rejected(self) -> None:
        credentials = self.create_account("bigshot")
        response = self.confirm(credentials, {"sticker": "", "image": noisy_png_data_url(1024), "design": DESIGN})
        self.assertEqual(response.status_code, 400, response.text)

    def test_custom_names_are_not_listed_as_presets(self) -> None:
        credentials = self.create_ready_account("lister")
        before = self.client.get("/api/stickers").json()["stickers"]
        self.confirm(credentials, {"sticker": "", "image": png_data_url(96), "design": DESIGN})
        after = self.client.get("/api/stickers").json()["stickers"]
        self.assertEqual([entry["name"] for entry in before], [entry["name"] for entry in after])


if __name__ == "__main__":
    unittest.main()
