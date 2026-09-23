"""Definition-time loading of trusted behavior scripts beside world content."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from importlib import util as importlib_util
from pathlib import Path
from types import ModuleType

from server.behaviors.builtin import BUILTIN_BEHAVIORS
from server.behaviors.events import PeepRef, PropRef
from server.content.common import ContentError
from server.content.worlds import WorldDefinition


@dataclass(frozen=True, slots=True)
class BehaviorScript:
    """A loaded behavior module and its stable identity."""

    script_id: str
    path: Path | None
    module: ModuleType


@dataclass(frozen=True, slots=True)
class BehaviorAttachment:
    """A script bound to one concrete peep or prop instance."""

    script_id: str
    namespace: str
    instance_id: str
    ref: PeepRef | PropRef | None


@dataclass(frozen=True, slots=True)
class BehaviorScripts:
    """All loaded behavior scripts and their world attachments."""

    scripts: dict[str, BehaviorScript]
    peep_attachments: dict[str, BehaviorAttachment]
    prop_attachments: dict[str, BehaviorAttachment]
    room_attachments: dict[str, tuple[BehaviorAttachment, ...]]


def _builtin_module() -> ModuleType:
    return ModuleType("tinyrooms_behavior_builtin")


class BehaviorLoader:
    """Import trusted scripts once per resolved path at definition time."""

    def __init__(self) -> None:
        self._cache: dict[Path, BehaviorScript] = {}
        self._builtin = BehaviorScript(script_id="builtin", path=None, module=_builtin_module())

    @staticmethod
    def _module_name(path: Path) -> str:
        digest = sha1(str(path).encode("utf-8")).hexdigest()
        return f"tinyrooms_behavior_{digest}"

    def _import(self, path: Path) -> BehaviorScript:
        resolved = path.resolve()
        cached = self._cache.get(resolved)
        if cached is not None:
            return cached
        spec = importlib_util.spec_from_file_location(self._module_name(resolved), resolved)
        if spec is None or spec.loader is None:
            raise ContentError(f"Behavior script '{resolved}' could not be loaded.")
        module = importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        script = BehaviorScript(script_id=f"behavior:{sha1(str(resolved).encode('utf-8')).hexdigest()}", path=resolved, module=module)
        self._cache[resolved] = script
        return script

    def _resolve_peep(self, world: WorldDefinition, script_name: str, peep_id: str) -> Path:
        path = (world.root_path / "peeps" / script_name).resolve()
        if not path.is_file():
            raise ContentError(f"Peep '{peep_id}' references missing behavior script '{script_name}'.")
        return path

    def _resolve_prop(self, world: WorldDefinition, script: str, instance_id: str) -> Path:
        path = (world.root_path / "props" / script).resolve()
        if not path.is_file():
            raise ContentError(f"Prop '{instance_id}' references missing behavior script '{script}'.")
        return path

    def load_world(self, world: WorldDefinition) -> BehaviorScripts:
        """Import every referenced script and build the attachment maps."""

        scripts: dict[str, BehaviorScript] = {}
        peep_attachments: dict[str, BehaviorAttachment] = {}
        prop_attachments: dict[str, BehaviorAttachment] = {}

        for peep in world.peeps.values():
            if not peep.script_name:
                continue
            script = self._import(self._resolve_peep(world, peep.script_name, peep.id))
            scripts[script.script_id] = script
            peep_attachments[peep.id] = BehaviorAttachment(
                script_id=script.script_id,
                namespace="peep",
                instance_id=peep.id,
                ref=PeepRef(kind="npc", peep_id=peep.id, account_id=None),
            )

        for room in world.rooms.values():
            for prop in room.props.values():
                if not prop.behavior:
                    continue
                if prop.behavior in BUILTIN_BEHAVIORS:
                    script_id = BUILTIN_BEHAVIORS[prop.behavior]
                    scripts.setdefault(script_id, BehaviorScript(script_id=script_id, path=None, module=self._builtin.module))
                else:
                    script = self._import(self._resolve_prop(world, prop.behavior, prop.id))
                    scripts[script.script_id] = script
                    script_id = script.script_id
                prop_attachments[prop.id] = BehaviorAttachment(
                    script_id=script_id,
                    namespace="prop",
                    instance_id=prop.id,
                    ref=PropRef(instance_id=prop.id, prop_id=prop.prop_id, room_id=room.id),
                )

        room_attachments: dict[str, tuple[BehaviorAttachment, ...]] = {}
        for room in world.rooms.values():
            attachments: list[BehaviorAttachment] = []
            for peep in world.peeps.values():
                if peep.room_id == room.id and peep.id in peep_attachments:
                    attachments.append(peep_attachments[peep.id])
            for prop in room.props.values():
                if prop.id in prop_attachments:
                    attachments.append(prop_attachments[prop.id])
            room_attachments[room.id] = tuple(attachments)

        return BehaviorScripts(
            scripts=scripts,
            peep_attachments=peep_attachments,
            prop_attachments=prop_attachments,
            room_attachments=room_attachments,
        )
