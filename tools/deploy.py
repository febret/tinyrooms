"""Deploy Tinyrooms distributions to remote hosts over SSH.

Usage:
    python tools/deploy.py <host> [rootdir] [-u USER] [--dirty] [--keep-version]

``host`` may be a bare hostname or ``user@host``; ``-u/--user`` overrides the
SSH user. Each deployment prepares missing host infrastructure, packages and
uploads the release, installs dependencies, then activates it and checks Mission
Control readiness. The default root is ``~/tinyrooms``. ``--keep-version`` reuses the
newest recorded version instead of bumping, overwriting that release both
locally and on the server.

The tarball is streamed over SSH rather than copied with ``scp`` so that an
interrupted connection resumes from the remote partial file's byte offset and
the release is installed only after its size and SHA-256 digest verify.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "version.json"
RELEASES_DIR = REPO_ROOT / "releases"
DEFAULT_ROOT = "~/tinyrooms"
ADMIN_SERVICE = "admin"
SERVICE_BASE_PORT = 8001
SSH_OPTIONS = (
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=3",
)
UPLOAD_ATTEMPTS = 5
WORLD_MAP_PATH = "/etc/nginx/tinyrooms-worlds.map"
WORLD_MAP_RELOAD = "sudo -n nginx -t && sudo -n systemctl reload nginx"
WORLD_MAP_EMPTY = 'map $tinyrooms_world_id $tinyrooms_world_upstream {\n    default "";\n}\n'

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

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.mission_control.nginx_template import site_config  # noqa: E402


class DeployError(RuntimeError):
    """Raised when a deployment step fails."""


def run_remote(
    host: str,
    command: str,
    *,
    check: bool = True,
    input: str | None = None,
    sensitive: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command on the remote host."""

    result = subprocess.run(
        ["ssh", *SSH_OPTIONS, host, command],
        input=None if input is None else input.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    completed = subprocess.CompletedProcess(result.args, result.returncode, stdout, stderr)
    if check and completed.returncode != 0:
        shown = "<redacted command>" if sensitive else command
        raise DeployError(f"Remote command failed ({completed.returncode}): {shown}\n{stderr.strip()}")
    return completed


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
                     f"{remote_path(root, 'cardsets')} {remote_path(root, 'propsets')} "
                     f"{remote_path(root, 'releases')} {remote_path(root, 'logs')} {remote_path(root, 'versions')}")


def check_remote_prerequisites(host: str) -> None:
    """Fail before preparing a release if required remote tools are missing."""

    run_remote(host, "for tool in bash python3 openssl tar stat sha256sum flock ss crontab systemctl sudo pgrep; do "
                     'command -v "$tool" >/dev/null || { printf "Missing required tool: %s\\n" "$tool" >&2; exit 1; }; done')


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
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DeployError(f"version.json is not valid JSON: {error}") from error
    if not isinstance(entries, list):
        raise DeployError("version.json must contain a list of version entries.")
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


