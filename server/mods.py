"""Discovery, validation, and loading of server mods.

A mod is a directory under the mods path containing a ``mod.yaml`` manifest.
It may contribute world content (``content/``), a single props set
(``props/props.yaml``, like a world), activity iframes (``activities/``),
client board renderers (``boards/``), and Python behaviour via an entrypoint
(``mod.py`` by default) exposing ``register(api)``.

Enabled mods come from ``TRSERVER_MODS`` (comma-separated names, or ``*`` for
every installed mod); the search root comes from ``TRSERVER_MODS_PATH``
(default ``./mods``). A world's ``shared_content`` root contributes a second
``mods/`` directory so workshop worlds can ship their required mods. Worlds
declare the mods they need through ``requires_mods`` in ``world.yaml``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import importlib.util
from pathlib import PurePosixPath
import re
import sys
from pathlib import Path
import types

from server.config import AppConfig, ConfigError, KNOWN_FEATURES
from server.content.activities import ActivityDefinition, load_activity_definitions
from server.content.common import ContentError, load_yaml_file, require_mapping
from server.content.cutscenes import CutsceneDefinition, load_cutscene_definitions
from server.content.sounds import load_sound_names


_MOD_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_BOARD_DESIGN_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True, slots=True)
class BoardDesignModule:
    """A client board renderer contributed by a mod."""

    name: str
    module: str


@dataclass(frozen=True, slots=True)
class ModDefinition:
    """A validated mod manifest."""

    id: str
    label: str
    path: Path
    requires: tuple[str, ...] = ()
    entrypoint: str = "mod.py"
    entrypoint_explicit: bool = False
    board_designs: tuple[BoardDesignModule, ...] = ()

    @property
    def activities_path(self) -> Path:
        """Return the mod's activity iframe directory."""

        return self.path / "activities"

    @property
    def cutscenes_path(self) -> Path:
        """Return the mod's cutscene script root."""

        return self.path / "cutscenes"

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

        if any(spec["name"] == name for spec in self._commands):
            raise ValueError(f"Mod '{self.mod.id}' registers command '{name}' more than once.")
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
    cutscene_definitions: dict[str, CutsceneDefinition] = field(default_factory=dict)

    @property
    def ids(self) -> frozenset[str]:
        """Return the enabled mod ids."""

        return frozenset(mod.id for mod in self.definitions)

    def cutscene_roots(self) -> tuple[Path, ...]:
        """Return the cutscene script roots contributed by enabled mods."""

        return tuple(
            mod.cutscenes_path for mod in self.definitions if mod.cutscenes_path.is_dir()
        )

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
    """Discover mod manifests under one directory, keyed by mod id."""

    return discover_mods_in((mods_path,) if mods_path is not None else ())


def discover_mods_in(mods_paths: Iterable[Path]) -> dict[str, ModDefinition]:
    """Discover mod manifests across search roots, later roots winning clashes."""

    mods: dict[str, ModDefinition] = {}
    for mods_path in mods_paths:
        if not mods_path.is_dir():
            continue
        _ensure_importable(mods_path)
        for manifest in sorted(mods_path.glob("*/mod.yaml")):
            definition = _load_manifest(manifest)
            mods[definition.id] = definition
    return mods


def _ensure_importable(mods_path: Path) -> None:
    """Make a mod root's parent importable so ``mods.<id>`` modules resolve."""

    parent = str(mods_path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)


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
    board_designs = _load_board_designs(payload.get("boards"), mod_id)
    return ModDefinition(
        id=mod_id,
        label=str(payload.get("label", mod_id)).strip() or mod_id,
        path=manifest.parent.resolve(),
        requires=tuple(requires),
        entrypoint=entrypoint,
        entrypoint_explicit="entrypoint" in payload,
        board_designs=board_designs,
    )


def _load_board_designs(raw_value: object, mod_id: str) -> tuple[BoardDesignModule, ...]:
    """Parse a mod's optional ``boards`` name -> client module mapping."""

    if raw_value is None:
        return ()
    if not isinstance(raw_value, Mapping):
        raise ContentError(f"Mod '{mod_id}' boards must be a mapping.")
    designs: list[BoardDesignModule] = []
    for raw_name, raw_module in raw_value.items():
        name = str(raw_name).strip()
        if not _BOARD_DESIGN_ID.match(name):
            raise ContentError(f"Mod '{mod_id}' has an invalid board design name '{raw_name}'.")
        module = str(raw_module).strip().replace("\\", "/")
        parts = PurePosixPath(module).parts
        if (
            not module
            or PurePosixPath(module).is_absolute()
            or ".." in parts
            or not module.endswith(".js")
        ):
            raise ContentError(
                f"Mod '{mod_id}' board '{name}' module must be a relative .js path."
            )
        designs.append(BoardDesignModule(name=name, module=module))
    return tuple(designs)


