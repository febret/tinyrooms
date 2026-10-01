"""Tests for the deployment base-path and public-origin support."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import re
import unittest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from server.base_path import BasePathMiddleware, inject_base_path, with_base
from server.config import ConfigError, normalize_base_path, parse_origins
from server.routes.static_files import register_static_routes
from tests.common import REPO_ROOT


class NormalizeBasePathTests(unittest.TestCase):
    def test_root_variants(self) -> None:
        for value in ("", "/", "  "):
            self.assertEqual(normalize_base_path(value), "")

    def test_segments_normalized(self) -> None:
        self.assertEqual(normalize_base_path("/admin"), "/admin")
        self.assertEqual(normalize_base_path("admin"), "/admin")
        self.assertEqual(normalize_base_path("/tinyrooms-world-1/"), "/tinyrooms-world-1")

    def test_invalid_values_rejected(self) -> None:
        for value in ("/admin/../root", "/ad min", "/admin//x"):
            with self.assertRaises(ConfigError):
                normalize_base_path(value)


class ParseOriginsTests(unittest.TestCase):
    def test_origins_parsed_and_deduplicated(self) -> None:
        self.assertEqual(
            parse_origins("https://a.test/, https://b.test/, https://a.test"),
            ("https://a.test", "https://b.test"),
        )

    def test_invalid_origin_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            parse_origins("not-an-origin")


class WithBaseTests(unittest.TestCase):
    def test_prefixes_root_relative_urls(self) -> None:
        self.assertEqual(with_base("/admin", "/api/x"), "/admin/api/x")

    def test_leaves_absolute_and_empty_alone(self) -> None:
        self.assertEqual(with_base("/admin", "https://x/y"), "https://x/y")
        self.assertEqual(with_base("", "/api/x"), "/api/x")
        self.assertEqual(with_base("/admin", "//cdn/x"), "//cdn/x")


class InjectBasePathTests(unittest.TestCase):
    def test_injects_base_and_rewrites_urls(self) -> None:
        html = (
            "<!doctype html><html><head>"
            '<link rel="stylesheet" href="/mission-control/css/app.css">'
            '</head><body><img src="/assets/x.png"></body></html>'
        )
        result = inject_base_path(html, "/admin")
        self.assertIn('<base href="/admin/">', result)
        self.assertIn('window.__TR_BASE__="/admin"', result)
        self.assertIn('href="/admin/mission-control/css/app.css"', result)
        self.assertIn('src="/admin/assets/x.png"', result)
        self.assertNotIn("/admin/admin/", result)

    def test_import_map_addresses_rewritten(self) -> None:
        html = '<script type="importmap">{"imports":{"three":"/app/vendor/three/three.module.js"}}</script>'
        result = inject_base_path(html, "/admin")
        self.assertIn('"/admin/app/vendor/three/three.module.js"', result)

    def test_no_base_path_is_noop(self) -> None:
        html = '<a href="/x">x</a>'
        self.assertEqual(inject_base_path(html, ""), html)

    def test_nested_activity_document_uses_its_own_directory(self) -> None:
        html = '<head><link rel="stylesheet" href="./sticker-designer.css"></head>'
        result = inject_base_path(html, "/home", "/activities/sticker-designer/")
        self.assertIn('<base href="/home/activities/sticker-designer/">', result)

    def test_nested_file_uses_its_parent_directory(self) -> None:
        result = inject_base_path("<head></head>", "/home", "/activities/x/sub/page.html")
        self.assertIn('<base href="/home/activities/x/sub/">', result)


class ActivityBasePathRouteTests(unittest.TestCase):
    def _client(self) -> TestClient:
        app = FastAPI()
        config = SimpleNamespace(
            base_path="/home",
            app_path=REPO_ROOT / "app",
            activities_path=REPO_ROOT / "activities",
        )
        app.state.runtime = SimpleNamespace(config=config, mod_definitions=[])
        register_static_routes(app)
        return TestClient(BasePathMiddleware(app, "/home"), base_url="https://test")

    def test_activity_index_uses_nested_base_href(self) -> None:
        with self._client() as client:
            response = client.get("/home/activities/sticker-designer/")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn('<base href="/home/activities/sticker-designer/">', body)
        self.assertIn('window.__TR_BASE__="/home"', body)
        self.assertIn('href="/home/activities/shared.css"', body)

    def test_activity_assets_are_served_under_base(self) -> None:
        with self._client() as client:
            css = client.get("/home/activities/sticker-designer/sticker-designer.css")
            shared = client.get("/home/activities/shared.js")
        self.assertEqual(css.status_code, 200)
        self.assertEqual(shared.status_code, 200)


class FirstPartyAssetBasePathTests(unittest.TestCase):
    """Guard against root-absolute asset URLs that break behind a base path."""

    def test_css_has_no_root_absolute_asset_urls(self) -> None:
        roots = [
            REPO_ROOT / "app" / "css",
            REPO_ROOT / "mission-control" / "css",
            REPO_ROOT / "prop-editor",
            REPO_ROOT / "world-editor",
            REPO_ROOT / "card-database",
            REPO_ROOT / "activities",
        ]
        offenders: list[str] = []
        for root in roots:
            for path in root.rglob("*.css"):
                if re.search(r"url\(\s*[\"']?/", path.read_text(encoding="utf-8")):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [])


class BasePathMiddlewareTests(unittest.TestCase):
    def _app(self) -> BasePathMiddleware:
        app = FastAPI()

        @app.get("/hello")
        async def hello() -> JSONResponse:
            return JSONResponse({"path": "hello"})

        return BasePathMiddleware(app, "/admin")

    def test_strips_prefix(self) -> None:
        with TestClient(self._app(), base_url="https://test") as client:
            self.assertEqual(client.get("/admin/hello").json(), {"path": "hello"})

    def test_unprefixed_passes_through(self) -> None:
        with TestClient(self._app(), base_url="https://test") as client:
            self.assertEqual(client.get("/hello").json(), {"path": "hello"})

    def test_empty_base_path_does_not_strip(self) -> None:
        inner = FastAPI()

        @inner.get("/admin/hello")
        async def hello() -> JSONResponse:
            return JSONResponse({"ok": True})

        with TestClient(BasePathMiddleware(inner, ""), base_url="https://test") as client:
            self.assertEqual(client.get("/admin/hello").status_code, 200)


class ConfigOriginsTests(unittest.TestCase):
    def test_public_origin_added_to_allowed_origins(self) -> None:
        from server.config import load_config

        env = {
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "invite",
            "TRSERVER_PUBLIC_ORIGIN": "https://tinyrooms.febret.com",
        }
        config = load_config(env=env, repo_root=Path.cwd())
        self.assertIn("https://tinyrooms.febret.com", config.allowed_origins)
        self.assertEqual(config.base_path, "")


if __name__ == "__main__":
    unittest.main()
