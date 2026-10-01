"""Deploy Tinyrooms distributions to remote hosts over SSH.

Usage:
    python tools/deploy.py <host> [rootdir] [type] [-u USER] [--dirty] [--keep-version]

``host`` may be a bare hostname or ``user@host``; ``-u/--user`` overrides the
SSH user. ``bootstrap`` prepares a host (directories, nginx reverse proxy, TLS
certificate, mission-control keepalive) and then runs a ``deploy``. ``deploy``
bumps the patch version, packages the working tree with its dependency manifest,
uploads it, and repoints the ``latest`` symlink. ``--keep-version`` reuses the
newest recorded version instead of bumping, overwriting that release both
locally and on the server.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "version.json"
RELEASES_DIR = REPO_ROOT / "releases"
DEFAULT_ROOT = "~/.local/tinyrooms"
DEFAULT_TYPE = "bootstrap"
ADMIN_SERVICE = "admin"
SERVICE_BASE_PORT = 8001
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
UPLOAD_ATTEMPTS = 3

EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        ".local",
        ".vscode",
        ".pytest_cache",
        ".browser-runtime",
        ".test-results",
        ".test-results-perf",
        ".playwright-report",
        "node_modules",
        "releases",
        "attic",
        "users",
        "__pycache__",
    }
)
EXCLUDED_SUFFIXES = (".pyc", ".sqlite", ".sqlite3", ".db")


class DeployError(RuntimeError):
    """Raised when a deployment step fails."""


def run_remote(host: str, command: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a shell command on the remote host."""

    result = subprocess.run(
        ["ssh", *SSH_OPTIONS, host, command],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise DeployError(f"Remote command failed ({result.returncode}): {command}\n{result.stderr.strip()}")
    return result


def run_local(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a local command."""

    result = subprocess.run(command, cwd=REPO_ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if check and result.returncode != 0:
        raise DeployError(f"Local command failed ({result.returncode}): {' '.join(command)}\n{result.stderr.strip()}")
    return result


def remote_path(root: str, *parts: str) -> str:
    """Join a remote root and path segments, quoting the result."""

    joined = "/".join([root.rstrip("/"), *parts])
    return shlex.quote(joined)


def resolve_root(host: str, root: str) -> str:
    """Resolve a possibly tilde- or home-relative root to an absolute path."""

    if root.startswith("/"):
        return root.rstrip("/")
    home = run_remote(host, "echo $HOME").stdout.strip()
    if root == "~":
        return home
    if root.startswith("~/"):
        return f"{home}/{root[2:]}".rstrip("/")
    return f"{home}/{root}".rstrip("/")


def read_services(host: str, root: str) -> dict[str, dict[str, object]]:
    """Return the remote service registry, or an empty mapping."""

    result = run_remote(host, f"cat {remote_path(root, 'services.json')} 2>/dev/null || true")
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DeployError(f"Remote services.json is not valid JSON: {exc}") from exc


def used_ports(host: str) -> set[int]:
    """Return the set of currently listening TCP ports on the host."""

    result = run_remote(host, "ss -ltnH 2>/dev/null | awk '{print $4}' || true", check=False)
    ports: set[int] = set()
    for line in result.stdout.splitlines():
        match = re.search(r":(\d+)\s*$", line.strip())
        if match:
            ports.add(int(match.group(1)))
    return ports


def allocate_port(host: str, services: dict[str, dict[str, object]]) -> int:
    """Reuse the registered service port or allocate a free one."""

    if "port" in services:
        return int(services["port"])  # type: ignore[arg-type]
    taken = used_ports(host)
    for candidate in range(SERVICE_BASE_PORT, SERVICE_BASE_PORT + 2000):
        if candidate not in taken:
            services["port"] = candidate
            return candidate
    raise DeployError("Could not find a free port for the admin service.")


def ensure_dirs(host: str, root: str) -> None:
    """Create the deployment directory skeleton."""

    run_remote(host, f"mkdir -p {remote_path(root, 'mods')} {remote_path(root, 'worlds')} "
                     f"{remote_path(root, 'releases')} {remote_path(root, 'logs')} {remote_path(root, 'versions')}")


def ensure_python_env(host: str, root: str) -> None:
    """Ensure pip/venv exist and the shared virtualenv is present."""

    run_remote(
        host,
        "python3 -c 'import ensurepip' 2>/dev/null || "
        "{ sudo -n apt-get update && sudo -n apt-get install -y python3-venv python3-pip; }",
    )
    run_remote(host, f"test -d {remote_path(root, 'venv')} || python3 -m venv {remote_path(root, 'venv')}")


def install_requirements(host: str, root: str, version: str) -> None:
    """Install a deployed version's Python requirements into the shared venv."""

    manifest = remote_path(root, "versions", version, "requirements.txt")
    python = remote_path(root, "venv", "bin", "python")
    run_remote(host, f"{python} -m pip install --disable-pip-version-check -r {manifest}")


def latest_version(entries: list[dict[str, object]]) -> dict[str, object]:
    """Return the highest version entry by major/minor/patch."""

    return max(entries, key=lambda entry: (int(entry["major"]), int(entry["minor"]), int(entry["patch"])))


def read_version_entries() -> list[dict[str, object]]:
    """Return the entries recorded in version.json, or an empty list."""

    if not VERSION_FILE.is_file():
        return []
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    entries: list[dict[str, object]] = json.loads(raw)
    return entries


def current_version() -> str:
    """Return the newest recorded version label without modifying version.json."""

    entries = read_version_entries()
    if not entries:
        raise DeployError("version.json has no version entries to keep.")
    current = latest_version(entries)
    return f"{int(current['major'])}.{int(current['minor'])}.{int(current['patch'])}"


def bump_version(dirty: bool) -> tuple[str, bool]:
    """Increment the patch version, write version.json, and return the label."""

    entries = read_version_entries()
    if not entries:
        entries = [{"major": 0, "minor": 0, "patch": 0}]
    current = latest_version(entries)
    entry: dict[str, object] = {
        "major": int(current["major"]),
        "minor": int(current["minor"]),
        "patch": int(current["patch"]) + 1,
    }
    if dirty:
        entry["dirty"] = True
    label = f"{entry['major']}.{entry['minor']}.{entry['patch']}"
    entry["created"] = datetime.now(tz=UTC).isoformat()
    entries.append(entry)
    VERSION_FILE.write_text(json.dumps(entries, indent=4) + "\n", encoding="utf-8")
    return label, dirty


def git_dirty() -> bool:
    """Return True when tracked files have uncommitted changes."""

    result = run_local(["git", "status", "--porcelain", "--untracked-files=no"])
    return bool(result.stdout.strip())


def tag_version(version: str) -> None:
    """Create a local git tag for the released version."""

    tag = f"v{version}"
    exists = run_local(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], check=False)
    if exists.returncode == 0:
        raise DeployError(f"Git tag {tag} already exists.")
    run_local(["git", "tag", tag])
    print(f"Tagged {tag}")


def package(version: str, dirty: bool) -> Path:
    """Create the self-contained release tarball for *version*."""

    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    tarball = RELEASES_DIR / f"tinyrooms-{version}.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        for current, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
            base = Path(current)
            for name in sorted(files):
                if name.endswith(EXCLUDED_SUFFIXES):
                    continue
                path = base / name
                archive.add(path, arcname=str(path.relative_to(REPO_ROOT)))
    suffix = " (dirty)" if dirty else ""
    print(f"Packaged {tarball.relative_to(REPO_ROOT)}{suffix}")
    return tarball


def remote_file_size(host: str, path: str) -> int | None:
    """Return the size of a remote file in bytes, or None when unavailable."""

    result = run_remote(host, f"stat -c %s {path} 2>/dev/null || true", check=False)
    text = result.stdout.strip()
    return int(text) if text.isdigit() else None


def upload_tarball(host: str, root: str, tarball: Path) -> None:
    """Copy *tarball* to the remote releases directory, retrying interrupted uploads."""

    releases_dir = remote_path(root, "releases")
    remote_tarball = remote_path(root, "releases", tarball.name)
    expected = tarball.stat().st_size
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            subprocess.run(["scp", *SSH_OPTIONS, str(tarball), f"{host}:{releases_dir}/"], check=True)
        except subprocess.CalledProcessError:
            pass
        if remote_file_size(host, remote_tarball) == expected:
            return
        if attempt == UPLOAD_ATTEMPTS:
            raise DeployError(f"Upload of {tarball.name} to {host} failed after {UPLOAD_ATTEMPTS} attempts.")
        print(f"Upload of {tarball.name} interrupted; retrying ({attempt}/{UPLOAD_ATTEMPTS - 1})...")
        run_remote(host, f"rm -f {remote_tarball}", check=False)


def upload_release(host: str, root: str, version: str, tarball: Path, *, overwrite: bool = False) -> None:
    """Upload and extract a release into versions/<version>."""

    release_dir = remote_path(root, "versions", version)
    upload_tarball(host, root, tarball)
    if overwrite:
        run_remote(host, f"rm -rf {release_dir} && mkdir -p {release_dir}")
    else:
        run_remote(host, f"mkdir -p {release_dir}")
    run_remote(host, f"tar -xzf {remote_path(root, 'releases', tarball.name)} -C {release_dir}")
    run_remote(host, f"ln -sfn {release_dir} {remote_path(root, 'versions', 'latest')}")
    print(f"Deployed version {version} to {host}:{root}/versions/{version}")


def deploy(
    host: str, server_name: str, root: str, dirty: bool, *, restart: bool = True, keep_version: bool = False
) -> str:
    """Package and deploy a version, returning its label."""

    if not dirty and git_dirty():
        raise DeployError("Uncommitted tracked changes detected. Commit them or pass --dirty.")
    if keep_version:
        version = current_version()
    else:
        version, dirty = bump_version(dirty)
        if not dirty:
            tag_version(version)
    tarball = package(version, dirty)
    ensure_dirs(host, root)
    ensure_python_env(host, root)
    upload_release(host, root, version, tarball, overwrite=keep_version)
    install_requirements(host, root, version)
    registry = read_services(host, root)
    write_admin_env(host, root, server_name, registry)
    ensure_keepalive(host, root)
    if restart:
        restart_admin(host, root)
    return version


def find_free_port(host: str) -> int:
    """Return a free port for the admin service."""

    return allocate_port(host, {})


def write_services(host: str, root: str) -> dict[str, dict[str, object]]:
    """Read, update, and persist the service registry."""

    registry = read_services(host, root)
    entry = registry.setdefault(ADMIN_SERVICE, {})
    entry["base_path"] = f"/{ADMIN_SERVICE}"
    entry["feature"] = "mission-control"
    if "port" not in entry or not entry["port"]:
        entry["port"] = find_free_port(host)
    payload = json.dumps(registry, indent=2)
    run_remote(host, f"cat > {remote_path(root, 'services.json')} <<'JSONEOF'\n{payload}\nJSONEOF")
    return registry


def nginx_locations(registry: dict[str, dict[str, object]]) -> str:
    """Build the reverse-proxy location blocks for every service."""

    blocks = []
    for name, entry in registry.items():
        port = int(entry["port"])  # type: ignore[arg-type]
        blocks.append(
            f"    location /{name}/ {{\n"
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
    return "\n".join(blocks)


def nginx_config(server_name: str, root: str, registry: dict[str, dict[str, object]]) -> str:
    """Render the nginx site configuration."""

    cert = f"{root.rstrip('/')}/nginx/certs/server.crt"
    key = f"{root.rstrip('/')}/nginx/certs/server.key"
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
        f"    ssl_certificate {cert};\n"
        f"    ssl_certificate_key {key};\n"
        "    client_max_body_size 64m;\n\n"
        f"{nginx_locations(registry)}"
        "}\n"
    )


def ensure_nginx(host: str, server_name: str, root: str, registry: dict[str, dict[str, object]]) -> None:
    """Install nginx if needed and write the Tinyrooms site configuration."""

    result = run_remote(
        host,
        "{ command -v nginx || test -x /usr/sbin/nginx; } >/dev/null 2>&1 && echo yes || echo no",
        check=False,
    )
    if result.stdout.strip() != "yes":
        print("Installing nginx via apt...")
        run_remote(host, "sudo -n apt-get update && sudo -n apt-get install -y nginx")
    cert_dir = remote_path(root, "nginx", "certs")
    run_remote(
        host,
        f"mkdir -p {cert_dir} && "
        f"test -f {remote_path(root, 'nginx', 'certs', 'server.crt')} || "
        f"openssl req -x509 -newkey rsa:2048 -nodes "
        f"-keyout {remote_path(root, 'nginx', 'certs', 'server.key')} "
        f"-out {remote_path(root, 'nginx', 'certs', 'server.crt')} "
        f"-days 825 -subj {shlex.quote(f'/CN={server_name}')} "
        f"-addext {shlex.quote(f'subjectAltName=DNS:{server_name}')}",
    )
    config = nginx_config(server_name, root, registry)
    run_remote(host, f"cat > {remote_path(root, 'nginx', 'tinyrooms.conf')} <<'NGINXEOF'\n{config}\nNGINXEOF")
    run_remote(
        host,
        f"sudo -n cp {remote_path(root, 'nginx', 'tinyrooms.conf')} /etc/nginx/sites-available/tinyrooms && "
        "sudo -n ln -sfn /etc/nginx/sites-available/tinyrooms /etc/nginx/sites-enabled/tinyrooms && "
        "sudo -n rm -f /etc/nginx/sites-enabled/default && "
        "sudo -n nginx -t",
    )
    run_remote(host, "sudo -n systemctl enable nginx >/dev/null 2>&1 || true")
    run_remote(host, "sudo -n systemctl restart nginx || sudo -n systemctl start nginx")
    print("nginx configured.")


def read_remote_env(host: str, root: str) -> dict[str, str]:
    """Read the existing admin.env, if any."""

    result = run_remote(host, f"cat {remote_path(root, 'admin.env')} 2>/dev/null || true", check=False)
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def render_env_file(values: dict[str, str]) -> str:
    """Render an env file whose values survive bash sourcing (quoted as needed)."""

    return "".join(f"{key}={shlex.quote(str(value))}\n" for key, value in values.items())


def admin_env_values(
    root: str, host_name: str, registry: dict[str, dict[str, object]], existing: dict[str, str]
) -> dict[str, str]:
    """Return the mission-control environment, preserving existing secrets."""

    entry = registry[ADMIN_SERVICE]
    port = int(entry["port"])  # type: ignore[arg-type]
    passphrase = existing.get("TRSERVER_MC_PASSPHRASE") or secrets.token_urlsafe(18)
    token = existing.get("TRSERVER_MC_TOKEN") or secrets.token_urlsafe(24)
    conf_path = f"{root.rstrip('/')}/nginx/tinyrooms.conf"
    reload_command = (
        f"sudo -n cp {conf_path} /etc/nginx/sites-available/tinyrooms"
        " && sudo -n nginx -t && sudo -n systemctl reload nginx"
    )
    lines = {
        "TRSERVER_FEATURES": "mission-control",
        "TRSERVER_MC_PASSPHRASE": passphrase,
        "TRSERVER_MC_TOKEN": token,
        "TRSERVER_MC_HOST": "127.0.0.1",
        "TRSERVER_MC_PORT": str(port),
        "TRSERVER_MC_BASE_PATH": f"/{ADMIN_SERVICE}",
        "TRSERVER_MC_PUBLIC_ORIGIN": f"https://{host_name}",
        "TRSERVER_MC_USERS_PATH": f"{root.rstrip('/')}/users",
        "TRSERVER_MC_INSTANCES_PATH": f"{root.rstrip('/')}/logs/instances",
        "TRSERVER_MC_VERSIONS_PATH": f"{root.rstrip('/')}/versions",
        "TRSERVER_MC_NGINX_CONF": conf_path,
        "TRSERVER_MC_NGINX_RELOAD": reload_command,
        "TRSERVER_MC_KEEPALIVE": f"{root.rstrip('/')}/keepalive.sh",
        "TRSERVER_MC_INSECURE_TLS": "1",
    }
    new_account_passphrase = existing.get("TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE")
    if new_account_passphrase:
        lines["TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE"] = new_account_passphrase
    return lines


def write_admin_env(host: str, root: str, host_name: str, registry: dict[str, dict[str, object]]) -> None:
    """Write the mission-control environment file, preserving secrets."""

    entry = registry.get(ADMIN_SERVICE)
    if not entry or not entry.get("port"):
        return
    existing = read_remote_env(host, root)
    lines = admin_env_values(root, host_name, registry, existing)
    body = render_env_file(lines)
    run_remote(host, f"cat > {remote_path(root, 'admin.env')} <<'ENVEOF'\n{body}\nENVEOF")
    run_remote(host, f"chmod 600 {remote_path(root, 'admin.env')}")


def keepalive_script(root: str) -> str:
    """Render the keepalive script that supervises the mission-control server."""

    base = root.rstrip("/")
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f'ROOT="{base}"\n'
        'PIDFILE="$ROOT/tinyrooms.pid"\n'
        'if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then\n'
        "  exit 0\n"
        "fi\n"
        "set -a\n"
        'if [ -f "$ROOT/admin.env" ]; then . "$ROOT/admin.env"; fi\n'
        "set +a\n"
        'cd "$ROOT/versions/latest" || exit 1\n'
        'nohup "$ROOT/venv/bin/python" run.py >>"$ROOT/logs/admin.log" 2>&1 &\n'
        'echo $! > "$PIDFILE"\n'
    )


