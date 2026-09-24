"""Configuration loading and validation for the mission-control server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import secrets

from server.config import (
    ConfigError,
    compute_allowed_origins,
    parse_bool,
    parse_features,
)


MC_FEATURE = "mission-control"
MC_FEATURE_ALIASES = frozenset({"mission-control", "mission_control"})


@dataclass(frozen=True, slots=True)
class MCConfig:
    """Validated mission-control configuration."""

    repo_root: Path
    host: str
    port: int
    passphrase: str
    token: str
    users_path: Path
    instances_path: Path
    versions_path: Path
    ca_file: Path | None
    insecure_tls: bool
    heartbeat_seconds: float
    actor: str
    new_account_passphrase: str
    features: frozenset[str]
    mods: str = "*"

    @property
    def ui_path(self) -> Path:
        """Return the static mission-control UI directory."""

        return self.repo_root / "mission-control"

    @property
    def profiles_db_path(self) -> Path:
        """Return the managed profile database path."""

        return self.users_path / "profiles.sqlite3"

    @property
    def is_wildcard_bind(self) -> bool:
        """Return True when bound to all interfaces."""

        return self.host in {"0.0.0.0", "::"}

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        """Return allowed browser origins for the mission-control UI."""

        return compute_allowed_origins(self.host, self.port)


def _require(values: dict[str, str], key: str) -> str:
    text = values.get(key, "").strip()
    if not text:
        raise ConfigError(f"{key} must be set.")
    return text


def load_mc_config(
    env: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> MCConfig:
    """Load and validate mission-control configuration."""

    values = dict(os.environ if env is None else env)
    root = Path(repo_root or Path(__file__).resolve().parent.parent.parent).resolve()

    features = parse_features(values.get("TRSERVER_FEATURES", ""))
    if not (features & MC_FEATURE_ALIASES):
        raise ConfigError("Mission control requires TRSERVER_FEATURES to include 'mission-control'.")

    passphrase = _require(values, "TRSERVER_MC_PASSPHRASE")
    token = _require(values, "TRSERVER_MC_TOKEN")

    host = values.get("TRSERVER_MC_HOST", "127.0.0.1").strip()
    if not host:
        raise ConfigError("TRSERVER_MC_HOST must be set.")
    port_raw = values.get("TRSERVER_MC_PORT", "8001").strip()
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigError(f"TRSERVER_MC_PORT must be an integer, got '{port_raw}'.") from exc
    if not 1 <= port <= 65535:
        raise ConfigError(f"TRSERVER_MC_PORT must be between 1 and 65535, got {port}.")

    users_path = Path(values.get("TRSERVER_MC_USERS_PATH", str(root / "users"))).expanduser()
    users_path.mkdir(parents=True, exist_ok=True)

    instances_path = Path(
        values.get("TRSERVER_MC_INSTANCES_PATH", str(root / ".local" / "mc-instances"))
    ).expanduser()
    instances_path.mkdir(parents=True, exist_ok=True)

    versions_path = Path(
        values.get("TRSERVER_MC_VERSIONS_PATH", str(root / ".local" / "mc-versions"))
    ).expanduser()
    versions_path.mkdir(parents=True, exist_ok=True)

    ca_raw = values.get("TRSERVER_MC_CA_FILE", "").strip()
    ca_file = Path(ca_raw).expanduser().resolve() if ca_raw else None
    insecure_tls = parse_bool(values.get("TRSERVER_MC_INSECURE_TLS", "0"))

    heartbeat_raw = values.get("TRSERVER_MC_HEARTBEAT_SECONDS", "5").strip()
    try:
        heartbeat_seconds = float(heartbeat_raw)
    except ValueError as exc:
        raise ConfigError(f"TRSERVER_MC_HEARTBEAT_SECONDS must be a number, got '{heartbeat_raw}'.") from exc
    if heartbeat_seconds <= 0:
        raise ConfigError(f"TRSERVER_MC_HEARTBEAT_SECONDS must be positive, got {heartbeat_seconds}.")

    actor = values.get("TRSERVER_MC_ACTOR", "mission-control").strip() or "mission-control"
    new_account_passphrase = (
        values.get("TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE", "").strip() or secrets.token_urlsafe(16)
    )

    return MCConfig(
        repo_root=root,
        host=host,
        port=port,
        passphrase=passphrase,
        token=token,
        users_path=users_path,
        instances_path=instances_path,
        versions_path=versions_path,
        ca_file=ca_file,
        insecure_tls=insecure_tls,
        heartbeat_seconds=heartbeat_seconds,
        actor=actor,
        new_account_passphrase=new_account_passphrase,
        features=features,
    )
