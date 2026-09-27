"""Strict loader for cutscene definitions.

A cutscene is authored as a YAML definition plus a JavaScript module in a
directory named after the cutscene id. The server owns every path involved: it
resolves the module to a real file at load time and publishes a served URL in
the play payload, so a client is never asked to load a module path it chose
itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping


AUDIENCES = frozenset({"private", "room", "any"})
MAX_PARAMS = 16
MAX_PARAM_STRING = 200
MAX_PARAMS_TEXT = 4000
RESERVED_PARAM_KEYS = ("origin", "source_name", "room_id", "random")


@dataclass(frozen=True, slots=True)
class CutsceneCue:
    """One caption cue scheduled relative to the start of the scene body."""

    at: int
    say: str = ""
    speaker: str = ""
    style: str = ""


@dataclass(frozen=True, slots=True)
class CutsceneDefinition:
    """An authored cutscene that a command, prop, peep, or emote can launch."""

    id: str
    title: str
    script_name: str
    frame: str
    source: str
    script_path: Path | None = None
    duration_ms: int = 0
    audience: str = "private"
    room_bound: bool = True
    skip: bool = True
    aliases: tuple[str, ...] = ()
    max_queue: int = 3
    required_feature: str | None = None
    power: str | None = None
    rooms: tuple[str, ...] = ()
    energy_cost: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    text: tuple[CutsceneCue, ...] = ()

    @property
    def script_url(self) -> str:
        """Return the served URL for this cutscene's entry module."""

        return f"/cutscenes/{self.id}/{self.script_name}"


@dataclass(frozen=True, slots=True)
class CutsceneCatalog:
    """A merged catalog indexed by id and by alias."""

    cutscenes: dict[str, CutsceneDefinition]
    by_alias: dict[str, str]


def _string_list(raw_value: Any, label: str, path: Path) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ContentError(f"{label} must be a list in {path}.")
    values: list[str] = []
    for value in raw_value:
        if not isinstance(value, str) or not value.strip():
            raise ContentError(f"{label} entries must be non-empty strings in {path}.")
        values.append(value.strip())
    return tuple(values)


def _non_negative_int(raw_value: Any, label: str) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise ContentError(f"{label} must be a non-negative integer.")
    return int(raw_value)


def _parse_params(raw_value: Any, cutscene_id: str, path: Path) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ContentError(f"Cutscene '{cutscene_id}' params must be a mapping in {path}.")
    if len(raw_value) > MAX_PARAMS:
        raise ContentError(
            f"Cutscene '{cutscene_id}' defines more than {MAX_PARAMS} params in {path}."
        )
    params: dict[str, Any] = {}
    for key, value in raw_value.items():
        name = str(key).strip()
        if not name:
            raise ContentError(f"Cutscene '{cutscene_id}' has an empty param name in {path}.")
        if name == "frame_options":
            if not isinstance(value, dict):
                raise ContentError(
                    f"Cutscene '{cutscene_id}' param 'frame_options' must be a mapping in {path}."
                )
            params[name] = _parse_frame_options(value, name, cutscene_id, path)
            continue
        if isinstance(value, bool):
            params[name] = value
        elif isinstance(value, (int, float)):
            params[name] = value
        elif isinstance(value, str):
            if len(value) > MAX_PARAM_STRING:
                raise ContentError(
                    f"Cutscene '{cutscene_id}' param '{name}' is longer than "
                    f"{MAX_PARAM_STRING} characters in {path}."
                )
            params[name] = value
        else:
            raise ContentError(
                f"Cutscene '{cutscene_id}' param '{name}' must be a string, number, or "
                f"boolean in {path}."
            )
    return params


def _parse_frame_options(
    raw_value: Mapping[str, Any],
    name: str,
    cutscene_id: str,
    path: Path,
) -> dict[str, Any]:
    if len(raw_value) > MAX_PARAMS:
        raise ContentError(
            f"Cutscene '{cutscene_id}' param '{name}' defines more than {MAX_PARAMS} keys in {path}."
        )
    options: dict[str, Any] = {}
    for key, value in raw_value.items():
        option = str(key).strip()
        if not option:
            raise ContentError(f"Cutscene '{cutscene_id}' has an empty '{name}' key in {path}.")
        if isinstance(value, bool) or isinstance(value, (int, float)):
            options[option] = value
        elif isinstance(value, str) and len(value) <= MAX_PARAM_STRING:
            options[option] = value
        else:
            raise ContentError(
                f"Cutscene '{cutscene_id}' frame option '{option}' must be a string, number, "
                f"or boolean in {path}."
            )
    return options