def keepalive_cron_entries(root: str) -> list[str]:
    """Return the crontab entries that keep the mission-control server alive."""

    marker = f"{root.rstrip('/')}/keepalive.sh"
    return [f"@reboot {marker}", f"* * * * * {marker}"]


def ensure_keepalive(host: str, root: str) -> None:
    """Install or refresh the keepalive script and its crontab entries."""

    script = keepalive_script(root)
    run_remote(host, f"cat > {remote_path(root, 'keepalive.sh')} <<'KEEPEOF'\n{script}\nKEEPEOF")
    run_remote(host, f"chmod +x {remote_path(root, 'keepalive.sh')}")
    for cron_line in keepalive_cron_entries(root):
        run_remote(
            host,
            f"crontab -l 2>/dev/null | grep -qF {shlex.quote(cron_line)} || "
            f"(crontab -l 2>/dev/null; echo {shlex.quote(cron_line)}) | crontab -",
        )


def setup_mission_control(host: str, root: str, host_name: str, registry: dict[str, dict[str, object]]) -> None:
    """Install the keepalive script, crontab entries, and start the server."""

    ensure_keepalive(host, root)
    run_remote(host, f"bash {remote_path(root, 'keepalive.sh')}")
    print("Mission control keepalive installed and started.")


def restart_admin(host: str, root: str) -> None:
    """Restart the mission control server if it is running."""

    pidfile = remote_path(root, "tinyrooms.pid")
    result = run_remote(host, f"cat {pidfile} 2>/dev/null || true", check=False)
    pid = result.stdout.strip()
    if pid.isdigit():
        run_remote(host, f"kill {pid} 2>/dev/null || true", check=False)
        for _ in range(20):
            state = run_remote(host, f"kill -0 {pid} 2>/dev/null && echo yes || echo no", check=False)
            if state.stdout.strip() != "yes":
                break
            time.sleep(0.5)
    run_remote(host, f"rm -f {pidfile}", check=False)
    run_remote(host, f"bash {remote_path(root, 'keepalive.sh')}", check=False)


