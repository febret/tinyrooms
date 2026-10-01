"""Render the nginx reverse-proxy site config shared by mission control and the deploy tool.

The mission-control server owns live regeneration, while ``tools/deploy.py``
bootstraps the host. Both must emit the same config, so the template lives here
with no dependencies beyond the standard library.
"""

from __future__ import annotations

_PROXY_HEADERS = (
    "        proxy_ssl_verify off;\n"
    "        proxy_http_version 1.1;\n"
    "        proxy_set_header Host $host;\n"
    "        proxy_set_header X-Real-IP $remote_addr;\n"
    "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
    "        proxy_set_header X-Forwarded-Proto $scheme;\n"
    "        proxy_set_header Upgrade $http_upgrade;\n"
    '        proxy_set_header Connection "upgrade";\n'
)


def location_block(route: str, port: int) -> str:
    """Return one ``location /<route>/`` proxy block."""

    return (
        f"    location /{route}/ {{\n"
        f"        proxy_pass https://127.0.0.1:{port};\n"
        f"{_PROXY_HEADERS}"
        "    }\n"
    )


def site_config(
    *,
    server_name: str,
    cert_path: str,
    key_path: str,
    locations: list[tuple[str, int]],
    root_redirect: str | None = None,
) -> str:
    """Render the HTTP-to-HTTPS redirect and the proxied HTTPS server block."""

    blocks = "\n".join(location_block(route, port) for route, port in locations)
    redirect = f"    location = / {{ return 302 {root_redirect}; }}\n" if root_redirect else ""
    return (
        "server {\n"
        "    listen 80;\n"
        "    listen [::]:80;\n"
        f"    server_name {server_name};\n"
        "    location / { return 301 https://$host$request_uri; }\n"
        "}\n\n"
        "server {\n"
        "    listen 443 ssl;\n"
        "    listen [::]:443 ssl;\n"
        f"    server_name {server_name};\n"
        f"    ssl_certificate {cert_path};\n"
        f"    ssl_certificate_key {key_path};\n"
        "    client_max_body_size 64m;\n\n"
        f"{redirect}"
        f"{blocks}"
        "}\n"
    )