def _parse_cues(raw_value: Any, cutscene_id: str, path: Path) -> tuple[CutsceneCue, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ContentError(f"Cutscene '{cutscene_id}' text must be a list in {path}.")
    cues: list[CutsceneCue] = []
    for index, raw_cue in enumerate(raw_value):
        if not isinstance(raw_cue, dict):
            raise ContentError(f"Cutscene '{cutscene_id}' text cue {index} must be a mapping in {path}.")
        say = str(raw_cue.get("say", "")).strip()
        speaker = str(raw_cue.get("speaker", "")).strip()
        if not say and not speaker:
            raise ContentError(
                f"Cutscene '{cutscene_id}' text cue {index} needs say or speaker in {path}."
            )
        raw_at = raw_cue.get("at", 0)
        if isinstance(raw_at, bool) or not isinstance(raw_at, (int, float)) or raw_at < 0:
            raise ContentError(
                f"Cutscene '{cutscene_id}' text cue {index} has an invalid at in {path}."
            )
        cues.append(
            CutsceneCue(
                at=int(raw_at),
                say=say[:MAX_PARAMS_TEXT],
                speaker=speaker[:MAX_PARAM_STRING],
                style=str(raw_cue.get("style", "")).strip()[:64],
            )
        )
    return tuple(cues)


def _resolve_script(cutscene_id: str, script_name: str, script_roots: Sequence[Path]) -> Path | None:
    for root in script_roots:
        candidate = (Path(root) / cutscene_id / script_name).resolve()
        if candidate.is_file() and candidate.parent.name == cutscene_id:
            return candidate
    return None


def load_cutscene_definitions(
    path: Path,
    *,
    source: str,
    script_roots: Sequence[Path] = (),
    known_rooms: frozenset[str] = frozenset(),
    known_features: frozenset[str] = frozenset(),
    known_powers: frozenset[str] = frozenset(),
) -> dict[str, CutsceneDefinition]:
    """Load and validate cutscene definitions from a YAML file."""

    if not path.is_file():
        return {}
    payload = require_mapping(load_yaml_file(path), path)
    definitions: dict[str, CutsceneDefinition] = {}
    for cutscene_id, raw in payload.items():
        if not isinstance(cutscene_id, str) or not cutscene_id.strip() or not isinstance(raw, dict):
            raise ContentError(f"{path} contains an invalid cutscene entry.")
        title = str(raw.get("title", "")).strip()
        if not title:
            raise ContentError(f"Cutscene '{cutscene_id}' must define a title.")
        script_name = str(raw.get("script", f"{cutscene_id}.js")).strip() or f"{cutscene_id}.js"
        if "/" in script_name or "\\" in script_name or script_name.startswith("."):
            raise ContentError(f"Cutscene '{cutscene_id}' script must be a plain file name.")
        if not script_name.endswith(".js"):
            raise ContentError(f"Cutscene '{cutscene_id}' script must be a .js file.")
        frame = str(raw.get("frame", "plain")).strip() or "plain"
        audience = str(raw.get("audience", "private")).strip() or "private"
        if audience not in AUDIENCES:
            raise ContentError(
                f"Cutscene '{cutscene_id}' has unknown audience '{audience}'. "
                f"Expected one of {', '.join(sorted(AUDIENCES))}."
            )
        room_bound = raw.get("room_bound", True)
        if not isinstance(room_bound, bool):
            raise ContentError(f"Cutscene '{cutscene_id}' room_bound must be a boolean.")
        skip = raw.get("skip", True)
        if not isinstance(skip, bool):
            raise ContentError(f"Cutscene '{cutscene_id}' skip must be a boolean.")
        aliases = _string_list(raw.get("aliases"), f"Cutscene '{cutscene_id}' aliases", path)
        if len(set(aliases)) != len(aliases):
            raise ContentError(f"Cutscene '{cutscene_id}' repeats an alias in {path}.")
        rooms = _string_list(raw.get("rooms"), f"Cutscene '{cutscene_id}' rooms", path)
        for room_id in rooms:
            if known_rooms and room_id not in known_rooms:
                raise ContentError(f"Cutscene '{cutscene_id}' references unknown room '{room_id}'.")
        required_feature = raw.get("feature")
        if required_feature is not None:
            required_feature = str(required_feature).strip()
            if not required_feature:
                raise ContentError(f"Cutscene '{cutscene_id}' feature must be a non-empty string.")
            if known_features and required_feature not in known_features:
                raise ContentError(
                    f"Cutscene '{cutscene_id}' references unknown feature '{required_feature}'."
                )
        power = raw.get("power")
        if power is not None:
            power = str(power).strip()
            if not power:
                raise ContentError(f"Cutscene '{cutscene_id}' power must be a non-empty string.")
            if known_powers and power not in known_powers:
                raise ContentError(f"Cutscene '{cutscene_id}' references unknown power '{power}'.")
        max_queue = raw.get("max_queue", 3)
        if isinstance(max_queue, bool) or not isinstance(max_queue, int) or max_queue < 1:
            raise ContentError(f"Cutscene '{cutscene_id}' max_queue must be an integer of at least 1.")
        script_path = _resolve_script(cutscene_id, script_name, script_roots) if script_roots else None
        if script_roots and script_path is None:
            raise ContentError(f"Cutscene '{cutscene_id}' references missing script '{script_name}'.")
        definitions[cutscene_id] = CutsceneDefinition(
            id=cutscene_id,
            title=title,
            script_name=script_name,
            frame=frame,
            source=source,
            script_path=script_path,
            duration_ms=_non_negative_int(raw.get("duration", 0), f"Cutscene '{cutscene_id}' duration"),
            audience=audience,
            room_bound=room_bound,
            skip=skip,
            aliases=aliases,
            max_queue=int(max_queue),
            required_feature=required_feature,
            power=power,
            rooms=rooms,
            energy_cost=_non_negative_int(
                raw.get("energy_cost", 0), f"Cutscene '{cutscene_id}' energy_cost"
            ),
            params=_parse_params(raw.get("params"), cutscene_id, path),
            text=_parse_cues(raw.get("text"), cutscene_id, path),
        )
    return definitions


def merge_cutscene_definitions(
    *catalogs: Mapping[str, CutsceneDefinition],
) -> dict[str, CutsceneDefinition]:
    """Merge catalogs in precedence order, rejecting duplicate ids and aliases."""

    merged: dict[str, CutsceneDefinition] = {}
    owners: dict[str, str] = {}
    for catalog in catalogs:
        for cutscene_id, definition in catalog.items():
            if cutscene_id in merged:
                raise ContentError(
                    f"Duplicate cutscene id '{cutscene_id}' in {owners[cutscene_id]} "
                    f"and {definition.source}."
                )
            merged[cutscene_id] = definition
            owners[cutscene_id] = definition.source
    aliases: dict[str, str] = {}
    for cutscene_id, definition in merged.items():
        for alias in definition.aliases:
            if alias in aliases and aliases[alias] != cutscene_id:
                raise ContentError(
                    f"Cutscene alias '{alias}' is claimed by both '{aliases[alias]}' and '{cutscene_id}'."
                )
            if alias in merged and alias != cutscene_id:
                raise ContentError(f"Cutscene alias '{alias}' collides with a cutscene id.")
            aliases[alias] = cutscene_id
    return merged


def build_cutscene_catalog(cutscenes: Mapping[str, CutsceneDefinition]) -> CutsceneCatalog:
    """Index a merged catalog by id and by alias."""

    by_alias: dict[str, str] = {}
    for cutscene_id, definition in cutscenes.items():
        for alias in definition.aliases:
            by_alias[alias] = cutscene_id
    return CutsceneCatalog(cutscenes=dict(cutscenes), by_alias=by_alias)


def parse_param_arguments(
    raw_arguments: Iterable[str],
    *,
    label: str = "Cutscene",
) -> dict[str, Any]:
    """Parse ``key=value`` launch arguments into scalar params."""

    params: dict[str, Any] = {}
    for raw in raw_arguments:
        key, separator, value = raw.partition("=")
        name = key.strip()
        if not separator or not name:
            raise ContentError(f"{label} arguments must be key=value pairs.")
        if name in RESERVED_PARAM_KEYS:
            raise ContentError(f"{label} argument '{name}' is reserved.")
        if len(params) >= MAX_PARAMS:
            raise ContentError(f"{label} accepts at most {MAX_PARAMS} arguments.")
        if len(value) > MAX_PARAM_STRING:
            raise ContentError(f"{label} argument '{name}' is too long.")
        params[name] = _coerce_param_value(value)
    return params


def _coerce_param_value(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def resolve_cutscene_id(catalog: CutsceneCatalog, reference: str) -> str | None:
    """Resolve an id or alias to a catalog id."""

    name = reference.strip()
    if name in catalog.cutscenes:
        return name
    return catalog.by_alias.get(name)