def bootstrap(host: str, server_name: str, root: str, dirty: bool, *, keep_version: bool = False) -> None:
    """Prepare the host and deploy the first version."""

    ensure_dirs(host, root)
    ensure_python_env(host, root)
    registry = write_services(host, root)
    ensure_nginx(host, server_name, root, registry)
    deploy(host, server_name, root, dirty, restart=False, keep_version=keep_version)
    setup_mission_control(host, root, server_name, registry)


def resolve_operation(operation: str | None, keep_version: bool) -> str:
    """Return the operation to run, defaulting to ``deploy`` when keeping a version."""

    if operation:
        return operation
    return "deploy" if keep_version else DEFAULT_TYPE


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Deploy Tinyrooms to a remote host.")
    parser.add_argument("host", help="Remote hostname or user@hostname (passwordless SSH access required).")
    parser.add_argument("rootdir", nargs="?", default=DEFAULT_ROOT, help=f"Deployment root (default: {DEFAULT_ROOT}).")
    parser.add_argument(
        "type",
        nargs="?",
        default=None,
        choices=("bootstrap", "deploy"),
        help=f"Operation to run (default: {DEFAULT_TYPE}, or deploy when --keep-version is set).",
    )
    parser.add_argument("-u", "--user", help="SSH user; overrides any user embedded in the host argument.")
    parser.add_argument("--dirty", action="store_true", help="Package uncommitted changes and skip git tagging.")
    parser.add_argument(
        "--keep-version",
        action="store_true",
        help="Reuse the newest recorded version and overwrite that release instead of bumping it.",
    )
    return parser.parse_args(argv)


def resolve_target(host_spec: str, user: str | None) -> tuple[str, str]:
    """Return the SSH target and server name from a host spec and optional user."""

    spec_user, _, server_name = host_spec.partition("@")
    if not server_name:
        spec_user, server_name = "", host_spec
    selected = user or spec_user
    target = f"{selected}@{server_name}" if selected else server_name
    return target, server_name


def main(argv: list[str] | None = None) -> int:
    """Run the requested deployment operation."""

    args = parse_args(argv)
    try:
        ssh_target, server_name = resolve_target(args.host, args.user)
        root = resolve_root(ssh_target, args.rootdir)
        operation = resolve_operation(args.type, args.keep_version)
        if operation == "bootstrap":
            bootstrap(ssh_target, server_name, root, args.dirty, keep_version=args.keep_version)
        else:
            deploy(ssh_target, server_name, root, args.dirty, keep_version=args.keep_version)
    except DeployError as exc:
        print(f"deploy: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
