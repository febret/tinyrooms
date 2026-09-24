"""Discovery, validation, and loading of server mods.

A mod is a directory under the mods path containing a ``mod.yaml`` manifest.
It may contribute world content (``content/``), a single props set
(``props/props.yaml``, like a world), activity iframes (``activities/``), and
Python behaviour via an entrypoint (``mod.py`` by default) exposing
``register(api)``.

Enabled mods come from ``TRSERVER_MODS`` (comma-separated names, or ``*`` for
every installed mod); the search root comes from ``TRSERVER_MODS_PATH``
(default ``./mods``). Worlds declare the mods they need through
``requires_mods`` in ``world.yaml``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import importlib.util
import re
import sys
from pathlib import Path
import types

from server.config import AppConfig, ConfigError, KNOWN_FEATURES
from server.content.activities import ActivityDefinition, load_activity_definitions
from server.content.common import ContentError, load_yaml_file, require_mapping


_MOD_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class ModDefinition:
    """A validated mod manifest."""

    id: str
    label: str
    path: Path
    requires: tuple[str, ...] = ()
    entrypoint: str = "mod.py"

    @property
    def activities_path(self) -> Path:
        """Return the mod's activity iframe directory."""

        return self.path / "activities"

    @property
    def props_path(self) -> Path:
        """Return the mod's single props directory (``props/props.yaml``)."""

        return self.path / "props"

    @property
    def content_path(self) -> Path:
        """Return the mod's content directory."""

        return self.path / "content"


class ModAPI:
    """Registration surface handed to a mod's ``register(api)`` entrypoint."""

    def __init__(self, mod: ModDefinition) -> None:
        self.mod = mod
        self._commands: list[dict[str, object]] = []
        self._state_factories: list[Callable[[object], object]] = []

    def register_command(
        self,
        name: str,
        summary: str,
        handler: Callable[..., object],
        *,
        usage: str = "",
        power: str | None = None,
        help: str = "",
        toast: bool = True,
        log: bool = True,
    ) -> None:
        """Register a ``.`` command contributed by the mod."""

        self._commands.append(
            {
                "name": name,
                "summary": summary,
                "handler": handler,
                "usage": usage,
                "power": power,
                "help": help,
                "toast": toast,
                "log": log,
            }
        )

    def register_state_factory(self, factory: Callable[[object], object]) -> None:
        """Register a factory that builds the mod's runtime state object."""

        self._state_factories.append(factory)

    @property
    def commands(self) -> tuple[dict[str, object], ...]:
        """Return the mod's registered command specifications."""

        return tuple(self._commands)

    @property
    def state_factories(self) -> tuple[Callable[[object], object], ...]:
        """Return the mod's registered state factories."""

        return tuple(self._state_factories)


@dataclass(frozen=True, slots=True)
class LoadedMods:
    """The resolved set of enabled mods and their contributions."""

    definitions: tuple[ModDefinition, ...] = ()
    apis: tuple[ModAPI, ...] = ()
    activity_definitions: dict[str, ActivityDefinition] = field(default_factory=dict)

    @property
    def ids(self) -> frozenset[str]:
        """Return the enabled mod ids."""

        return frozenset(mod.id for mod in self.definitions)

    def mod_props(self) -> tuple[tuple[str, Path], ...]:
        """Return ``(mod_id, props_dir)`` for every mod with a props.yaml."""

        return tuple(
            (mod.id, mod.props_path)
            for mod in self.definitions
            if (mod.props_path / "props.yaml").is_file()
        )

    def command_specs(self) -> list[dict[str, object]]:
        """Return every mod-registered command specification."""

        return [spec for api in self.apis for spec in api.commands]

    def state_factories(self) -> list[tuple[str, Callable[[object], object]]]:
        """Return ``(mod_id, factory)`` pairs in load order."""

        return [
            (api.mod.id, factory)
            for api in self.apis
            for factory in api.state_factories
        ]