def board_designs_payload(definitions: Iterable[ModDefinition]) -> list[dict[str, str]]:
    """Return the client board renderer manifest for enabled mods."""

    return [
        {
            "name": design.name,
            "mod_id": mod.id,
            "module_url": f"/assets/mods/{mod.id}/boards/{design.module}",
        }
        for mod in definitions
        for design in mod.board_designs
    ]


def resolve_mods(config: AppConfig) -> tuple[ModDefinition, ...]:
    """Resolve the configured mod names against installed manifests."""

    if not config.mods:
        return ()
    mods_paths = config.mods_paths
    available = discover_mods_in(mods_paths)
    if "*" in config.mods:
        selected = set(available)
    else:
        selected = set(config.mods)
    missing = sorted(selected - set(available))
    if missing:
        roots = ", ".join(str(path) for path in mods_paths) or "(none)"
        raise ConfigError(f"Unknown mod(s) {missing} in {roots}.")
    resolved: dict[str, ModDefinition] = {}
    order: list[str] = []

    def visit(mod_id: str, active: set[str]) -> None:
        if mod_id in resolved:
            return
        if mod_id in active:
            raise ConfigError(f"Mod dependency cycle detected at '{mod_id}'.")
        mod = available[mod_id]
        active.add(mod_id)
        for required in mod.requires:
            if required not in available:
                raise ConfigError(f"Mod '{mod_id}' requires missing mod '{required}'.")
            visit(required, active)
        active.discard(mod_id)
        resolved[mod_id] = mod
        order.append(mod_id)

    for mod_id in sorted(selected):
        visit(mod_id, set())
    return tuple(resolved[mod_id] for mod_id in order)


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


def load_mod_cutscene_definitions(
    mods: Iterable[ModDefinition],
    *,
    known_features: frozenset[str] = KNOWN_FEATURES,
    known_sounds: frozenset[str] | None = None,
) -> dict[str, CutsceneDefinition]:
    """Load each mod's optional ``content/cutscenes.yaml``."""

    definitions: dict[str, CutsceneDefinition] = {}
    for mod in mods:
        path = mod.content_path / "cutscenes.yaml"
        if not path.is_file():
            continue
        loaded = load_cutscene_definitions(
            path,
            source=mod.id,
            script_roots=(mod.cutscenes_path,),
            known_features=known_features,
            known_sounds=known_sounds,
        )
        for cutscene_id, definition in loaded.items():
            if cutscene_id in definitions:
                raise ContentError(f"Duplicate mod cutscene id '{cutscene_id}'.")
            definitions[cutscene_id] = definition
    return definitions


def load_mods(config: AppConfig) -> LoadedMods:
    """Resolve, import, and register every enabled mod."""

    definitions = resolve_mods(config)
    _validate_board_design_names(definitions)
    apis: list[ModAPI] = []
    for mod in definitions:
        api = ModAPI(mod)
        entrypoint = mod.path / mod.entrypoint
        if entrypoint.is_file():
            module = load_mod_module(mod)
            register = getattr(module, "register", None)
            if register is not None:
                register(api)
        elif mod.entrypoint_explicit:
            raise ConfigError(
                f"Mod '{mod.id}' declares entrypoint '{mod.entrypoint}' but it does not exist."
            )
        apis.append(api)
    return LoadedMods(
        definitions=definitions,
        apis=tuple(apis),
        activity_definitions=load_mod_activity_definitions(definitions),
        cutscene_definitions=load_mod_cutscene_definitions(
            definitions,
            known_sounds=load_sound_names(config.sounds_path),
        ),
    )


def _validate_board_design_names(definitions: Iterable[ModDefinition]) -> None:
    seen: dict[str, str] = {}
    for mod in definitions:
        for design in mod.board_designs:
            owner = seen.get(design.name)
            if owner is not None:
                raise ContentError(
                    f"Board design '{design.name}' is contributed by both '{owner}' and '{mod.id}'."
                )
            seen[design.name] = mod.id
