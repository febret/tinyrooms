"""Render and apply the nginx reverse-proxy configuration for managed instances."""

from __future__ import annotations

from urllib.parse import urlparse
import subprocess

from server.mission_control import nginx_template
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


def render_site_config(config: MCConfig, records: list[InstanceRecord]) -> str:
    """Render the full nginx site configuration for the current services."""

    if config.nginx_conf_path is None:
        raise NginxConfigError("Nginx configuration path is not configured.")
    cert_dir = config.nginx_conf_path.parent / "certs"
    locations = [
        (str(entry["route"]), int(entry["port"])) for entry in service_entries(config, records)
    ]
    return nginx_template.site_config(
        server_name=config.server_name,
        cert_path=str(cert_dir / "server.crt"),
        key_path=str(cert_dir / "server.key"),
        locations=locations,
        root_redirect="/home",
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
