"""Configuration loading and validation for the Tinyrooms backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_FEATURE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_KNOWN_FEATURES = frozenset(
    {
        "dev-sample-activity",
        "dev_sample_activity",
        "world-editor",
        "world-server",
    }
)


class ConfigError(ValueError):
    """Raised when configuration is invalid."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Validated application configuration."""

    repo_root: Path
    local_path: Path
    users_path: Path
    world_path: Path
    worldstate_path: Path
    new_account_passphrase: str
    features: frozenset[str]
    timezone_name: str
    timezone: ZoneInfo
    host: str
    port: int

    @property
    def app_path(self) -> Path:
        """Return the frontend application directory."""

        return self.repo_root / "app"

    @property
    def activities_path(self) -> Path:
        """Return the activities directory."""

        return self.repo_root / "activities"

    @property
    def stickers_path(self) -> Path:
        """Return the stickers directory."""

        return self.repo_root / "data" / "stickers"

    @property
    def cardsets_path(self) -> Path:
        """Return the global cardsets directory."""

        return self.repo_root / "data" / "cardsets"

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        """Return allowed browser origins for this server."""

        hosts = {self.host}
        if self.host in {"0.0.0.0", "::"}:
            hosts.update({"127.0.0.1", "localhost"})
        if self.host == "127.0.0.1":
            hosts.add("localhost")
        if self.host == "localhost":
            hosts.add("127.0.0.1")
        return tuple(sorted(f"https://{host}:{self.port}" for host in hosts))


def parse_features(raw_value: str) -> frozenset[str]:
    """Parse a comma-separated feature list."""

    features: set[str] = set()
    for item in raw_value.split(","):
        feature = item.strip()
        if not feature:
            continue
        if not _FEATURE_PATTERN.match(feature):
            raise ConfigError(f"Invalid feature flag '{feature}'.")
        if feature not in _KNOWN_FEATURES:
            raise ConfigError(f"Unsupported feature flag '{feature}'.")
        features.add(feature)
    return frozenset(features)


def ensure_contained(path: Path, root: Path, label: str) -> Path:
    """Resolve *path* and ensure it stays beneath *root*."""

    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_root == resolved_path or resolved_root in resolved_path.parents:
        return resolved_path
    raise ConfigError(f"{label} path escapes its configured root: {resolved_path}")


def load_config(env: dict[str, str] | None = None, repo_root: Path | None = None) -> AppConfig:
    """Load and validate configuration from environment variables."""

    values = dict(os.environ if env is None else env)
    root = Path(repo_root or Path(__file__).resolve().parent.parent).resolve()
    local_path = root / ".local"
    local_path.mkdir(parents=True, exist_ok=True)

    passphrase = values.get("TRSERVER_NEW_ACCOUNT_PASSPHRASE", "").strip()
    if not passphrase:
        raise ConfigError("TRSERVER_NEW_ACCOUNT_PASSPHRASE must be set.")

    users_path = Path(values.get("TRSERVER_USERS_PATH", str(root / "users"))).expanduser()
    users_path.mkdir(parents=True, exist_ok=True)
    if not users_path.is_dir():
        raise ConfigError(f"TRSERVER_USERS_PATH must be a directory: {users_path}")

    world_value = values.get("TRSERVER_WORLD_PATH", str(root / "worlds" / "tutorial"))
    world_path = Path(world_value).expanduser()
    if world_path.is_file():
        world_path = world_path.parent
    if not world_path.exists() or not world_path.is_dir():
        raise ConfigError(f"TRSERVER_WORLD_PATH does not exist: {world_path}")
    if not (world_path / "world.yaml").is_file():
        raise ConfigError(f"TRSERVER_WORLD_PATH must contain world.yaml: {world_path}")

    worldstate_value = values.get("TRSERVER_WORLDSTATE_PATH", str(local_path / "worldstate.sqlite3"))
    worldstate_path = Path(worldstate_value).expanduser()
    worldstate_path.parent.mkdir(parents=True, exist_ok=True)
    if worldstate_path.exists() and worldstate_path.is_dir():
        raise ConfigError(f"TRSERVER_WORLDSTATE_PATH must be a file path: {worldstate_path}")

    feature_value = values.get("TRSERVER_FEATURES", "")
    features = parse_features(feature_value)

    timezone_name = values.get("TRSERVER_TIMEZONE", "UTC").strip()
    if not timezone_name:
        raise ConfigError("TRSERVER_TIMEZONE must be set.")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Invalid TRSERVER_TIMEZONE value '{timezone_name}'.") from exc

    host = values.get("TRSERVER_HOST", "127.0.0.1").strip()
    if not host:
        raise ConfigError("TRSERVER_HOST must be set.")
    port_raw = values.get("TRSERVER_PORT", "5000").strip()
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigError(f"TRSERVER_PORT must be an integer, got '{port_raw}'.") from exc
    if not 1 <= port <= 65535:
        raise ConfigError(f"TRSERVER_PORT must be between 1 and 65535, got {port}.")

    return AppConfig(
        repo_root=root,
        local_path=local_path,
        users_path=users_path.resolve(),
        world_path=world_path.resolve(),
        worldstate_path=worldstate_path.resolve(),
        new_account_passphrase=passphrase,
        features=features,
        timezone_name=timezone_name,
        timezone=timezone,
        host=host,
        port=port,
    )
