"""Render the fixed Mission Control entry point installed by the deploy tool."""

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


def location_block(port: int) -> str:
    """Proxy all paths to Mission Control without rewriting the request URI."""

    return (
        "    location / {\n"
        f"        proxy_pass https://127.0.0.1:{port};\n"
        f"{_PROXY_HEADERS}"
        "    }\n"
    )


def site_config(
    *,
    server_name: str,
    cert_path: str,
    key_path: str,
    port: int,
) -> str:
    """Render the HTTP-to-HTTPS redirect and the proxied HTTPS server block."""

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
        "    location = /admin { return 302 /mission-control; }\n"
        "    location = /admin/ { return 302 /mission-control; }\n"
        "    location ~ ^/admin/(.*)$ { return 302 /$1$is_args$args; }\n"
        f"{location_block(port)}"
        "}\n"
    )
