"""Deployment base-path support for servers behind a reverse-proxy prefix."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable
import re

from fastapi.responses import FileResponse, HTMLResponse, Response


_MIME_HTML = "text/html"
_ATTRIBUTE_PATTERN = re.compile(
    r"(?P<attribute>\b(?:href|src|action)\s*=\s*[\"'])/(?P<tail>[^/])",
    re.IGNORECASE,
)
_MAPPING_PATTERN = re.compile(r"(?P<quote>[\"']):\s*(?P<value>[\"'])/(?P<tail>[^/])")
_HEAD_PATTERN = re.compile(r"<head(?P<attributes>\s[^>]*)?>", re.IGNORECASE)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def with_base(base_path: str, url: str) -> str:
    """Prefix a root-relative *url* with *base_path* when one is configured."""

    if not base_path or not url.startswith("/") or url.startswith("//"):
        return url
    return f"{base_path}{url}"


def _document_directory(document_path: str) -> str:
    """Return the trailing-slash directory of a root-relative document path."""

    if not document_path or document_path == "/":
        return "/"
    if document_path.endswith("/"):
        return document_path
    head, _, _ = document_path.rpartition("/")
    return f"{head}/" if head else "/"


def inject_base_path(html: str, base_path: str, document_path: str = "/") -> str:
    """Rewrite root-absolute HTML URLs to honor *base_path*.

    ``document_path`` is the root-relative URL of the document (without the base
    prefix). The injected ``<base>`` points at the document's own directory so
    document-relative references keep resolving correctly for nested pages such
    as activities served under ``/activities/<id>/``.
    """

    if not base_path:
        return html
    html = _ATTRIBUTE_PATTERN.sub(
        lambda match: f'{match.group("attribute")}{base_path}/{match.group("tail")}',
        html,
    )
    html = _MAPPING_PATTERN.sub(
        lambda match: f'{match.group("quote")}: {match.group("value")}{base_path}/{match.group("tail")}',
        html,
    )
    base_href = f"{base_path}{_document_directory(document_path)}"
    injection = (
        f'<base href="{base_href}">'
        f'<script>window.__TR_BASE__="{base_path}";</script>'
    )
    head = _HEAD_PATTERN.search(html)
    if head is not None:
        html = f"{html[:head.end()]}{injection}{html[head.end():]}"
    else:
        html = f"{injection}{html}"
    return html


def render_html(
    path: Path,
    base_path: str,
    *,
    media_type: str = _MIME_HTML,
    document_path: str = "/",
) -> Response:
    """Serve *path* as HTML, injecting the base path when one is configured."""

    if not base_path or not media_type.startswith(_MIME_HTML):
        return FileResponse(path, media_type=media_type)
    text = path.read_text(encoding="utf-8")
    return HTMLResponse(inject_base_path(text, base_path, document_path))


class BasePathMiddleware:
    """Strip a configured prefix from incoming request paths."""

    def __init__(self, app: Any, base_path: str) -> None:
        self.app = app
        self.base_path = base_path

    def __getattr__(self, name: str) -> Any:
        return getattr(self.app, name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.base_path and scope.get("type") in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == self.base_path or path.startswith(f"{self.base_path}/"):
                scope = dict(scope)
                scope["path"] = path[len(self.base_path):] or "/"
                scope["root_path"] = self.base_path
                raw_path = scope.get("raw_path")
                if raw_path:
                    scope["raw_path"] = raw_path[len(self.base_path):] or b"/"
        await self.app(scope, receive, send)