def discover_mods(mods_path: Path | None) -> dict[str, ModDefinition]:
    """Discover mod manifests under a directory, keyed by mod id."""

    if mods_path is None or not mods_path.is_dir():
        return {}
    mods: dict[str, ModDefinition] = {}
    for manifest in sorted(mods_path.glob("*/mod.yaml")):
        definition = _load_manifest(manifest)
        if definition.id in mods:
            raise ContentError(f"Duplicate mod id '{definition.id}' under {mods_path}.")
        mods[definition.id] = definition
    return mods


def _load_manifest(manifest: Path) -> ModDefinition:
    payload = require_mapping(load_yaml_file(manifest), manifest)
    default_id = manifest.parent.name
    mod_id = str(payload.get("id", default_id)).strip() or default_id
    if not _MOD_ID.match(mod_id):
        raise ContentError(f"Mod '{manifest}' has an invalid id '{mod_id}'.")
    raw_requires = payload.get("requires", []) or []
    if not isinstance(raw_requires, list):
        raise ContentError(f"Mod '{mod_id}' requires must be a list.")
    requires: list[str] = []
    for entry in raw_requires:
        name = str(entry).strip()
        if not _MOD_ID.match(name):
            raise ContentError(f"Mod '{mod_id}' requires an invalid mod name '{entry}'.")
        if name not in requires:
            requires.append(name)
    entrypoint = str(payload.get("entrypoint", "mod.py")).strip() or "mod.py"
    return ModDefinition(
        id=mod_id,
        label=str(payload.get("label", mod_id)).strip() or mod_id,
        path=manifest.parent.resolve(),
        requires=tuple(requires),
        entrypoint=entrypoint,
    )


def resolve_mods(config: AppConfig) -> tuple[ModDefinition, ...]:
    """Resolve the configured mod names against installed manifests."""

    if not config.mods:
        return ()
    available = discover_mods(config.mods_path)
    if "*" in config.mods:
        selected = set(available)
    else:
        selected = set(config.mods)
    missing = sorted(selected - set(available))
    if missing:
        raise ConfigError(f"Unknown mod(s) {missing} in {config.mods_path}.")
    resolved: dict[str, ModDefinition] = {}
    pending = list(selected)
    while pending:
        mod_id = pending.pop()
        if mod_id in resolved:
            continue
        mod = available[mod_id]
        resolved[mod_id] = mod
        for required in mod.requires:
            if required not in available:
                raise ConfigError(f"Mod '{mod_id}' requires missing mod '{required}'.")
            pending.append(required)
    return tuple(resolved[mod_id] for mod_id in sorted(resolved))


def load_mod_module(mod: ModDefinition) -> types.ModuleType:
    """Import a mod's Python entrypoint from its file path."""

    module_name = f"tinyrooms_mod_{mod.id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, mod.path / mod.entrypoint)
    if spec is None or spec.loader is None:
        raise ConfigError(f"Mod '{mod.id}' has no loadable entrypoint '{mod.entrypoint}'.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_mod_activity_definitions(
    mods: Iterable[ModDefinition],
    *,
    known_features: frozenset[str] = KNOWN_FEATURES,
) -> dict[str, ActivityDefinition]:
    """Load each mod's optional ``content/activities.yaml``."""

    definitions: dict[str, ActivityDefinition] = {}
    for mod in mods:
        path = mod.content_path / "activities.yaml"
        if not path.is_file():
            continue
        loaded = load_activity_definitions(path, source=mod.id, known_features=known_features)
        for activity_id, definition in loaded.items():
            if activity_id in definitions:
                raise ContentError(f"Duplicate mod activity id '{activity_id}'.")
            definitions[activity_id] = definition
    return definitions


def load_mods(config: AppConfig) -> LoadedMods:
    """Resolve, import, and register every enabled mod."""

    definitions = resolve_mods(config)
    apis: list[ModAPI] = []
    for mod in definitions:
        api = ModAPI(mod)
        if (mod.path / mod.entrypoint).is_file():
            module = load_mod_module(mod)
            register = getattr(module, "register", None)
            if register is not None:
                register(api)
        apis.append(api)
    return LoadedMods(
        definitions=definitions,
        apis=tuple(apis),
        activity_definitions=load_mod_activity_definitions(definitions),
    )
