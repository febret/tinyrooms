"""HTML responses for activity and cutscene routes."""

from __future__ import annotations

import html

from fastapi.responses import HTMLResponse


def render_fallback_activity(kind: str) -> HTMLResponse:
    """Render the placeholder page for a cutscene-less activity directory."""

    title = html.escape(kind.replace("-", " ").title())
    body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:sans-serif;padding:1rem">
  <h1>{title}</h1>
  <p>Fallback activity page for <code>{title}</code>.</p>
  <p>This route is ready for the real activity files under <code>activities\\{html.escape(kind)}</code>.</p>
</body>
</html>"""
    return HTMLResponse(body)
