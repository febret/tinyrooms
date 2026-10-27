"""Launch a local multi-world Tinyrooms fleet described by multiworld.json."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import json
import os
import re
import signal
import ssl
import subprocess
import sys
import time
import urllib.request


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "multiworld.json"
DEFAULT_MC_PORT = 8001
DEFAULT_MC_PORT_MIN = 5100
DEFAULT_MC_PORT_MAX = 5199
DEFAULT_WORLD_FEATURES = (
    "dev_sample_activity,world-editor,card-database,prop-editor,"
    "cutscene-catalog,asset-bakery"
)
DEFAULT_WORLD_PORTS = {
    "tutorial": 5100,
    "scammon-academia": 5101,
    "tiny-arcade": 5102,
    "tinytown": 5103,
    "tiny-backrooms": 5104,
    "tiny-vault": 5105,
    "bobs-burgers": 5106,
}
DEFAULT_INSTANCE_IDS = {
    "tutorial": "tutorial-1",
    "scammon-academia": "scammon-1",
    "tiny-arcade": "arcade-1",
    "tinytown": "tinytown-1",
    "tiny-backrooms": "backrooms-1",
    "tiny-vault": "vault-1",
    "bobs-burgers": "bobs-1",
}
LEGACY_PORT_ENV = {
    "tutorial": "TUTORIAL_PORT",
    "scammon-academia": "SCAMMON_PORT",
    "tiny-arcade": "ARCADE_PORT",
    "tinytown": "TINYTOWN_PORT",
    "tiny-backrooms": "BACKROOMS_PORT",
    "tiny-vault": "VAULT_PORT",
    "bobs-burgers": "BOBS_PORT",
}
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class MultiworldConfigError(ValueError):
    """Raised when multiworld.json or its overrides are invalid."""


@dataclass(frozen=True, slots=True)
class WorldSpec:
    """One world server to launch."""

    world_id: str
    port: int
    instance_id: str
    label: str
    mods: str | None = None
    # Optional world directory override (absolute or relative to the repo
    # root). Lets the fleet run worlds that live outside ``worlds/``, such as
    # contributed worlds in a sibling ``tinyrooms-workshop`` checkout.
    path: str | None = None
    # Optional shared-content root (absolute or relative to the repo root)
    # passed as TRSERVER_SHARED_CONTENT_PATH so the world can bring its own
    # cardsets/propsets/mods.
    shared_content: str | None = None


@dataclass(frozen=True, slots=True)
class MultiworldConfig:
    """Validated multiworld launch configuration."""

    worlds: tuple[WorldSpec, ...]
    mods: str
    default_instance_id: str


def _as_mods(value: Any, context: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        entries: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise MultiworldConfigError(f"{context} must contain non-empty strings.")
            entries.append(item.strip())
        return ",".join(entries)
    raise MultiworldConfigError(f"{context} must be a string or a list of strings.")


def _parse_port(value: Any, context: str) -> int:
    if isinstance(value, bool):
        raise MultiworldConfigError(f"{context} must be an integer port.")
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        try:
            port = int(value.strip())
        except ValueError as exc:
            raise MultiworldConfigError(f"{context} must be an integer port.") from exc
    else:
        raise MultiworldConfigError(f"{context} must be an integer port.")
    if not 1 <= port <= 65535:
        raise MultiworldConfigError(f"{context} must be between 1 and 65535, got {port}.")
    return port


def _port_env_names(world_id: str) -> tuple[str, ...]:
    suffix = re.sub(r"[^A-Z0-9]+", "_", world_id.upper()).strip("_")
    names = [f"MULTIWORLD_{suffix}_PORT"]
    legacy = LEGACY_PORT_ENV.get(world_id)
    if legacy is not None:
        names.append(legacy)
    return tuple(names)


def _world_id(entry: Any, index: int) -> str:
    context = f"worlds[{index}]"
    if isinstance(entry, str):
        world_id = entry.strip()
    elif isinstance(entry, dict):
        raw_id = entry.get("id", entry.get("world"))
        if not isinstance(raw_id, str):
            raise MultiworldConfigError(f"{context} must have a string 'id'.")
        world_id = raw_id.strip()
    else:
        raise MultiworldConfigError(f"{context} must be a world id or an object.")
    if not _ID_PATTERN.match(world_id):
        raise MultiworldConfigError(f"{context} has an invalid world id '{world_id}'.")
    return world_id


def _optional_path(value: Any, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MultiworldConfigError(f"{context} must be a non-empty path string.")
    return value.strip()


def _world_options(entry: Any, index: int) -> tuple[Any, Any, str | None, Any, str | None, str | None]:
    if not isinstance(entry, dict):
        return None, None, None, None, None, None
    context = f"worlds[{index}]"
    port = entry.get("port")
    instance_id = entry.get("instance_id")
    if instance_id is not None and (
        not isinstance(instance_id, str) or not _ID_PATTERN.match(instance_id.strip())
    ):
        raise MultiworldConfigError(f"{context}.instance_id is invalid.")
    label = entry.get("label")
    if label is not None and not isinstance(label, str):
        raise MultiworldConfigError(f"{context}.label must be a string.")
    mods = _as_mods(entry.get("mods"), f"{context}.mods")
    path = _optional_path(entry.get("path"), f"{context}.path")
    shared_content = _optional_path(entry.get("shared_content"), f"{context}.shared_content")
    return port, instance_id, label, mods, path, shared_content


def _next_available_port(used_ports: set[int], start: int = DEFAULT_MC_PORT_MIN) -> int:
    port = start
    while port in used_ports and port <= 65535:
        port += 1
    if port > 65535:
        raise MultiworldConfigError("No free ports remain for the configured worlds.")
    return port


def load_multiworld_config(
    path: Path = DEFAULT_CONFIG_PATH,
    env: dict[str, str] | None = None,
) -> MultiworldConfig:
    """Load and validate a multiworld JSON file, applying environment overrides."""

    values = dict(os.environ if env is None else env)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise MultiworldConfigError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MultiworldConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MultiworldConfigError("The multiworld file must contain a JSON object.")

    configured_mods = _as_mods(payload.get("mods"), "mods")
    if "TRSERVER_MODS" in values:
        mods = values["TRSERVER_MODS"].strip()
    elif configured_mods is not None:
        mods = configured_mods
    else:
        mods = "*"

    entries = payload.get("worlds")
    if not isinstance(entries, list) or not entries:
        raise MultiworldConfigError("'worlds' must be a non-empty list.")

    env_mods = values.get("TRSERVER_MODS")
    worlds: list[WorldSpec] = []
    used_ports: set[int] = set()
    used_worlds: set[str] = set()
    used_instances: set[str] = set()
    for index, entry in enumerate(entries):
        world_id = _world_id(entry, index)
        if world_id in used_worlds:
            raise MultiworldConfigError(f"World '{world_id}' appears more than once.")
        used_worlds.add(world_id)

        (
            explicit_port,
            configured_instance,
            label,
            world_mods,
            world_path,
            shared_content,
        ) = _world_options(entry, index)
        port: int | None = None
        for env_name in _port_env_names(world_id):
            if env_name in values:
                port = _parse_port(values[env_name], env_name)
                break
        if port is None:
            if explicit_port is not None:
                port = _parse_port(explicit_port, f"worlds[{index}].port")
            elif world_id in DEFAULT_WORLD_PORTS:
                port = DEFAULT_WORLD_PORTS[world_id]
            else:
                port = _next_available_port(used_ports)
        if port in used_ports:
            raise MultiworldConfigError(f"Port {port} is assigned to more than one world.")
        used_ports.add(port)

        instance_id = (
            configured_instance.strip()
            if isinstance(configured_instance, str)
            else DEFAULT_INSTANCE_IDS.get(world_id, f"{world_id}-1")
        )
        if instance_id in used_instances:
            raise MultiworldConfigError(f"Instance id '{instance_id}' appears more than once.")
        used_instances.add(instance_id)

        world_label = label.strip() if isinstance(label, str) and label.strip() else world_id
        if env_mods is not None:
            effective_mods = env_mods.strip()
        elif world_mods is not None:
            effective_mods = world_mods
        else:
            effective_mods = mods
        worlds.append(
            WorldSpec(
                world_id=world_id,
                port=port,
                instance_id=instance_id,
                label=world_label,
                mods=effective_mods,
                path=world_path,
                shared_content=shared_content,
            )
        )

    default_instance = payload.get("default_instance_id")
    if default_instance is not None:
        if not isinstance(default_instance, str) or default_instance.strip() not in used_instances:
            raise MultiworldConfigError(
                "'default_instance_id' must name one of the configured world instances."
            )
        default_instance_id = default_instance.strip()
    else:
        default_instance_id = worlds[0].instance_id

    return MultiworldConfig(worlds=tuple(worlds), mods=mods, default_instance_id=default_instance_id)


def _resolve_against_root(value: str, root: Path) -> Path:
    """Resolve a configured path against *root* (absolute paths pass through)."""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate


def world_directory(spec: WorldSpec, root: Path = REPO_ROOT) -> Path:
    """Return the world directory for *spec* (defaults to worlds/<id>)."""

    if spec.path is None:
        return root / "worlds" / spec.world_id
    return _resolve_against_root(spec.path, root)


def shared_content_directory(spec: WorldSpec, root: Path = REPO_ROOT) -> Path | None:
    """Return the shared-content root for *spec*, if one is configured."""

    if spec.shared_content is None:
        return None
    return _resolve_against_root(spec.shared_content, root)


def validate_world_directories(config: MultiworldConfig, root: Path = REPO_ROOT) -> None:
    """Fail before spawning when a configured world definition is missing."""

    missing = [
        spec.world_id
        for spec in config.worlds
        if not (world_directory(spec, root) / "world.yaml").is_file()
    ]
    missing_shared = sorted(
        {
            str(shared_content_directory(spec, root))
            for spec in config.worlds
            if spec.shared_content is not None
            and not shared_content_directory(spec, root).is_dir()
        }
    )
    problems = [f"Missing world.yaml for: {', '.join(sorted(missing))}"] if missing else []
    if missing_shared:
        problems.append("Missing shared content directories: " + ", ".join(missing_shared))
    if problems:
        raise MultiworldConfigError("; ".join(problems))


def wait_for_mission_control(host: str, port: int, process: subprocess.Popen[Any]) -> None:
    """Wait until Mission Control's entry API answers HTTPS requests."""

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    url = f"https://{host}:{port}/api/entry/session"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Mission Control exited before becoming ready on {host}:{port}."
            )
        try:
            with urllib.request.urlopen(url, context=context, timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"Mission Control did not become ready on https://{host}:{port}.")


