"""Configuration loading and validation for the Tinyrooms backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_FEATURE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MOD_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_BASE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
MC_FEATURE_ALIASES = frozenset({"mission-control", "mission_control"})
# MC aliases select the launcher process; they are not needed to enroll a world.
# Editor flags enable routes, not powers: world-editor/card-database still require
# builder, game-master, or admin; prop-editor requires admin.
# Cutscenes have no subsystem flag; reduced motion suppresses client playback.
KNOWN_FEATURES = frozenset(
    {
        "dev-sample-activity",
        "dev_sample_activity",
        "world-editor",
        "card-database",
        "prop-editor",
        *MC_FEATURE_ALIASES,
    }
)


def selects_mission_control(raw_value: str) -> bool:
    """Return True when a raw feature list contains a mission-control alias."""

    normalized = {
        part.strip().lower().replace("_", "-")
        for part in raw_value.split(",")
        if part.strip()
    }
    return "mission-control" in normalized


def compute_allowed_origins(host: str, port: int) -> tuple[str, ...]:
    """Return allowed browser origins for a listener address and port."""

    if host in {"0.0.0.0", "::"}:
        hosts = {"127.0.0.1", "localhost"}
    else:
        hosts = {host}
    if host == "127.0.0.1":
        hosts.add("localhost")
    if host == "localhost":
        hosts.add("127.0.0.1")
    return tuple(sorted(f"https://{candidate}:{port}" for candidate in hosts))


def parse_bool(raw_value: str) -> bool:
    """Parse a loose environment boolean flag."""

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_base_path(raw_value: str) -> str:
    """Validate and normalize a URL base path, returning empty for the root."""

    value = raw_value.strip()
    if value in {"", "/"}:
        return ""
    if not value.startswith("/"):
        value = f"/{value}"
    value = value.rstrip("/")
    if not _BASE_PATH_PATTERN.match(value) or any(part in {".", ".."} for part in value.split("/")):
        raise ConfigError(f"Invalid base path '{raw_value}'.")
    return value


def parse_origins(raw_value: str) -> tuple[str, ...]:
    """Parse a comma-separated list of additional allowed browser origins."""

    origins: list[str] = []
    for item in raw_value.split(","):
        text = item.strip().rstrip("/")
        if not text:
            continue
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"Invalid public origin '{item.strip()}'.")
        if text not in origins:
            origins.append(text)
    return tuple(origins)


def validate_public_url(raw_value: str, label: str) -> str | None:
    """Validate an optional absolute browser URL without credentials or fragments."""

    value = raw_value.strip().rstrip("/")
    if not value:
        return None
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigError(f"Invalid {label} '{raw_value}'.") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or any(character.isspace() for character in value) or "\\" in value
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or (port is not None and not 1 <= port <= 65535)):
        raise ConfigError(f"Invalid {label} '{raw_value}'.")
    return value


def validate_instance_id(raw_value: str) -> str | None:
    """Validate an optional stable, filesystem-safe mission-control identity."""

    value = raw_value.strip()
    if not value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ConfigError(f"Invalid mission-control instance id '{raw_value}'.")
    return value


class ConfigError(ValueError):
    """Raised when configuration is invalid."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Validated application configuration."""

    repo_root: Path
    local_path: Path
    drafts_path: Path
    revisions_path: Path
    # Contains profiles.sqlite3; MC entry and participating worlds must share it.
    users_path: Path
    # Authored YAML/assets, separate from the mutable SQLite worldstate file.
    world_path: Path
    worldstate_path: Path
    # Rendered player stickers, separate from bundled preset artwork.
    custom_stickers_path: Path
    # Bundled/search roots for propsets and prop-effect definitions/sprites.
    propsets_path: Path
    fx_path: Path
    # Invitation for registration only; changing it does not affect existing accounts.
    new_account_passphrase: str
    features: frozenset[str]
    # Case-folded usernames granted the admin power by PowersService.
    bootstrap_admins: frozenset[str]
    # IANA game-calendar timezone for daily tasks and dated memories.
    timezone_name: str
    timezone: ZoneInfo
    host: str
    port: int
    tick_seconds: float = 1.0
    mods: frozenset[str] = frozenset()
    mods_path: Path | None = None
    # Deploy root: cardsets/ and propsets/ override bundled ids; duplicates within
    # one root and collisions with world-local definitions remain errors.
    # World selection is separate, via world_path rather than this root's worlds/.
    shared_content_path: Path | None = None
    # Browser WebRTC peer-audio ICE URLs; an explicitly empty list supplies no servers.
    stun_urls: tuple[str, ...] = ("stun:stun.l.google.com:19302",)
    # MC host:port (no scheme); enables registration/heartbeats and token-gated
    # world /api/mc/* routes. Management outages do not stop gameplay.
    mc_endpoint: str | None = None
    mc_token: str | None = None
    # Display label only; registration derives world_id@host:port when omitted.
    mc_name: str | None = None
    # Outbound management TLS trust for MC, not the world's browser certificate.
    # Use normal trust without a CA override; dev-only insecure TLS takes precedence.
    mc_ca_file: Path | None = None
    mc_insecure_tls: bool = False
    # Optional URL prefix, normalized to empty at root; public origins add to the
    # listener-derived Origin allowlist rather than changing the bind address.
    base_path: str = ""
    public_origins: tuple[str, ...] = ()
    # Durable identity, distinct from world id/display name, advertised by /health
    # and saved in player destinations. MC supplies it to children; external entry
    # destinations must set it too. A transient registry id cannot satisfy health.
    # Entry resolves the exact saved instance; only legacy profiles lacking one
    # may match a unique world, never silently falling back to the default.
    mc_instance_id: str | None = None
    # Browser destination, separate from the management endpoint; registration
    # derives the world listener URL + base_path when omitted. Parsing allows
    # HTTP, but MC player entry requires HTTPS on entry's hostname to share cookies.
    client_url: str | None = None
    # Root-page redirect for unauthenticated or wrong-world/instance profiles;
    # legacy profiles without an instance id may pass a matching world check.
    entry_url: str | None = None

    @property
    def app_path(self) -> Path:
        """Return the frontend application directory."""

        return self.repo_root / "app"

    @property
    def activities_path(self) -> Path:
        """Return the activities directory."""

        return self.repo_root / "activities"

    @property
    def cutscenes_path(self) -> Path:
        """Return the core cutscene script directory."""

        return self.repo_root / "data" / "cutscenes"

    @property
    def stickers_path(self) -> Path:
        """Return the stickers directory."""

        return self.repo_root / "data" / "stickers"

    @property
    def cardsets_path(self) -> Path:
        """Return the global cardsets directory."""

        return self.repo_root / "data" / "cardsets"

    @property
    def shared_cardsets_path(self) -> Path | None:
        """Return the shared cardsets directory, if a shared root is configured."""

        return None if self.shared_content_path is None else self.shared_content_path / "cardsets"

    @property
    def shared_propsets_path(self) -> Path | None:
        """Return the shared propsets directory, if a shared root is configured."""

        return None if self.shared_content_path is None else self.shared_content_path / "propsets"

    @property
    def is_wildcard_bind(self) -> bool:
        """Return True when bound to all interfaces (LAN access)."""

        return self.host in {"0.0.0.0", "::"}

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        """Return allowed browser origins for this server."""

        return tuple(
            dict.fromkeys(
                (*compute_allowed_origins(self.host, self.port), *self.public_origins)
            )
        )

    @property
    def ice_servers(self) -> list[dict[str, object]]:
        """Return browser-facing ICE server descriptors for WebRTC."""

        if not self.stun_urls:
            return []
        return [{"urls": list(self.stun_urls)}]


