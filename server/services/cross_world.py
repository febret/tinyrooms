"""Cross-world travel resolution and browser redirect.

A world server discovers a running instance for another world through mission
control's token-authenticated fleet channel, then updates the shared profile so
the destination accepts the browser session. The client performs the actual
navigation with the returned ``travel`` payload. Energy costs and shared-loadout
reconciliation are intentionally out of scope for this minimal transfer.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from server.commands.outcomes import CommandError
from server.config import AppConfig
from server.content.worlds import ExitDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.services.powers import PowersService
from server.state.migrations import DatabaseHub


@dataclass(frozen=True, slots=True)
class WorldDestination:
    """A resolved running instance serving a target world."""

    world_id: str
    instance_id: str
    client_url: str
    entry_room_id: str | None


@dataclass(frozen=True, slots=True)
class TravelPlan:
    """A validated cross-world transfer ready to commit."""

    world_id: str
    instance_id: str
    client_url: str
    room_id: str

    def payload(self) -> dict[str, object]:
        """Return the command payload that tells the client where to travel."""

        return {
            "travel": {
                "url": self.client_url,
                "world_id": self.world_id,
                "instance_id": self.instance_id,
                "room_id": self.room_id,
            }
        }


class CrossWorldService:
    """Resolve and travel between mission-control-linked worlds."""

    def __init__(
        self,
        *,
        config: AppConfig,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_id: str,
        powers: PowersService,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._hub = hub
        self._profiles = profiles
        self._world_id = world_id
        self._powers = powers
        self._client = client

    @property
    def available(self) -> bool:
        """Return True when this server can reach mission control."""

        return bool(self._config.mc_endpoint and self._config.mc_token)

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            verify: object = True
            if self._config.mc_insecure_tls:
                verify = False
            elif self._config.mc_ca_file is not None:
                verify = str(self._config.mc_ca_file)
            self._client = httpx.AsyncClient(verify=verify, timeout=5.0)
        return self._client

    def _local_hostname(self) -> str:
        if self._config.client_url:
            hostname = urlsplit(self._config.client_url).hostname
            if hostname:
                return hostname
        if self._config.host in {"0.0.0.0", "::"}:
            return "127.0.0.1"
        return self._config.host

    async def list_worlds(self) -> list[dict[str, object]]:
        """Return running worlds with a destination that shares this login host."""

        if not self.available:
            raise CommandError("The Multiverse is unavailable on this server.")
        client = self._client_or_create()
        try:
            response = await client.get(
                f"https://{self._config.mc_endpoint}/api/mc/worlds",
                headers={"X-MC-Token": self._config.mc_token or ""},
            )
        except httpx.HTTPError as exc:
            raise CommandError("The Multiverse could not be reached right now.") from exc
        if response.status_code != 200:
            raise CommandError("The Multiverse is unavailable right now.")
        try:
            data = response.json()
        except ValueError as exc:
            raise CommandError("The Multiverse returned an invalid response.") from exc
        if not isinstance(data, dict) or not data.get("ok"):
            raise CommandError("The Multiverse is unavailable right now.")
        raw_worlds = data.get("worlds")
        if not isinstance(raw_worlds, list):
            raise CommandError("The Multiverse returned an invalid response.")
        local_host = self._local_hostname()
        worlds: list[dict[str, object]] = []
        for raw in raw_worlds:
            if not isinstance(raw, dict):
                continue
            world_id = str(raw.get("id") or "").strip()
            if not world_id:
                continue
            instances = raw.get("instances")
            chosen: dict[str, object] | None = None
            if isinstance(instances, list):
                for instance in instances:
                    if not isinstance(instance, dict):
                        continue
                    client_url = str(instance.get("client_url") or "")
                    if urlsplit(client_url).hostname == local_host:
                        chosen = instance
                        break
            if chosen is None:
                continue
            online_ids = raw.get("online_account_ids")
            worlds.append(
                {
                    "id": world_id,
                    "label": str(raw.get("label") or world_id),
                    "description": str(raw.get("description") or ""),
                    "image_url": str(chosen.get("image_url") or ""),
                    "users_online": max(0, int(raw.get("users_online") or 0)),
                    "online_account_ids": [
                        str(account_id) for account_id in online_ids if account_id
                    ] if isinstance(online_ids, list) else [],
                    "current": world_id == self._world_id,
                }
            )
        return worlds

    async def resolve_destination(self, world_id: str) -> WorldDestination:
        """Return a validated running instance for *world_id*, or raise."""

        if not self.available:
            raise CommandError("Cross-world travel is unavailable on this server.")
        client = self._client_or_create()
        try:
            response = await client.get(
                f"https://{self._config.mc_endpoint}/api/mc/instances/{world_id}/destination",
                headers={"X-MC-Token": self._config.mc_token or ""},
                params={"host": self._local_hostname()},
            )
        except httpx.HTTPError as exc:
            raise CommandError("The destination world could not be reached right now.") from exc
        if response.status_code != 200:
            raise CommandError("That destination is unavailable right now.")
        try:
            data = response.json()
        except ValueError as exc:
            raise CommandError("That destination returned an invalid response.") from exc
        if not isinstance(data, dict) or not data.get("ok"):
            raise CommandError("That destination is unavailable right now.")
        client_url = str(data.get("client_url") or "")
        instance_id = str(data.get("instance_id") or "")
        if not client_url or not instance_id:
            raise CommandError("That destination is unavailable right now.")
        if urlsplit(client_url).hostname != self._local_hostname():
            raise CommandError("That destination cannot share this session's login.")
        entry_room = data.get("entry_room_id")
        return WorldDestination(
            world_id=world_id,
            instance_id=instance_id,
            client_url=client_url,
            entry_room_id=str(entry_room) if entry_room else None,
        )

    def check_multiverse_access(self, account: AccountRecord) -> None:
        """Require permanent Multiverse Map access, or the admin power, for cross-world travel."""

        if self._powers.has_power(account.id, "admin"):
            return
        if not self._profiles.has_multiverse_access(account.id):
            raise CommandError("Use the Multiverse Map to unlock cross-world travel.")

    def _check_exit(self, account: AccountRecord, exit_definition: ExitDefinition) -> None:
        if exit_definition.target_world_id is None:
            raise CommandError("That exit does not lead to another world.")
        if exit_definition.locked:
            raise CommandError("That way is locked.")
        if exit_definition.requires_card_id is not None:
            inventory_ids = {stack.card_def_id for stack in self._profiles.list_inventory(account.id, self._world_id)}
            if exit_definition.requires_card_id not in inventory_ids:
                raise CommandError(f"You need {exit_definition.requires_card_id} to go that way.")
        self.check_multiverse_access(account)

    async def prepare(self, account: AccountRecord, exit_definition: ExitDefinition) -> TravelPlan:
        """Validate the exit and resolve its destination without side effects."""

        self._check_exit(account, exit_definition)
        destination = await self.resolve_destination(exit_definition.target_world_id or "")
        room_id = exit_definition.target_room_id or destination.entry_room_id or ""
        return TravelPlan(
            world_id=destination.world_id,
            instance_id=destination.instance_id,
            client_url=destination.client_url,
            room_id=room_id,
        )

    async def prepare_world(
        self,
        account: AccountRecord,
        world_id: str,
        room_id: str | None = None,
    ) -> TravelPlan:
        """Resolve a cross-world destination, requiring permanent access or admin power."""

        self.check_multiverse_access(account)
        destination = await self.resolve_destination(world_id)
        return TravelPlan(
            world_id=destination.world_id,
            instance_id=destination.instance_id,
            client_url=destination.client_url,
            room_id=room_id or destination.entry_room_id or "",
        )

    def commit(
        self,
        account: AccountRecord,
        plan: TravelPlan,
        *,
        source_room_id: str | None = None,
        source_room_label: str | None = None,
        source_world_label: str | None = None,
    ) -> dict[str, object]:
        """Persist the remembered destination and arrival source, then return the payload."""

        with self._hub.transaction() as connection:
            self._profiles.set_remembered_room(connection, account.id, plan.world_id, plan.room_id)
            if source_room_id is not None:
                self._profiles.record_world_arrival_in_transaction(
                    connection,
                    account.id,
                    source_world_id=self._world_id,
                    source_room_id=source_room_id,
                    source_room_label=source_room_label,
                    source_world_label=source_world_label,
                )
        self._profiles.remember_instance(account.id, plan.instance_id)
        return plan.payload()

    async def travel(
        self,
        account: AccountRecord,
        exit_definition: ExitDefinition,
        *,
        source_room_id: str | None = None,
        source_room_label: str | None = None,
        source_world_label: str | None = None,
    ) -> dict[str, object]:
        """Resolve and commit a cross-world transfer, returning the client payload."""

        plan = await self.prepare(account, exit_definition)
        return self.commit(
            account,
            plan,
            source_room_id=source_room_id,
            source_room_label=source_room_label,
            source_world_label=source_world_label,
        )