def local_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a local file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stream_to_remote(host: str, command: str, tarball: Path) -> bool:
    """Read the locked remote offset, then send the remaining bytes."""

    with subprocess.Popen(
        ["ssh", *SSH_OPTIONS, host, command],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as process:
        offset = process.stdout.readline().strip()
        if offset.isdigit() and int(offset) <= tarball.stat().st_size:
            print(f"Uploading {tarball.name}: {int(offset)}/{tarball.stat().st_size} bytes...")
            try:
                with tarball.open("rb") as handle:
                    handle.seek(int(offset))
                    shutil.copyfileobj(handle, process.stdin)
            except BrokenPipeError:
                pass
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        process.stdin = None
        _, stderr = process.communicate()
        if stderr:
            print(stderr.decode("utf-8", errors="replace").strip())
        return process.returncode == 0 and offset.isdigit() and int(offset) <= tarball.stat().st_size


def upload_tarball(host: str, root: str, tarball: Path) -> None:
    """Resume a locked partial upload and promote it only after verification."""

    remote_tarball = remote_path(root, "releases", tarball.name)
    expected_size = tarball.stat().st_size
    expected_hash = local_sha256(tarball)
    partial = remote_path(root, "releases", f".{tarball.name}.{expected_hash}.part")
    lock = remote_path(root, "releases", f".{tarball.name}.lock")
    script = (
        "set -e\n"
        "command -v sha256sum >/dev/null\n"
        f"exec 9>{lock}\nflock -x 9\n"
        f"offset=$(stat -c %s {partial} 2>/dev/null || printf 0)\n"
        f"if [ \"$offset\" -gt {expected_size} ]; then rm -f {partial}; offset=0; fi\n"
        "printf '%s\\n' \"$offset\"\n"
        f"cat >> {partial}\n"
        f"[ \"$(stat -c %s {partial})\" -eq {expected_size} ] || exit 1\n"
        f"digest=$(sha256sum {partial})\n"
        f"if [ \"${{digest%% *}}\" != {expected_hash} ]; then rm -f {partial}; exit 1; fi\n"
        f"mv -f {partial} {remote_tarball}\n"
    )
    command = f"bash -c {shlex.quote(script)}"
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        if stream_to_remote(host, command, tarball):
            print(f"Uploaded {tarball.name} ({expected_size} bytes).")
            return
        if attempt == UPLOAD_ATTEMPTS:
            raise DeployError(f"Upload of {tarball.name} to {host} failed after {UPLOAD_ATTEMPTS} attempts.")
        print(f"Upload interrupted; retrying ({attempt}/{UPLOAD_ATTEMPTS - 1})...")


def upload_release(host: str, root: str, version: str, tarball: Path, *, overwrite: bool = False) -> None:
    """Upload and extract a release into versions/<version>."""

    release_dir = remote_path(root, "versions", version)
    upload_tarball(host, root, tarball)
    if overwrite:
        run_remote(host, f"rm -rf {release_dir} && mkdir -p {release_dir}")
    else:
        run_remote(host, f"mkdir -p {release_dir}")
    run_remote(host, f"tar -xzf {remote_path(root, 'releases', tarball.name)} -C {release_dir}")
    print(f"Uploaded version {version} to {host}:{root}/versions/{version}")


def deploy(
    host: str, server_name: str, root: str, dirty: bool, *, keep_version: bool = False
) -> str:
    """Package and deploy a version, returning its label."""

    if not dirty and git_dirty():
        raise DeployError("Uncommitted tracked changes detected. Commit them or pass --dirty.")
    check_remote_prerequisites(host)
    ensure_dirs(host, root)
    ensure_python_env(host, root)
    registry = write_services(host, root)
    ensure_nginx(host, server_name, root, registry)
    if keep_version:
        version = current_version()
    else:
        version, dirty = bump_version(dirty)
        if not dirty:
            tag_version(version)
    tarball = package(version, dirty)
    upload_release(host, root, version, tarball, overwrite=keep_version)
    install_requirements(host, root, version)
    write_admin_env(host, root, server_name, registry)
    ensure_keepalive(host, root)
    run_remote(host, f"ln -sfn {remote_path(root, 'versions', version)} {remote_path(root, 'versions', 'latest')}")
    restart_admin(host, root)
    wait_for_admin(host, root, int(registry[ADMIN_SERVICE]["port"]), version)
    print(f"Deployed version {version}; Mission Control is ready at https://{server_name}/")
    return version


def find_free_port(host: str) -> int:
    """Return a free port for the admin service."""

    return allocate_port(host, {})


def write_services(host: str, root: str) -> dict[str, dict[str, object]]:
    """Read, update, and persist the service registry."""

    registry = read_services(host, root)
    entry = registry.setdefault(ADMIN_SERVICE, {})
    entry["base_path"] = ""
    entry["feature"] = "mission-control"
    if "port" not in entry or not entry["port"]:
        entry["port"] = find_free_port(host)
    payload = json.dumps(registry, indent=2)
    run_remote(host, f"cat > {remote_path(root, 'services.json')} <<'JSONEOF'\n{payload}\nJSONEOF")
    return registry


def nginx_config(server_name: str, root: str, registry: dict[str, dict[str, object]]) -> str:
    """Render the nginx site configuration."""

    base = root.rstrip("/")
    return site_config(
        server_name=server_name,
        cert_path=f"{base}/nginx/certs/server.crt",
        key_path=f"{base}/nginx/certs/server.key",
        port=int(registry[ADMIN_SERVICE]["port"]),  # type: ignore[arg-type]
        world_map_path=WORLD_MAP_PATH,
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
    run_remote(
        host,
        f"sudo -n test -f {WORLD_MAP_PATH} || sudo -n tee {WORLD_MAP_PATH} >/dev/null <<'MAPEOF'\n"
        f"{WORLD_MAP_EMPTY}\nMAPEOF",
    )
    cert_dir = remote_path(root, "nginx", "certs")
    cert = remote_path(root, "nginx", "certs", "server.crt")
    key = remote_path(root, "nginx", "certs", "server.key")
    run_remote(
        host,
        "set -e; "
        f"mkdir -p {cert_dir}; "
        f"if [ ! -e {cert} ] && [ ! -e {key} ]; then "
        "umask 077; "
        f"openssl req -x509 -newkey rsa:2048 -nodes "
        f"-keyout {key} -out {cert} "
        f"-days 825 -subj {shlex.quote(f'/CN={server_name}')} "
        f"-addext {shlex.quote(f'subjectAltName=DNS:{server_name}')} || exit 1; fi; "
        f"test -r {cert} && test -r {key} && "
        f"openssl x509 -in {cert} -noout -checkend 0 && "
        f"cert_public=$(openssl x509 -in {cert} -pubkey -noout) && "
        f"key_public=$(openssl pkey -in {key} -passin pass: -pubout) && "
        '[ "$cert_public" = "$key_public" ]',
    )
    run_remote(host, "sudo -n systemctl enable nginx >/dev/null 2>&1 || true")
    refresh_nginx(host, server_name, root, registry)
    print("nginx configured.")


def refresh_nginx(host: str, server_name: str, root: str, registry: dict[str, dict[str, object]]) -> None:
    """Refresh an existing installation's fixed proxy without changing TLS files."""

    config = nginx_config(server_name, root, registry)
    run_remote(host, f"cat > {remote_path(root, 'nginx', 'tinyrooms.conf')} <<'NGINXEOF'\n{config}\nNGINXEOF")
    run_remote(
        host,
        f"sudo -n cp {remote_path(root, 'nginx', 'tinyrooms.conf')} /etc/nginx/sites-available/tinyrooms && "
        "sudo -n ln -sfn /etc/nginx/sites-available/tinyrooms /etc/nginx/sites-enabled/tinyrooms && "
        "sudo -n rm -f /etc/nginx/sites-enabled/default && "
        "sudo -n nginx -t",
    )
    run_remote(host, "sudo -n systemctl reload nginx || sudo -n systemctl start nginx")


def unquote_env_value(raw: str) -> str:
    """Return the value a bash-sourced env line assigns, preserving quotes.

    ``render_env_file`` writes values with ``shlex.quote``; reading them back by
    merely stripping the outer quotes corrupts any value that itself contains a
    quote. Parsing the value as a shell word round-trips every rendered value and
    also tolerates hand-edited ``export`` lines and trailing comments.
    """

    text = raw.strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text, comments=False)
    except ValueError:
        return text
    return parts[0] if parts else ""


def read_remote_env(host: str, root: str) -> dict[str, str]:
    """Read the existing admin.env, if any."""

    result = run_remote(host, f"cat {remote_path(root, 'admin.env')} 2>/dev/null || true", check=False)
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        values[key] = unquote_env_value(value)
    return values


def render_env_file(values: dict[str, str]) -> str:
    """Render an env file whose values survive bash sourcing (quoted as needed)."""

    return "".join(f"{key}={shlex.quote(str(value))}\n" for key, value in values.items())


def admin_env_values(
    root: str,
    host_name: str,
    registry: dict[str, dict[str, object]],
    existing: dict[str, str],
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the mission-control environment, preserving existing secrets.

    Secrets come from, in order: the deployer's environment (so an operator can
    set ``TRSERVER_MC_PASSPHRASE``/``TRSERVER_MC_TOKEN`` explicitly), the values
    already on the host, or a freshly generated value on first deploy.
    """

    provided = overrides or {}
    entry = registry[ADMIN_SERVICE]
    port = int(entry["port"])  # type: ignore[arg-type]
    passphrase = (
        provided.get("TRSERVER_MC_PASSPHRASE")
        or existing.get("TRSERVER_MC_PASSPHRASE")
        or secrets.token_urlsafe(18)
    )
    token = (
        provided.get("TRSERVER_MC_TOKEN")
        or existing.get("TRSERVER_MC_TOKEN")
        or secrets.token_urlsafe(24)
    )
    lines = {
        "TRSERVER_FEATURES": "mission-control",
        "TRSERVER_MC_PASSPHRASE": passphrase,
        "TRSERVER_MC_TOKEN": token,
        "TRSERVER_MC_HOST": "127.0.0.1",
        "TRSERVER_MC_PORT": str(port),
        "TRSERVER_MC_BASE_PATH": "",
        "TRSERVER_MC_PUBLIC_ORIGIN": f"https://{host_name}",
        "TRSERVER_MC_USERS_PATH": f"{root.rstrip('/')}/users",
        "TRSERVER_MC_INSTANCES_PATH": f"{root.rstrip('/')}/logs/instances",
        "TRSERVER_MC_VERSIONS_PATH": f"{root.rstrip('/')}/versions",
        "TRSERVER_MC_CONTENT_PATH": f"{root.rstrip('/')}",
        "TRSERVER_MC_INSTANCE_HOST": "127.0.0.1",
        "TRSERVER_MC_INSTANCE_PUBLIC_HOST": host_name,
        "TRSERVER_MC_SAME_ORIGIN_WORLDS": "1",
        "TRSERVER_MC_WORLD_MAP": WORLD_MAP_PATH,
        "TRSERVER_MC_WORLD_MAP_RELOAD": WORLD_MAP_RELOAD,
        "TRSERVER_MC_INSTANCE_PORT_MIN": "10000",
        "TRSERVER_MC_INSTANCE_PORT_MAX": "10999",
        "TRSERVER_MC_INSTANCE_CERTFILE": f"{root.rstrip('/')}/nginx/certs/server.crt",
        "TRSERVER_MC_INSTANCE_KEYFILE": f"{root.rstrip('/')}/nginx/certs/server.key",
        "TRSERVER_MC_KEEPALIVE": f"{root.rstrip('/')}/keepalive.sh",
        "TRSERVER_MC_INSECURE_TLS": "1",
    }
    for key in (
        "TRSERVER_MC_HEARTBEAT_SECONDS", "TRSERVER_MC_CA_FILE", "TRSERVER_MC_INSECURE_TLS",
        "TRSERVER_MC_INSTALL_PATH", "TRSERVER_MC_INSTANCE_PORT_MIN", "TRSERVER_MC_INSTANCE_PORT_MAX",
        "TRSERVER_MC_INSTANCE_CERTFILE", "TRSERVER_MC_INSTANCE_KEYFILE", "TRSERVER_MODS",
    ):
        if key in provided:
            lines[key] = provided[key]
        elif key in existing:
            lines[key] = existing[key]
    new_account_passphrase = (
        provided.get("TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE")
        or existing.get("TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE")
    )
    for key in ("TRSERVER_MC_INSTANCE_HOST", "TRSERVER_MC_INSTANCE_PUBLIC_HOST",
                "TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME", "TRSERVER_MC_SAME_ORIGIN_WORLDS",
                "TRSERVER_MC_WORLD_MAP", "TRSERVER_MC_WORLD_MAP_RELOAD"):
        if key in provided:
            lines[key] = provided[key]
    if new_account_passphrase:
        lines["TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE"] = new_account_passphrase
    return lines


def write_admin_env(host: str, root: str, host_name: str, registry: dict[str, dict[str, object]]) -> None:
    """Write the mission-control environment file, preserving secrets."""

    entry = registry.get(ADMIN_SERVICE)
    if not entry or not entry.get("port"):
        return
    existing = read_remote_env(host, root)
    lines = admin_env_values(root, host_name, registry, existing, overrides=dict(os.environ))
    body = render_env_file(lines)
    admin_env = remote_path(root, "admin.env")
    run_remote(
        host,
        f"umask 077; cat > {admin_env} && chmod 600 {admin_env}",
        input=body,
        sensitive=True,
    )


def keepalive_script(root: str) -> str:
    """Render the keepalive script that starts mission control when stopped."""

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


def restart_admin(host: str, root: str) -> None:
    """Stop tracked or orphaned admin processes before starting the keepalive."""

    pidfile = remote_path(root, "tinyrooms.pid")
    pattern = shlex.quote(f"^{re.escape(root.rstrip('/') + '/venv/bin/python')} run\\.py$")
    script = (
        f"pids=$( {{ cat {pidfile} 2>/dev/null; pgrep -f {pattern}; }} | sort -u)\n"
        'for pid in $pids; do\n'
        '  case "$pid" in *[!0-9]*|"") continue;; esac\n'
        '  kill "$pid" 2>/dev/null || true\n'
        "  n=0\n"
        '  while [ "$n" -lt 20 ] && kill -0 "$pid" 2>/dev/null; do\n'
        "    sleep 0.5; n=$((n + 1))\n"
        "  done\n"
        '  if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null || true; fi\n'
        "done\n"
        f"rm -f {pidfile}\n"
        f"bash {remote_path(root, 'keepalive.sh')}\n"
    )
    run_remote(host, f"bash -c {shlex.quote(script)}")


def wait_for_admin(host: str, root: str, port: int, version: str) -> None:
    """Verify the running build and operator login against the deployed env file."""

    script = (
        "import http.cookiejar, json, os, ssl, time, urllib.request\n"
        f"base = 'https://127.0.0.1:{port}'\n"
        "url = base + '/api/mission-control/session'\n"
        "context = ssl._create_unverified_context()\n"
        "deadline = time.monotonic() + 60\n"
        "error = 'No response'\n"
        "while time.monotonic() < deadline:\n"
        "    try:\n"
        "        with urllib.request.urlopen(url, context=context, timeout=2) as response:\n"
        "            data = json.load(response)\n"
        f"        if data.get('ok') is True and data.get('version') == {version!r}:\n"
        "            break\n"
        "        error = 'Unexpected Mission Control response: ' + repr(data)\n"
        "    except Exception as exc:\n"
        "        error = str(exc)\n"
        "    time.sleep(1)\n"
        "else:\n"
        f"    raise SystemExit('Mission Control did not become ready; check ' + {root + '/logs/admin.log'!r} + ': ' + error)\n"
        "opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),\n"
        "    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))\n"
        "request = urllib.request.Request(base + '/api/mission-control/auth/login',\n"
        "    data=json.dumps({'passphrase': os.environ['TRSERVER_MC_PASSPHRASE']}).encode(),\n"
        "    headers={'Content-Type': 'application/json', 'Origin': os.environ['TRSERVER_MC_PUBLIC_ORIGIN']})\n"
        "try:\n"
        "    with opener.open(request, timeout=5) as response:\n"
        "        authenticated = json.load(response).get('ok') is True\n"
        "    with opener.open(url, timeout=5) as response:\n"
        "        authenticated = authenticated and json.load(response).get('logged_in') is True\n"
        "    if not authenticated:\n"
        "        raise ValueError('Operator session was not established')\n"
        "except Exception as exc:\n"
        "    raise SystemExit('Mission Control operator login does not match admin.env: ' + str(exc))\n"
    )
    run_remote(host, f"set -a; . {remote_path(root, 'admin.env')}; set +a; "
                     f"{remote_path(root, 'venv', 'bin', 'python')} -c {shlex.quote(script)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Deploy Tinyrooms to a remote host.")
    parser.add_argument("host", help="Remote hostname or user@hostname (passwordless SSH access required).")
    parser.add_argument("rootdir", nargs="?", default=DEFAULT_ROOT, help=f"Deployment root (default: {DEFAULT_ROOT}).")
    parser.add_argument("-u", "--user", help="SSH user; overrides any user embedded in the host argument.")
    parser.add_argument("--dirty", action="store_true", help="Package uncommitted changes and skip git tagging.")
    parser.add_argument(
        "--keep-version",
        "--keepversion",
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
    """Prepare the remote host and deploy a release."""

    args = parse_args(argv)
    try:
        ssh_target, server_name = resolve_target(args.host, args.user)
        root = resolve_root(ssh_target, args.rootdir)
        deploy(ssh_target, server_name, root, args.dirty, keep_version=args.keep_version)
    except DeployError as exc:
        print(f"deploy: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