def _stop_processes(processes: list[subprocess.Popen[Any]], timeout: float = 5.0) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
    deadline = time.monotonic() + timeout
    for process in processes:
        if process.poll() is not None:
            continue
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass
    for process in processes:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


def _wait_for_processes(processes: list[subprocess.Popen[Any]]) -> None:
    while any(process.poll() is None for process in processes):
        time.sleep(0.5)


def _handle_stop(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start a local multi-world Tinyrooms from multiworld.json."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the multiworld JSON file (default: multiworld.json).",
    )
    parser.add_argument(
        "--public-host",
        help="Hostname or IP advertised to browsers; also binds listeners to 0.0.0.0.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env = dict(os.environ)
    config_path = Path(args.config).expanduser()
    try:
        config = load_multiworld_config(config_path, env=env)
        validate_world_directories(config)
        mc_port = _parse_port(env.get("MC_PORT", str(DEFAULT_MC_PORT)), "MC_PORT")
        public_host = (
            args.public_host if args.public_host is not None else env.get("PUBLIC_HOST", "")
        ).strip()
    except MultiworldConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if public_host:
        bind_host = "0.0.0.0"
    else:
        bind_host = "127.0.0.1"
        public_host = "127.0.0.1"
    management_host = "127.0.0.1"

    base_env = env.copy()
    passphrase = env.get("TRSERVER_NEW_ACCOUNT_PASSPHRASE") or "deadbeef"
    base_env["TRSERVER_NEW_ACCOUNT_PASSPHRASE"] = passphrase
    base_env["TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE"] = (
        env.get("TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE") or passphrase
    )
    base_env["TRSERVER_MC_PASSPHRASE"] = env.get("TRSERVER_MC_PASSPHRASE") or "deadbeef"
    base_env["TRSERVER_MC_TOKEN"] = env.get("TRSERVER_MC_TOKEN") or "deadbeef-token"

    root = REPO_ROOT / ".local" / "multiworld"
    users = root / "users"
    instances = root / "mc-instances"
    versions = root / "mc-versions"
    for directory in (users, instances, versions):
        directory.mkdir(parents=True, exist_ok=True)
    (instances / "entry.json").write_text(
        json.dumps({"default_instance_id": config.default_instance_id}) + "\n",
        encoding="utf-8",
    )

    processes: list[subprocess.Popen[Any]] = []
    mc_env = base_env.copy()
    mc_env.update(
        {
            "TRSERVER_FEATURES": "mission-control",
            "TRSERVER_MC_USERS_PATH": str(users),
            "TRSERVER_MC_INSTANCES_PATH": str(instances),
            "TRSERVER_MC_VERSIONS_PATH": str(versions),
            "TRSERVER_MC_INSTANCE_HOST": bind_host,
            "TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME": public_host,
            "TRSERVER_MC_INSTANCE_PORT_MIN": str(DEFAULT_MC_PORT_MIN),
            "TRSERVER_MC_INSTANCE_PORT_MAX": str(DEFAULT_MC_PORT_MAX),
            "TRSERVER_MC_PUBLIC_ORIGIN": f"https://{public_host}:{mc_port}",
            "TRSERVER_MC_INSECURE_TLS": "1",
            "TRSERVER_MODS": config.mods,
        }
    )

    signal.signal(signal.SIGTERM, _handle_stop)
    world_features = env.get("WORLD_FEATURES") or DEFAULT_WORLD_FEATURES
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(REPO_ROOT / "run.py"),
                    "--host",
                    bind_host,
                    "--port",
                    str(mc_port),
                ],
                cwd=REPO_ROOT,
                env=mc_env,
            )
        )
        wait_for_mission_control(management_host, mc_port, processes[0])

        for spec in config.worlds:
            world_env = base_env.copy()
            world_env.update(
                {
                    "TRSERVER_FEATURES": world_features,
                    "TRSERVER_WORLD_PATH": str(world_directory(spec, REPO_ROOT)),
                    "TRSERVER_WORLDSTATE_PATH": str(root / f"{spec.world_id}.sqlite3"),
                    "TRSERVER_USERS_PATH": str(users),
                    "TRSERVER_MC_ENDPOINT": f"{management_host}:{mc_port}",
                    "TRSERVER_MC_TOKEN": base_env["TRSERVER_MC_TOKEN"],
                    "TRSERVER_MC_INSTANCE_ID": spec.instance_id,
                    "TRSERVER_MC_NAME": spec.label,
                    "TRSERVER_CLIENT_URL": f"https://{public_host}:{spec.port}",
                    "TRSERVER_ENTRY_URL": f"https://{public_host}:{mc_port}",
                    "TRSERVER_MC_INSECURE_TLS": "1",
                    "TRSERVER_MODS": spec.mods or "",
                }
            )
            shared_content = shared_content_directory(spec, REPO_ROOT)
            if shared_content is not None:
                world_env["TRSERVER_SHARED_CONTENT_PATH"] = str(shared_content)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(REPO_ROOT / "run.py"),
                        "--host",
                        bind_host,
                        "--port",
                        str(spec.port),
                        "--legacy-features",
                        "svg-boards",
                    ],
                    cwd=REPO_ROOT,
                    env=world_env,
                )
            )

        lines = [
            f"Tinyrooms multiworld is starting (bind {bind_host}, advertised as {public_host}):",
            f"  {'Mission Control':<16}: https://{public_host}:{mc_port}/mission-control",
            f"  {'Player entry':<16}: https://{public_host}:{mc_port}/",
        ]
        for spec in config.worlds:
            lines.append(f"  {spec.label:<16}: https://{public_host}:{spec.port}/")
        lines.append(
            f"Mission Control manages all {len(config.worlds)} worlds; "
            "the Multiverse travels between them."
        )
        lines.append("Press Ctrl-C to stop everything.")
        print("\n".join(lines), flush=True)

        _wait_for_processes(processes)
    except KeyboardInterrupt:
        print("\nStopping Tinyrooms multiworld...", file=sys.stderr)
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        _stop_processes(processes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
