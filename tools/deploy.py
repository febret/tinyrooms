"""Deploy Tinyrooms distributions to remote hosts over SSH.

Usage:
    python tools/deploy.py <host> [rootdir] [-u USER] [--content FILE] [--dirty]
                           [--force] [--force-restart]

``host`` may be a bare hostname or ``user@host``; ``-u/--user`` overrides the
SSH user. Each deployment prepares missing host infrastructure, packages and
uploads the release, installs dependencies, then activates it and checks Mission
Control readiness. Worlds come from the deployment content file (default
``multiworld.json``); only entries enabled in that file are packaged, together
with the mods, cardsets, and propsets their ``world.yaml`` requires. The
tarball name carries a SHA-256 content hash, and a ``deploy-manifest.json`` in
the package records it for Mission Control. The default root is ``~/tinyrooms``.
The deploy script never modifies ``version.json``: it ships the newest recorded
version. If a local or remote artifact already exists with that version,
deployment stops unless ``--force`` is given to overwrite it. Cut a new release
by editing ``version.json`` before deploying.

``--force-restart`` additionally rolls every *running spawned* instance onto
the deployed version before Mission Control itself restarts: each such child
is pointed at the new checkout and restarted, and the deploy script streams
per-instance progress while it waits for them to report the new build.
External instances cannot be updated and are skipped with a warning; stopped
instances are left untouched. Deployment always restarts Mission Control once
to activate the release, so no extra restart is added for this flag.

The tarball is streamed over SSH rather than copied with ``scp`` so that an
interrupted connection resumes from the remote partial file's byte offset and
the release is installed only after its size and SHA-256 digest verify.

Console output is animated and colored when stdout is a TTY; it degrades to
plain lines otherwise, and honors ``NO_COLOR``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterator
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
        # Design documentation and test suites ship in git only; releases carry
        # runtime code, content, and tools.
        "doc",
        "tests",
    }
)
EXCLUDED_FILES = frozenset(
    {
        ".gitignore",
        "AGENTS.md",
        "TASKS.md",
        "playwright.config.js",
        "playwright.perf.config.js",
        "requirements-dev.txt",
        "run_tests.sh",
    }
)
EXCLUDED_SUFFIXES = (".pyc", ".sqlite", ".sqlite3", ".db")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from deploy_console import CONSOLE, Console  # noqa: E402
from deploy_content import (  # noqa: E402
    DEFAULT_CONTENT_FILE,
    ContentConfigError,
    ContentSelection,
    content_hash,
    iter_content_members,
    load_content_selection,
)
from server.mission_control.nginx_template import site_config  # noqa: E402
from server.version import DEPLOY_MANIFEST_FILE, package_filename  # noqa: E402


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


def stream_remote(host: str, command: str, on_line: Callable[[str], None]) -> int:
    """Run a remote command, forwarding each stdout/stderr line to *on_line*.

    Returns the remote exit status. Standard error is merged into the stream
    because the fleet helper reserves stdout for structured event lines.
    """

    process = subprocess.Popen(
        ["ssh", *SSH_OPTIONS, host, command],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    try:
        assert process.stdout is not None
        for line in process.stdout:
            on_line(line.rstrip("\n"))
    finally:
        try:
            process.wait(timeout=10)
        except Exception:  # noqa: BLE001 - always clean up the SSH child
            process.kill()
            raise
    return process.returncode


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
        raise DeployError("version.json has no version entries.")
    current = latest_version(entries)
    return f"{int(current['major'])}.{int(current['minor'])}.{int(current['patch'])}"


def git_dirty() -> bool:
    """Return True when tracked files have uncommitted changes."""

    result = run_local(["git", "status", "--porcelain", "--untracked-files=no"])
    return bool(result.stdout.strip())


def release_members(
    root: Path,
    selection: ContentSelection | None = None,
) -> Iterator[tuple[Path, str]]:
    """Yield ``(path, arcname)`` pairs included in a release tarball.

    ``tools/fleet_restart.py`` and the other runtime helpers stay in the
    release; design docs, tests, and dev-only files are omitted. When a content
    selection is supplied, runtime content roots are replaced by exactly the
    selected worlds, mods, cardsets, and propsets, which may live outside
    *root*.
    """

    prefixes = selection.prefixes() if selection is not None else ()

    def selected(relative: str) -> bool:
        return any(
            relative == prefix or relative.startswith(prefix + "/") for prefix in prefixes
        )

    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        base = Path(current)
        relative_root = base.relative_to(root)
        if selection is not None and selected(relative_root.as_posix()):
            dirs[:] = []
            continue
        for name in sorted(files):
            if name in EXCLUDED_FILES or name.endswith(EXCLUDED_SUFFIXES):
                continue
            path = base / name
            relative = path.relative_to(root)
            if selection is not None and selected(relative.as_posix()):
                continue
            yield path, str(relative)
    if selection is not None:
        for entry in selection.entries():
            yield from iter_content_members(entry)


def package(
    version: str,
    dirty: bool,
    console: Console | None = None,
    *,
    selection: ContentSelection,
    version_hash: str | None = None,
) -> Path:
    """Create the self-contained release tarball for *version*.

    *selection* comes from ``deploy()`` via ``load_content_selection``; the
    tarball name carries the content hash so identical deployments share one
    identifiable package.
    """

    console = console or CONSOLE
    digest = version_hash or content_hash(selection)
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    tarball = RELEASES_DIR / package_filename(version, digest)
    manifest = json.dumps(selection.manifest(version, digest), indent=2, sort_keys=True).encode("utf-8")
    count = 0
    with tarfile.open(tarball, "w:gz") as archive:
        for path, arcname in release_members(REPO_ROOT, selection):
            archive.add(path, arcname=arcname)
            count += 1
        info = tarfile.TarInfo(DEPLOY_MANIFEST_FILE)
        info.size = len(manifest)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(manifest))
        count += 1
    size_mb = tarball.stat().st_size / 1e6
    suffix = " (dirty)" if dirty else ""
    console.info(
        f"Packaged {tarball.relative_to(REPO_ROOT)} ({count} files, {size_mb:.0f} MB, "
        f"hash {digest[:12]}){suffix}"
    )
    return tarball


def local_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a local file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _release_names(version: str, version_hash: str | None) -> list[str]:
    names = [f"tinyrooms-{version}.tar.gz"]
    if version_hash:
        hashed = package_filename(version, version_hash)
        if hashed not in names:
            names.insert(0, hashed)
    return names


def local_artifact_clashes(
    version: str,
    releases_dir: Path | None = None,
    version_hash: str | None = None,
) -> list[str]:
    """Return descriptions of local artifacts that collide with *version*."""

    releases_dir = RELEASES_DIR if releases_dir is None else releases_dir
    clashes: list[str] = []
    for name in _release_names(version, version_hash):
        tarball = releases_dir / name
        if tarball.is_file():
            clashes.append(f"local release {tarball}")
    return clashes


def remote_artifact_clashes(
    host: str,
    root: str,
    version: str,
    version_hash: str | None = None,
) -> list[str]:
    """Return descriptions of remote artifacts that collide with *version*."""

    clashes: list[str] = []
    for tarball_name in _release_names(version, version_hash):
        if run_remote(host, f"test -e {remote_path(root, 'releases', tarball_name)}", check=False).returncode == 0:
            clashes.append(f"remote release {root}/releases/{tarball_name}")
    if run_remote(host, f"test -e {remote_path(root, 'versions', version)}", check=False).returncode == 0:
        clashes.append(f"remote checkout {root}/versions/{version}")
    return clashes


def existing_artifacts(
    host: str,
    root: str,
    version: str,
    version_hash: str | None = None,
) -> list[str]:
    """Return descriptions of local and remote artifacts already using *version*."""

    return local_artifact_clashes(version, version_hash=version_hash) + remote_artifact_clashes(
        host, root, version, version_hash
    )


def stream_to_remote(host: str, command: str, tarball: Path, console: Console | None = None) -> bool:
    """Read the locked remote offset, then send the remaining bytes."""

    console = console or CONSOLE
    with subprocess.Popen(
        ["ssh", *SSH_OPTIONS, host, command],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as process:
        offset = process.stdout.readline().strip()
        if offset.isdigit() and int(offset) <= tarball.stat().st_size:
            remaining = tarball.stat().st_size - int(offset)
            try:
                with tarball.open("rb") as handle:
                    handle.seek(int(offset))
                    if remaining:
                        with console.progress(f"Uploading {tarball.name}", remaining) as advance:
                            while True:
                                chunk = handle.read(1024 * 1024)
                                if not chunk:
                                    break
                                try:
                                    process.stdin.write(chunk)
                                except BrokenPipeError:
                                    break
                                advance(len(chunk))
                    else:
                        console.info(f"{tarball.name} is already fully uploaded.")
            except BrokenPipeError:
                pass
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        process.stdin = None
        _, stderr = process.communicate()
        if stderr:
            console.warning(stderr.decode("utf-8", errors="replace").strip())
        return process.returncode == 0 and offset.isdigit() and int(offset) <= tarball.stat().st_size


def upload_tarball(host: str, root: str, tarball: Path, console: Console | None = None) -> None:
    """Resume a locked partial upload and promote it only after verification."""

    console = console or CONSOLE

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
        if stream_to_remote(host, command, tarball, console=console):
            console.success(f"Uploaded {tarball.name} ({expected_size} bytes).")
            return
        if attempt == UPLOAD_ATTEMPTS:
            raise DeployError(f"Upload of {tarball.name} to {host} failed after {UPLOAD_ATTEMPTS} attempts.")
        console.warning(f"Upload interrupted; retrying ({attempt}/{UPLOAD_ATTEMPTS - 1})...")


def upload_release(host: str, root: str, version: str, tarball: Path, *, overwrite: bool = False,
                   console: Console | None = None) -> None:
    """Upload and extract a release into versions/<version>."""

    console = console or CONSOLE
    release_dir = remote_path(root, "versions", version)
    upload_tarball(host, root, tarball, console=console)
    if overwrite:
        run_remote(host, f"rm -rf {release_dir} && mkdir -p {release_dir}")
    else:
        run_remote(host, f"mkdir -p {release_dir}")
    run_remote(host, f"tar -xzf {remote_path(root, 'releases', tarball.name)} -C {release_dir}")
    console.info(f"Uploaded version {version} to {host}:{root}/versions/{version}")


class _FleetProgress:
    """Renders fleet_restart.py JSON event lines as live console status."""

    def __init__(self, version: str, console: Console) -> None:
        self.version = version
        self.console = console
        self.failures: list[str] = []
        self.done = False
        self.error = ""
        self.unreachable = False

    def handle(self, raw: str) -> None:
        """Render one raw output line from the fleet helper."""

        line = raw.strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self.console.warning(f"fleet: {line}")
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "begin":
            total = event.get("total", 0)
            skipped = event.get("skipped", [])
            if total:
                self.console.info(f"Rolling {total} running instance(s) to version {self.version}")
            else:
                self.console.info("No running spawned instances to restart.")
            for item in skipped if isinstance(skipped, list) else []:
                if isinstance(item, dict):
                    self.console.warning(f"Skipped {item.get('name') or item.get('instance_id')}: {item.get('reason')}")
        elif kind == "instance":
            label = str(event.get("name") or event.get("instance_id") or "instance")
            world = event.get("world")
            label = f"{label} ({world})" if world else label
            status = event.get("status")
            if status == "updating":
                self.console.start_spinner(f"Restarting {label} on {self.version}")
            elif status == "waiting":
                self.console.update_spinner(f"Waiting for {label} to report {self.version}")
            elif status == "ready":
                self.console.stop_spinner()
                self.console.success(f"Restarted {label} on {self.version} ({event.get('elapsed', 0)}s)")
            elif status == "failed":
                self.console.stop_spinner()
                self.console.error(f"Failed to restart {label}: {event.get('message')}")
                self.failures.append(label)
        elif kind == "done":
            self.done = True
        elif kind == "error":
            self.error = str(event.get("message") or "fleet restart failed")
            self.unreachable = event.get("code") == "unreachable"


def render_fleet_events(version: str, lines: list[str], console: Console | None = None) -> list[str]:
    """Render fleet helper event lines; return the labels of failed instances."""

    progress = _FleetProgress(version, console or CONSOLE)
    for line in lines:
        progress.handle(line)
    progress.console.stop_spinner()
    return progress.failures


def force_restart_fleet(host: str, root: str, version: str, console: Console | None = None) -> list[str]:
    """Update every running spawned instance to *version* and restart it.

    Runs ``tools/fleet_restart.py`` from the freshly deployed checkout on the
    remote host, rendering its JSON event stream as live console status.
    Returns the labels of instances that failed so deployment can finish its
    own restart and readiness checks before reporting them.
    """

    console = console or CONSOLE
    admin_env = remote_path(root, "admin.env")
    if run_remote(host, f"test -f {admin_env}", check=False).returncode != 0:
        console.info("No existing admin.env; nothing to force restart on a fresh install.")
        return []
    python = remote_path(root, "venv", "bin", "python")
    helper = remote_path(root, "versions", version, "tools", "fleet_restart.py")
    command = (
        f"set -a; . {admin_env}; set +a; "
        f"exec {python} {helper} --port \"$TRSERVER_MC_PORT\" --version {shlex.quote(version)}"
    )
    failures: list[str] = []
    progress = _FleetProgress(version, console)

    try:
        status = stream_remote(host, command, progress.handle)
    finally:
        console.stop_spinner()
    if status == 2 or (status != 0 and progress.unreachable):
        console.warning("Mission Control was not reachable; fleet restart skipped.")
        return []
    if status != 0 or not progress.done:
        raise DeployError(progress.error or "Fleet restart helper did not complete; check the remote MC log.")
    failures = progress.failures
    if failures:
        console.warning(f"Fleet restart finished with {len(failures)} failure(s).")
    else:
        console.success("Fleet restart complete: all running instances are on the deployed version.")
    return failures


def deploy(
    host: str, server_name: str, root: str, dirty: bool, *,
    force: bool = False, force_restart: bool = False, console: Console | None = None,
    content_path: Path | str | None = None,
) -> str:
    """Package and deploy a version, returning its label."""

    console = console or CONSOLE
    total_steps = 12 if force_restart else 11
    step = 0

    def phase(title: str) -> None:
        nonlocal step
        step += 1
        console.phase(step, total_steps, title)

    phase("Verifying working tree")
    if not dirty and git_dirty():
        raise DeployError("Uncommitted tracked changes detected. Commit them or pass --dirty.")

    phase("Preparing remote host")
    with console.spinner("Checking remote prerequisites", "Remote tooling ready"):
        check_remote_prerequisites(host)
    with console.spinner("Creating deployment directories", "Directories ready"):
        ensure_dirs(host, root)
    with console.spinner("Ensuring Python environment", "Python environment ready"):
        ensure_python_env(host, root)

    phase("Configuring service registry and nginx")
    with console.spinner("Writing service registry", "Service registry ready"):
        registry = write_services(host, root)
    with console.spinner("Configuring nginx"):
        ensure_nginx(host, server_name, root, registry, console=console)

    phase("Selecting release version")
    with console.spinner("Reading newest recorded version"):
        version = current_version()
    with console.spinner("Selecting deployment content"):
        try:
            selection = load_content_selection(content_path or DEFAULT_CONTENT_FILE)
        except ContentConfigError as exc:
            raise DeployError(str(exc)) from exc
        version_hash = content_hash(selection)
    with console.spinner("Checking for existing artifacts"):
        clashes = existing_artifacts(host, root, version, version_hash)
    if clashes and not force:
        raise DeployError(
            f"Version {version} already exists ({'; '.join(clashes)}). "
            "Pass --force to overwrite it."
        )
    if force and clashes:
        console.warning(f"Overwriting existing artifacts for version {version}.")
    console.info(
        f"Deploying version {version} (content hash {version_hash[:12]}): "
        f"{len(selection.worlds)} world(s), {len(selection.mods)} mod(s), "
        f"{len(selection.cardsets)} cardset(s), {len(selection.propsets)} propset(s)"
    )

    phase("Packaging release")
    tarball_name = package_filename(version, version_hash)
    with console.spinner(f"Packing {tarball_name}"):
        tarball = package(
            version, dirty, console=console,
            selection=selection, version_hash=version_hash,
        )

    phase("Uploading release")
    upload_release(host, root, version, tarball, overwrite=True, console=console)

    phase("Installing dependencies")
    with console.spinner(f"Installing requirements for {version}", f"Requirements installed for {version}"):
        install_requirements(host, root, version)

    phase("Activating release")
    with console.spinner(f"Pointing versions/latest at {version}", f"versions/latest now points at {version}"):
        run_remote(host, f"ln -sfn {remote_path(root, 'versions', version)} {remote_path(root, 'versions', 'latest')}")

    fleet_failures: list[str] = []
    if force_restart:
        phase("Force restarting running instances")
        fleet_failures = force_restart_fleet(host, root, version, console=console)

    phase("Writing environment and keepalive")
    with console.spinner("Writing mission-control environment", "Environment ready"):
        write_admin_env(host, root, server_name, registry)
    with console.spinner("Installing keepalive", "Keepalive installed"):
        ensure_keepalive(host, root)

    phase("Restarting Mission Control")
    with console.spinner("Restarting Mission Control", "Mission Control restarted"):
        restart_admin(host, root)

    phase("Verifying Mission Control")
    with console.spinner(f"Waiting for version {version}", f"Mission Control {version} is ready"):
        wait_for_admin(host, root, int(registry[ADMIN_SERVICE]["port"]), version)
    if fleet_failures:
        raise DeployError(f"Deployed version {version}, but force restart failed for: {', '.join(fleet_failures)}")
    console.success(f"Deployed version {version}; Mission Control is ready at https://{server_name}/")
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


def ensure_nginx(host: str, server_name: str, root: str, registry: dict[str, dict[str, object]],
                 console: Console | None = None) -> None:
    """Install nginx if needed and write the Tinyrooms site configuration."""

    console = console or CONSOLE
    result = run_remote(
        host,
        "{ command -v nginx || test -x /usr/sbin/nginx; } >/dev/null 2>&1 && echo yes || echo no",
        check=False,
    )
    if result.stdout.strip() != "yes":
        console.info("Installing nginx via apt...")
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
    console.info("nginx configured.")


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
    parser.add_argument(
        "--content",
        type=Path,
        default=REPO_ROOT / DEFAULT_CONTENT_FILE,
        help=f"Deployment content file (default: {DEFAULT_CONTENT_FILE}).",
    )
    parser.add_argument("--dirty", action="store_true", help="Package with uncommitted changes (skip the clean-tree check).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite a local or remote artifact that already uses the deployed version.",
    )
    parser.add_argument(
        "--force-restart",
        "--forcerestart",
        action="store_true",
        help="After activating the release, update every running spawned instance to the "
             "deployed version and restart it before restarting Mission Control.",
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
    console = Console()
    try:
        ssh_target, server_name = resolve_target(args.host, args.user)
        root = resolve_root(ssh_target, args.rootdir)
        console.info(f"Deploying to {ssh_target} ({root})")
        deploy(ssh_target, server_name, root, args.dirty, force=args.force,
               force_restart=args.force_restart, console=console,
               content_path=args.content)
    except DeployError as exc:
        console.error(f"deploy: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
