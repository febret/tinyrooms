"""Render and apply the nginx reverse-proxy configuration for managed instances."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
import subprocess

from server.mission_control.config import MCConfig
from server.mission_control.registry import STATUS_STOPPED, InstanceRecord


class NginxConfigError(ValueError):
    """Raised when the generated nginx configuration cannot be applied."""


def _endpoint_port(endpoint: str) -> int | None:
    try:
        parsed = urlparse(endpoint)
        return parsed.port
    except ValueError:
        return None


def _route(base_path: str, fallback: str) -> str:
    return base_path.strip("/") or fallback


def service_entries(config: MCConfig, records: list[InstanceRecord]) -> list[dict[str, object]]:
    """Return the reverse-proxy routes for the admin UI and live instances."""

    entries: list[dict[str, object]] = [
        {
            "name": "mission-control",
            "route": config.admin_route,
            "port": config.port,
            "source": "admin",
            "status": "running",
        }
    ]
    for record in records:
        if record.status == STATUS_STOPPED:
            continue
        port = _endpoint_port(record.endpoint)
        if port is None:
            continue
        entries.append(
            {
                "name": record.name,
                "route": _route(record.base_path, record.instance_id),
                "port": port,
                "source": record.source,
                "status": record.status,
            }
        )
    return entries


def _location(route: str, port: int) -> str:
    return (
        f"    location /{route}/ {{\n"
        f"        proxy_pass https://127.0.0.1:{port};\n"
        "        proxy_ssl_verify off;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_set_header Upgrade $http_upgrade;\n"
        '        proxy_set_header Connection "upgrade";\n'
        "    }\n"
    )


def render_site_config(config: MCConfig, records: list[InstanceRecord]) -> str:
    """Render the full nginx site configuration for the current services."""

    if config.nginx_conf_path is None:
        raise NginxConfigError("Nginx configuration path is not configured.")
    cert_dir = config.nginx_conf_path.parent / "certs"
    locations = "\n".join(_location(str(entry["route"]), int(entry["port"])) for entry in service_entries(config, records))
    return (
        "server {\n"
        "    listen 80;\n"
        "    listen [::]:80;\n"
        f"    server_name {config.server_name};\n"
        "    location / { return 301 https://$host$request_uri; }\n"
        "}\n\n"
        "server {\n"
        "    listen 443 ssl;\n"
        "    listen [::]:443 ssl;\n"
        f"    server_name {config.server_name};\n"
        f"    ssl_certificate {cert_dir / 'server.crt'};\n"
        f"    ssl_certificate_key {cert_dir / 'server.key'};\n"
        "    client_max_body_size 64m;\n\n"
        "    location = / { return 302 /home; }\n"
        f"{locations}"
        "}\n"
    )


def _run_command(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        shell=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def apply_site_config(config: MCConfig, text: str) -> dict[str, object]:
    """Write the rendered configuration and reload nginx."""

    if config.nginx_conf_path is None:
        raise NginxConfigError("Nginx configuration path is not configured.")
    path = config.nginx_conf_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    output = ""
    if config.nginx_reload_command:
        result = _run_command(config.nginx_reload_command)
        output = f"{result.stdout or ''}{result.stderr or ''}".strip()
        if result.returncode != 0:
            raise NginxConfigError(f"nginx reload failed ({result.returncode}): {output or 'no output'}")
    return {"path": str(path), "output": output}
