"""Tests for the deployment base-path and public-origin support."""

from __future__ import annotations

from pathlib import Path
import unittest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from server.base_path import BasePathMiddleware, inject_base_path, with_base
from server.config import ConfigError, normalize_base_path, parse_origins


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

    def test_delegates_state_like_attributes(self) -> None:
        inner = FastAPI()
        inner.state.marker = "ok"
        self.assertEqual(BasePathMiddleware(inner, "/admin").state.marker, "ok")

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
