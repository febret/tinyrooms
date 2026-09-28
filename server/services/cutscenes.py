"""Cutscene launch resolution and play-payload construction.

The service owns every decision made before a cutscene reaches a client: which
definition a reference names, whether the caller may launch it, who hears it,
and which world assets each placeholder token refers to. Clients receive a
closed record and never resolve a path themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import random
import re
from typing import TYPE_CHECKING, Any

from server.config import AppConfig
from server.content.cutscenes import (
    CutsceneCatalog,
    CutsceneDefinition,
    build_cutscene_catalog,
    resolve_cutscene_id,
)
from server.content.worlds import WorldDefinition

if TYPE_CHECKING:
    from server.profiles import AccountRecord, ProfileRepository
    from server.services.cards import CardService


AUDIENCE_PRIVATE = "private"
AUDIENCE_ROOM = "room"
MAX_PLACEHOLDERS = 24


class CutsceneError(ValueError):
    """Raised when a cutscene launch is rejected."""


@dataclass(frozen=True, slots=True)
class CutsceneLaunch:
    """A resolved, ready-to-deliver cutscene play event."""

    definition: CutsceneDefinition
    audience: str
    room_id: str
    params: dict[str, Any]
    assets: tuple[dict[str, object], ...]
    event: dict[str, object]

    @property
    def is_room_wide(self) -> bool:
        """Return whether the play event belongs on the room broadcast."""

        return self.audience == AUDIENCE_ROOM


PLACEHOLDER_PATTERN = re.compile(r"\$[a-z]+(?::[A-Za-z0-9_.:\-]+)?")


def _placeholder_tokens(value: Any) -> list[str]:
    """Return every placeholder token inside a nested param structure.

    Tokens are matched anywhere in a string so that a caption such as
    ``"$me, you again?"`` contributes ``$me`` to the resolved asset list.
    """

    if isinstance(value, str):
        return [match.group(0) for match in PLACEHOLDER_PATTERN.finditer(value)]
    if isinstance(value, Mapping):
        tokens: list[str] = []
        for entry in value.values():
            tokens.extend(_placeholder_tokens(entry))
        return tokens
    if isinstance(value, (list, tuple)):
        tokens = []
        for entry in value:
            tokens.extend(_placeholder_tokens(entry))
        return tokens
    return []


def choose_audience(definition: CutsceneDefinition, requested: str | None = None) -> str:
    """Return the delivery audience for a launch, honouring the definition."""

    if requested == AUDIENCE_ROOM:
        if definition.audience not in {AUDIENCE_ROOM, "any"}:
            raise CutsceneError(f"{definition.title} cannot be shown to the whole room.")
        return AUDIENCE_ROOM
    if requested == AUDIENCE_PRIVATE:
        return AUDIENCE_PRIVATE
    if definition.audience == AUDIENCE_ROOM:
        return AUDIENCE_ROOM
    return AUDIENCE_PRIVATE


class CutsceneService:
    """Resolve definitions, audiences, and placeholders for a cutscene launch."""

    def __init__(
        self,
        config: AppConfig,
        *,
        world: Callable[[], WorldDefinition],
        profiles: ProfileRepository,
        cards: CardService,
        valid_stickers: frozenset[str],
    ) -> None:
        self._config = config
        self._world = world
        self._profiles = profiles
        self._cards = cards
        self._valid_stickers = valid_stickers

    @property
    def valid_stickers(self) -> frozenset[str]:
        """Return every sticker name the server will serve."""

        return self._valid_stickers

    def feature_enabled(self, feature: str) -> bool:
        """Return whether a feature flag is enabled, normalizing separators.

        Cutscenes themselves are always available; this only serves a
        definition's own ``feature:`` gate.
        """

        normalized = feature.replace("-", "_")
        return any(enabled.replace("-", "_") == normalized for enabled in self._config.features)

    def catalog(self) -> CutsceneCatalog:
        """Return the merged catalog for the loaded world."""

        return build_cutscene_catalog(self._world().cutscenes)

    def definitions(self) -> dict[str, CutsceneDefinition]:
        """Return every cutscene definition in the loaded world."""

        return self._world().cutscenes

    def choose_audience(self, definition: CutsceneDefinition, requested: str | None = None) -> str:
        """Return the delivery audience for a launch, honouring the definition."""

        return choose_audience(definition, requested)

    def resolve(self, reference: str) -> CutsceneDefinition:
        """Return the definition named by an id or alias."""

        catalog = self.catalog()
        cutscene_id = resolve_cutscene_id(catalog, reference)
        if cutscene_id is None:
            raise CutsceneError(f"There is no cutscene called '{reference}'.")
        return catalog.cutscenes[cutscene_id]

    def visible_catalog(self, *, room_id: str) -> list[dict[str, object]]:
        """Return the catalog a client may offer for launching."""

        entries: list[dict[str, object]] = []
        for definition in self.definitions().values():
            if definition.rooms and room_id not in definition.rooms:
                continue
            entries.append(
                {
                    "id": definition.id,
                    "title": definition.title,
                    "aliases": list(definition.aliases),
                    "frame": definition.frame,
                    "audience": definition.audience,
                    "room_bound": definition.room_bound,
                    "rooms": list(definition.rooms),
                    "origin": definition.source,
                }
            )
        entries.sort(key=lambda entry: str(entry["title"]).lower())
        return entries

    def check(
        self,
        definition: CutsceneDefinition,
        *,
        room_id: str,
        has_power: Callable[[str], bool],
    ) -> None:
        """Validate that a launch may proceed."""

        if definition.required_feature and not self.feature_enabled(definition.required_feature):
            raise CutsceneError(f"{definition.title} is not available.")
        if definition.rooms and room_id not in definition.rooms:
            raise CutsceneError(f"{definition.title} is not available here.")
        if definition.power and not has_power(definition.power):
            raise CutsceneError(f"{definition.title} is not available.")

    def launch(
        self,
        *,
        definition: CutsceneDefinition,
        account: AccountRecord,
        room_id: str,
        audience: str,
        origin: str,
        params: Mapping[str, Any] | None = None,
        occupants: Iterable[str] | None = None,
    ) -> CutsceneLaunch:
        """Build the ``cutscene.play`` event for a validated launch.

        *occupants* is the set of account ids present in the room; callers
        fetch it because room membership is only readable asynchronously.
        """

        merged = self._merge_params(definition, params)
        merged["origin"] = origin
        merged["source_name"] = account.username_display
        merged["room_id"] = room_id
        merged.setdefault("random", random.randint(0, 9999))
        room_accounts = frozenset(occupants) if occupants is not None else None
        cue_values = [value for cue in definition.text for value in (cue.say, cue.speaker)]
        tokens = list(
            dict.fromkeys(_placeholder_tokens([*merged.values(), *cue_values]))
        )
        resolved: list[dict[str, object]] = []
        for token in tokens:
            if len(resolved) >= MAX_PLACEHOLDERS:
                break
            asset = self._resolve_assets(token, room_id=room_id, account=account, occupants=room_accounts)
            if asset is not None:
                resolved.append(asset)
        cues = tuple(
            {"at": cue.at, "say": self._substitute(cue.say, resolved), "speaker": cue.speaker, "style": cue.style}
            for cue in definition.text
        )
        payload: dict[str, object] = {
            "id": definition.id,
            "title": definition.title,
            "script_url": definition.script_url,
            "frame": definition.frame,
            "duration": definition.duration_ms,
            "skip": definition.skip,
            "room_bound": definition.room_bound,
            "audience": audience,
            "origin": origin,
            "source": {"id": account.id, "name": account.username_display},
            "params": merged,
            "text": list(cues),
            "assets": list(resolved),
        }
        event: dict[str, object] = {
            "type": "cutscene.play",
            "room_id": room_id,
            "cutscene": payload,
        }
        if audience == AUDIENCE_PRIVATE:
            event["account_id"] = account.id
        return CutsceneLaunch(
            definition=definition,
            audience=audience,
            room_id=room_id,
            params=merged,
            assets=tuple(resolved),
            event=event,
        )

    def _merge_params(
        self,
        definition: CutsceneDefinition,
        overrides: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(definition.params)
        for key, value in (overrides or {}).items():
            merged[str(key)] = value
        merged["origin"] = self._origin_of(merged.get("origin"), definition)
        return merged

    @staticmethod
    def _origin_of(raw_value: Any, definition: CutsceneDefinition) -> str:
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
        return definition.source

    def _substitute(self, text: str, assets: Sequence[Mapping[str, object]]) -> str:
        if not text:
            return text
        labels = {str(asset["ref"]): str(asset.get("label", "")) for asset in assets}
        substituted = text
        for ref, label in labels.items():
            if label:
                substituted = substituted.replace(ref, label)
        return substituted

    def _resolve_assets(
        self,
        token: str,
        *,
        room_id: str,
        account: AccountRecord,
        occupants: frozenset[str] | None = None,
    ) -> dict[str, object] | None:
        kind, _, value = token[1:].partition(":")
        value = value.strip()
        if kind == "me":
            return self._sticker_asset(token, account)
        if kind == "user" and value:
            return self._user_asset(token, value, occupants)
        if kind == "peep" and value:
            return self._peep_asset(token, value)
        if kind == "sticker" and value:
            return self._named_sticker_asset(token, value)
        if kind == "card" and value:
            return self._card_asset(token, value, account)
        if kind == "prop" and value:
            return self._prop_asset(token, value, room_id)
        return None

    def _sticker_asset(self, ref: str, account: AccountRecord) -> dict[str, object] | None:
        if not account.sticker:
            return None
        return {
            "ref": ref,
            "kind": "sticker",
            "id": account.sticker,
            "label": account.username_display,
            "url": f"/assets/stickers/{account.sticker}",
            "animation_url": None,
        }

    def _user_asset(
        self,
        ref: str,
        account_id: str,
        occupants: frozenset[str] | None,
    ) -> dict[str, object] | None:
        if occupants is not None and account_id not in occupants:
            return None
        account = self._profiles.get_account_by_id(account_id)
        if account is None or not account.sticker:
            return None
        return {
            "ref": ref,
            "kind": "sticker",
            "id": account.sticker,
            "label": account.username_display,
            "url": f"/assets/stickers/{account.sticker}",
            "animation_url": None,
        }

    def _peep_asset(self, ref: str, peep_id: str) -> dict[str, object] | None:
        world = self._world()
        peep = world.peeps.get(peep_id)
        if peep is None:
            return None
        return {
            "ref": ref,
            "kind": "sticker",
            "id": peep.id,
            "label": peep.label or peep.id,
            "url": f"/assets/world/{world.id}/peeps/{peep.image_name}",
            "animation_url": None,
        }

    def _named_sticker_asset(self, ref: str, name: str) -> dict[str, object] | None:
        if name not in self._valid_stickers:
            return None
        return {
            "ref": ref,
            "kind": "sticker",
            "id": name,
            "label": name,
            "url": f"/assets/stickers/{name}",
            "animation_url": None,
        }

    def _card_asset(self, ref: str, value: str, account: AccountRecord) -> dict[str, object] | None:
        definition = None
        if self._cards.has_definition(value):
            definition = self._cards.definition(value)
        else:
            for stack in self._profiles.list_inventory(account.id, self._world().id):
                if stack.stack_id == value and self._cards.has_definition(stack.card_def_id):
                    definition = self._cards.definition(stack.card_def_id)
                    break
        if definition is None:
            return None
        image_url, animation_url = self._cards.asset_urls(definition)
        return {
            "ref": ref,
            "kind": "card",
            "id": definition.id,
            "label": definition.label,
            "url": image_url,
            "animation_url": animation_url,
        }

    def _prop_asset(self, ref: str, instance_id: str, room_id: str) -> dict[str, object] | None:
        world = self._world()
        room = world.rooms.get(room_id)
        if room is None:
            return None
        instance = room.props.get(instance_id)
        if instance is None:
            return None
        definition = world.props.get(instance.prop_id)
        if definition is None:
            return None
        if definition.source_kind == "mod":
            model_url = f"/assets/mods/{definition.source}/props/{definition.model_name}"
        elif definition.source_kind == "propset":
            model_url = f"/assets/propsets/{definition.source}/{definition.model_name}"
        else:
            model_url = f"/assets/world/{world.id}/props/{definition.model_name}"
        return {
            "ref": ref,
            "kind": "prop",
            "id": instance.id,
            "label": definition.label or definition.id,
            "model_url": model_url,
            "thumbnail": None,
            "scale": instance.scale * definition.scale,
        }

    def referenced_ids(self, values: Iterable[Any]) -> list[str]:
        """Return every placeholder token in *values* in order, deduplicated."""

        return list(dict.fromkeys(_placeholder_tokens(list(values))))