def parse_features(raw_value: str) -> frozenset[str]:
    """Parse case-sensitive known flags; planned dynamic_peeps is not accepted.

    Both dev_sample_activity and dev-sample-activity enable sample activities.
    """

    features: set[str] = set()
    for item in raw_value.split(","):
        feature = item.strip()
        if not feature:
            continue
        if not _FEATURE_PATTERN.match(feature):
            raise ConfigError(f"Invalid feature flag '{feature}'.")
        if feature not in KNOWN_FEATURES:
            raise ConfigError(f"Unsupported feature flag '{feature}'.")
        features.add(feature)
    return frozenset(features)


def parse_mods(raw_value: str) -> frozenset[str]:
    """Parse a comma-separated mod list; ``*`` selects every installed mod."""

    mods: set[str] = set()
    for item in raw_value.split(","):
        mod = item.strip()
        if not mod:
            continue
        if mod == "*":
            mods.add("*")
            continue
        if not _MOD_PATTERN.match(mod):
            raise ConfigError(f"Invalid mod name '{mod}'.")
        mods.add(mod)
    return frozenset(mods)


def parse_ice_urls(raw_value: str) -> tuple[str, ...]:
    """Parse a comma-separated list of STUN/TURN URLs."""

    urls: list[str] = []
    for item in raw_value.split(","):
        url = item.strip()
        if not url:
            continue
        if not url.lower().startswith(("stun:", "stuns:", "turn:", "turns:")):
            raise ConfigError(f"Invalid ICE server URL '{url}'.")
        urls.append(url)
    return tuple(urls)


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
    drafts_path = local_path / "drafts"
    drafts_path.mkdir(parents=True, exist_ok=True)
    revisions_path = local_path / "revisions"
    revisions_path.mkdir(parents=True, exist_ok=True)

    passphrase = values.get("TRSERVER_NEW_ACCOUNT_PASSPHRASE", "").strip()
    if not passphrase:
        raise ConfigError("TRSERVER_NEW_ACCOUNT_PASSPHRASE must be set.")

    users_path = Path(values.get("TRSERVER_USERS_PATH", str(root / "users"))).expanduser()
    users_path.mkdir(parents=True, exist_ok=True)

    # Accept a world directory or a file inside it; the directory needs world.yaml.
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

    custom_stickers_value = values.get("TRSERVER_CUSTOM_STICKERS_PATH", str(local_path / "stickers"))
    custom_stickers_path = Path(custom_stickers_value).expanduser()
    custom_stickers_path.mkdir(parents=True, exist_ok=True)
    if custom_stickers_path.exists() and not custom_stickers_path.is_dir():
        raise ConfigError(f"TRSERVER_CUSTOM_STICKERS_PATH must be a directory: {custom_stickers_path}")

    propsets_path = Path(
        values.get("TRSERVER_PROPSETS_PATH", str(root / "data" / "propsets"))
    ).expanduser().resolve()
    fx_path = Path(
        values.get("TRSERVER_FX_PATH", str(root / "data" / "fx"))
    ).expanduser().resolve()

    feature_value = values.get("TRSERVER_FEATURES", "")
    features = parse_features(feature_value)

    admin_value = values.get("TRSERVER_ADMINS", "")
    bootstrap_admins = frozenset(
        entry.strip().casefold() for entry in admin_value.split(",") if entry.strip()
    )

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

    tick_raw = values.get("TRSERVER_TICK_SECONDS", "1.0").strip()
    try:
        tick_seconds = float(tick_raw)
    except ValueError as exc:
        raise ConfigError(f"TRSERVER_TICK_SECONDS must be a number, got '{tick_raw}'.") from exc
    if tick_seconds <= 0:
        raise ConfigError(f"TRSERVER_TICK_SECONDS must be positive, got {tick_seconds}.")

    mods = parse_mods(values.get("TRSERVER_MODS", ""))
    mods_path = Path(values.get("TRSERVER_MODS_PATH", str(root / "mods"))).expanduser().resolve()
    if mods and not mods_path.is_dir():
        raise ConfigError(f"TRSERVER_MODS_PATH does not exist: {mods_path}")

    shared_raw = values.get("TRSERVER_SHARED_CONTENT_PATH", "").strip()
    shared_content_path = Path(shared_raw).expanduser().resolve() if shared_raw else None

    stun_urls = parse_ice_urls(
        values.get("TRSERVER_STUN_URLS", "stun:stun.l.google.com:19302")
    )

    mc_endpoint = values.get("TRSERVER_MC_ENDPOINT", "").strip() or None
    mc_token = values.get("TRSERVER_MC_TOKEN", "").strip() or None
    mc_name = values.get("TRSERVER_MC_NAME", "").strip() or None
    if mc_endpoint is not None and mc_token is None:
        raise ConfigError("TRSERVER_MC_TOKEN must be set when TRSERVER_MC_ENDPOINT is set.")
    mc_ca_raw = values.get("TRSERVER_MC_CA_FILE", "").strip()
    mc_ca_file = Path(mc_ca_raw).expanduser().resolve() if mc_ca_raw else None
    mc_insecure_tls = parse_bool(values.get("TRSERVER_MC_INSECURE_TLS", "0"))

    base_path = normalize_base_path(values.get("TRSERVER_BASE_PATH", ""))
    public_origins = parse_origins(values.get("TRSERVER_PUBLIC_ORIGIN", ""))
    mc_instance_id = validate_instance_id(values.get("TRSERVER_MC_INSTANCE_ID", ""))
    client_url = validate_public_url(values.get("TRSERVER_CLIENT_URL", ""), "TRSERVER_CLIENT_URL")
    entry_url = validate_public_url(values.get("TRSERVER_ENTRY_URL", ""), "TRSERVER_ENTRY_URL")

    return AppConfig(
        repo_root=root,
        local_path=local_path,
        drafts_path=drafts_path,
        revisions_path=revisions_path,
        users_path=users_path.resolve(),
        world_path=world_path.resolve(),
        worldstate_path=worldstate_path.resolve(),
        custom_stickers_path=custom_stickers_path.resolve(),
        propsets_path=propsets_path,
        fx_path=fx_path,
        new_account_passphrase=passphrase,
        features=features,
        bootstrap_admins=bootstrap_admins,
        timezone_name=timezone_name,
        timezone=timezone,
        host=host,
        port=port,
        tick_seconds=tick_seconds,
        mods=mods,
        mods_path=mods_path,
        shared_content_path=shared_content_path,
        stun_urls=stun_urls,
        mc_endpoint=mc_endpoint,
        mc_token=mc_token,
        mc_name=mc_name,
        mc_ca_file=mc_ca_file,
        mc_insecure_tls=mc_insecure_tls,
        base_path=base_path,
        public_origins=public_origins,
        mc_instance_id=mc_instance_id,
        client_url=client_url,
        entry_url=entry_url,
    )
