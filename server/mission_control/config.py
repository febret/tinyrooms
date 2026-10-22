"""Configuration loading and validation for the mission-control server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import os
import secrets

from server.config import (
    MC_FEATURE_ALIASES,
    ConfigError,
    compute_allowed_origins,
    normalize_base_path,
    parse_bool,
    parse_features,
    parse_origins,
)


@dataclass(frozen=True, slots=True)
class MCConfig:
    """Validated mission-control configuration."""

    repo_root: Path
    host: str
    port: int
    # Operator UI login, independent of player invitations/accounts.
    passphrase: str
    # Shared secret for token-authenticated MC <-> world management calls.
    token: str
    # Shared profiles.sqlite3 directory for MC and all player destinations;
    # external worlds need operator verification of the same database setup.
    users_path: Path
    # Durable <id>/instance.json identities/launch settings, entry.json's new-user
    # default, and reboot's resume.json. Restoring identities alone does not spawn.
    instances_path: Path
    # Additional installed code checkouts, independent of shared content.
    versions_path: Path
    # Outside version checkouts: shared worlds/, cardsets/, propsets/, releases/.
    # Inventory detects <id>/world.yaml, cards.yaml (optional pack.yaml), props.yaml
    # in the respective roots; selected shared world ids precede bundled ones.
    content_root: Path
    # Server Info storage-measurement override, not the child code/content root.
    install_path: Path | None
    # Outbound world-management TLS trust, not browser-facing listener certificates.
    # Normal trust applies without a CA; the dev-only insecure switch overrides it.
    ca_file: Path | None
    insecure_tls: bool
    # Negotiated world heartbeat interval; registry staleness is three times this.
    heartbeat_seconds: float
    # Player invitation, also passed to children as TRSERVER_NEW_ACCOUNT_PASSPHRASE.
    # Blank/unset randomizes on every config load; set explicitly to keep it stable.
    # Invitation changes do not invalidate existing accounts.
    new_account_passphrase: str
    features: frozenset[str]
    # Default child mod selection; a start request can override it.
    mods: str = "*"
    # Optional MC URL prefix; independent of direct worlds' saved base paths.
    base_path: str = ""
    # Serve worlds under same-origin paths managed by the generated nginx map.
    same_origin_worlds: bool = False
    # Generated nginx map consumed by the fixed site configuration.
    world_map_path: Path | None = None
    world_map_reload_command: str | None = None
    # Extra Origin allowlist entries; the first also supplies the public entry
    # origin. Direct-world URLs share its hostname so player cookies span ports.
    public_origins: tuple[str, ...] = ()
    # Legacy parsed settings only: no runtime nginx management/reload uses these.
    nginx_conf_path: Path | None = None
    nginx_reload_command: str | None = None
    # Script relaunched after MC exits for Reboot; absence disables that action.
    keepalive_path: Path | None = None
    # Default bind for new worlds, separate from their advertised public hostname.
    # Saved restart/resume settings retain their bind/base path/version selections;
    # changing deployment defaults does not migrate existing launch settings.
    instance_host: str = "127.0.0.1"
    instance_public_hostname: str | None = None
    # Inclusive bounds for automatic allocation and explicit start/resume ports.
    # Resume rejects saved out-of-range ports; Restart reuses saved launch settings.
    instance_port_min: int = 5000
    instance_port_max: int = 5999
    # Paired existing TLS files passed to child run.py, independently of MC's own
    # listener cert. Deployment reuses nginx's certificate/key for direct worlds.
    instance_certfile: Path | None = None
    instance_keyfile: Path | None = None

    @property
    def public_origin(self) -> str:
        """Return the player entry origin, independently of the admin base path."""

        if self.public_origins:
            parsed = urlparse(self.public_origins[0])
            return f"{parsed.scheme}://{parsed.netloc}"
        host = "127.0.0.1" if self.is_wildcard_bind else self.host
        host = f"[{host}]" if ":" in host else host
        return f"https://{host}:{self.port}"

    @property
    def public_instance_hostname(self) -> str:
        """Return the hostname advertised for direct world connections."""

        return self.instance_public_hostname or urlparse(self.public_origin).hostname or "127.0.0.1"

    @property
    def admin_route(self) -> str:
        """Return the URL path segment the mission-control UI is served under."""

        return self.base_path.lstrip("/") or "mission-control"

    @property
    def server_name(self) -> str:
        """Return the public hostname used in the generated nginx config."""

        for origin in self.public_origins:
            hostname = urlparse(origin).hostname
            if hostname:
                return hostname
        return self.host

    @property
    def shared_worlds_root(self) -> Path:
        """Return the shared world-definition root outside any server version."""

        return self.content_root / "worlds"

    @property
    def shared_cardsets_root(self) -> Path:
        """Return the shared cardset root outside any server version."""

        return self.content_root / "cardsets"

    @property
    def shared_propsets_root(self) -> Path:
        """Return the shared propset root outside any server version."""

        return self.content_root / "propsets"

    @property
    def releases_path(self) -> Path:
        """Return the directory of deployed release artifacts."""

        return self.content_root / "releases"

    @property
    def install_root(self) -> Path:
        """Return the Tinyrooms install directory the storage view measures.

        When the running checkout is nested inside the deploy content root (a
        production deploy) the content root is the install; otherwise the
        running checkout itself is the install (local development).
        """

        if self.install_path is not None:
            return self.install_path
        content = self.content_root.resolve()
        repo = self.repo_root.resolve()
        if repo == content or content in repo.parents:
            return content
        return repo

    @property
    def client_path(self) -> Path:
        """Return the browser client directory."""

        return self.repo_root / "client"

    @property
    def ui_path(self) -> Path:
        """Return the static mission-control UI directory."""

        return self.client_path / "mission-control"

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

        return tuple(
            dict.fromkeys(
                (*compute_allowed_origins(self.host, self.port), *self.public_origins)
            )
        )


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

    content_root = Path(
        values.get("TRSERVER_MC_CONTENT_PATH", str(versions_path.parent))
    ).expanduser()

    install_raw = values.get("TRSERVER_MC_INSTALL_PATH", "").strip()
    install_path = Path(install_raw).expanduser() if install_raw else None

    # Supervisor also passes the CA to children for their MC connection; without
    # a CA (or with insecure_tls), it explicitly disables their TLS verification.
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

    new_account_passphrase = (
        values.get("TRSERVER_MC_NEW_ACCOUNT_PASSPHRASE", "").strip() or secrets.token_urlsafe(16)
    )
    base_path = normalize_base_path(values.get("TRSERVER_MC_BASE_PATH", ""))
    public_origins = parse_origins(values.get("TRSERVER_MC_PUBLIC_ORIGIN", ""))

    nginx_conf_raw = values.get("TRSERVER_MC_NGINX_CONF", "").strip()
    nginx_conf_path = Path(nginx_conf_raw).expanduser() if nginx_conf_raw else None
    nginx_reload_command = values.get("TRSERVER_MC_NGINX_RELOAD", "").strip() or None
    same_origin_worlds = parse_bool(values.get("TRSERVER_MC_SAME_ORIGIN_WORLDS", "0"))
    world_map_raw = values.get("TRSERVER_MC_WORLD_MAP", "").strip()
    world_map_path = Path(world_map_raw).expanduser() if world_map_raw else None
    world_map_reload_command = values.get("TRSERVER_MC_WORLD_MAP_RELOAD", "").strip() or None
    if same_origin_worlds and (world_map_path is None or world_map_reload_command is None):
        raise ConfigError(
            "TRSERVER_MC_WORLD_MAP and TRSERVER_MC_WORLD_MAP_RELOAD are required when "
            "TRSERVER_MC_SAME_ORIGIN_WORLDS is enabled."
        )

    keepalive_raw = values.get("TRSERVER_MC_KEEPALIVE", "").strip()
    keepalive_path = Path(keepalive_raw).expanduser() if keepalive_raw else None

    instance_host = values.get("TRSERVER_MC_INSTANCE_HOST", "127.0.0.1").strip()
    if not instance_host or any(character.isspace() for character in instance_host) or "/" in instance_host:
        raise ConfigError("TRSERVER_MC_INSTANCE_HOST must be a bind hostname or address.")
    # Canonical setting wins over the deployment alias, even when explicitly blank.
    # Omission falls back to the entry-origin hostname, without its port/path.
    instance_public_hostname = values.get(
        "TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME", values.get("TRSERVER_MC_INSTANCE_PUBLIC_HOST", "")
    ).strip() or None
    if instance_public_hostname is not None:
        candidate = instance_public_hostname
        authority = f"[{candidate}]" if ":" in candidate else candidate
        try:
            parsed = urlparse(f"https://{authority}")
            valid = parsed.hostname == candidate.lower() and parsed.port is None
        except ValueError:
            valid = False
        if not valid or any(character in candidate for character in "/@?#") or any(character.isspace() for character in candidate):
            raise ConfigError("TRSERVER_MC_INSTANCE_PUBLIC_HOSTNAME must be a hostname without a port or path.")
    try:
        instance_port_min = int(values.get("TRSERVER_MC_INSTANCE_PORT_MIN", "5000"))
        instance_port_max = int(values.get("TRSERVER_MC_INSTANCE_PORT_MAX", "5999"))
    except ValueError as exc:
        raise ConfigError("Mission-control instance port bounds must be integers.") from exc
    if not 1 <= instance_port_min <= instance_port_max <= 65535:
        raise ConfigError("Mission-control instance port bounds must satisfy 1 <= min <= max <= 65535.")
    cert_raw = values.get("TRSERVER_MC_INSTANCE_CERTFILE", "").strip()
    key_raw = values.get("TRSERVER_MC_INSTANCE_KEYFILE", "").strip()
    if bool(cert_raw) != bool(key_raw):
        raise ConfigError("TRSERVER_MC_INSTANCE_CERTFILE and TRSERVER_MC_INSTANCE_KEYFILE must be set together.")
    instance_certfile = Path(cert_raw).expanduser().resolve() if cert_raw else None
    instance_keyfile = Path(key_raw).expanduser().resolve() if key_raw else None
    for path in (instance_certfile, instance_keyfile):
        if path is not None and not path.is_file():
            raise ConfigError(f"Instance TLS file does not exist: {path}")

    return MCConfig(
        repo_root=root,
        host=host,
        port=port,
        passphrase=passphrase,
        token=token,
        users_path=users_path,
        instances_path=instances_path,
        versions_path=versions_path,
        content_root=content_root,
        install_path=install_path,
        ca_file=ca_file,
        insecure_tls=insecure_tls,
        heartbeat_seconds=heartbeat_seconds,
        new_account_passphrase=new_account_passphrase,
        features=features,
        base_path=base_path,
        same_origin_worlds=same_origin_worlds,
        world_map_path=world_map_path,
        world_map_reload_command=world_map_reload_command,
        public_origins=public_origins,
        nginx_conf_path=nginx_conf_path,
        nginx_reload_command=nginx_reload_command,
        keepalive_path=keepalive_path,
        instance_host=instance_host,
        instance_public_hostname=instance_public_hostname,
        instance_port_min=instance_port_min,
        instance_port_max=instance_port_max,
        instance_certfile=instance_certfile,
        instance_keyfile=instance_keyfile,
    )
