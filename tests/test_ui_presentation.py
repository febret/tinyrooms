"""Static browser-contract tests for the Milestone 1 client."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import unittest

from tests.common import REPO_ROOT


class UIPresentationTests(unittest.TestCase):
    """Guard the responsive shell and authoritative client integration."""

    def test_entrypoint_uses_local_assets_and_accessible_landmarks(self) -> None:
        index = (REPO_ROOT / "app" / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="viewport"', index)
        self.assertIn('src="/app/js/ui.js"', index)
        self.assertIn('"/app/vendor/three/three.module.js"', index)
        self.assertIn('id="board-canvas"', index)
        self.assertIn('id="chat-form"', index)
        self.assertNotRegex(index, r"https?://")

    def test_client_uses_live_server_contract_without_local_gameplay_storage(self) -> None:
        javascript = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((REPO_ROOT / "app" / "js").glob("*.js"))
        )
        self.assertIn('session: "/api/session"', javascript)
        self.assertIn('websocket: "/ws"', javascript)
        self.assertIn('"tinyrooms.activity.sticker.confirm"', javascript)
        self.assertNotIn("localStorage", javascript)
        self.assertNotIn("sessionStorage", javascript)

    def test_stylesheets_exist_and_browser_suite_covers_real_layout(self) -> None:
        """Check asset wiring here; Playwright checks computed geometry."""
        stylesheets: list[str] = []

        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == "link" and attributes.get("rel") == "stylesheet":
                    stylesheets.append(attributes["href"])

        Links().feed((REPO_ROOT / "app" / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(stylesheets)
        for href in stylesheets:
            self.assertTrue(href.startswith("/app/"))
            self.assertTrue((REPO_ROOT / href.lstrip("/")).is_file(), href)
        package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("@playwright/test", package["devDependencies"])
        self.assertIn("test:browser", package["scripts"])

    def test_first_party_source_files_stay_below_limit(self) -> None:
        roots = [
            REPO_ROOT / "server",
            REPO_ROOT / "app" / "js",
            REPO_ROOT / "app" / "css",
            REPO_ROOT / "activities",
            REPO_ROOT / "tests",
            REPO_ROOT / "tools",
        ]
        oversized: list[str] = []
        for root in roots:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {
                    ".py",
                    ".js",
                    ".css",
                    ".html",
                }:
                    continue
                if "vendor" in path.parts:
                    continue
                line_count = len(path.read_text(encoding="utf-8").splitlines())
                if line_count >= 1200:
                    oversized.append(f"{path.relative_to(REPO_ROOT)}: {line_count}")
        self.assertEqual(oversized, [])


if __name__ == "__main__":
    unittest.main()
