"""Create and redeem guest-entry links for the current world."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

from server.accounts import AccountService
from server.config import AppConfig
from server.connections import ConnectionRegistry
from server.content.worlds import WorldDefinition
from server.instance_policy import AccountLimitError
from server.profiles import AccountRecord, ProfileRepository
from server.security import IssuedSession, utc_now
from server.services.rooms import RoomService
from server.state.migrations import DatabaseHub

GUEST_INVITE_TTL = timedelta(days=7)
GUEST_TOKEN_BYTES = 32
GUEST_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
GUEST_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
GUEST_INVITES_PER_ACCOUNT = 20

GUEST_ADJECTIVES = (
    "Brave",
    "Calm",
    "Clever",
    "Curious",
    "Daring",
    "Gentle",
    "Jolly",
    "Lucky",
    "Quiet",
    "Wandering",
)
GUEST_NOUNS = (
    "Badger",
    "Finch",
    "Gecko",
    "Heron",
    "Lemur",
    "Otter",
    "Pigeon",
    "Rabbit",
    "Robin",
    "Turtle",
)


class GuestInviteError(ValueError):
    """Raised when a guest invite cannot be created or redeemed."""

    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class FingerprintContext:
    """Basic client information used to identify one device."""

    device_id: str
    user_agent: str
    accept_language: str
    client_host: str


@dataclass(frozen=True, slots=True)
class GuestInviteRecord:
    """One live invite held in process memory."""

    inviter_account_id: str
    world_id: str
    instance_id: str
    room_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class GuestInviteLink:
    """A freshly created invite link."""

    token: str
    url: str
    world_id: str
    instance_id: str
    room_id: str
    room_label: str
    inviter_username: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class GuestRedeemResult:
    """The session issued after an invite is accepted."""

    session: IssuedSession
    redirect_url: str


class GuestInviteService:
    """Own guest link creation, device reuse, and room placement."""

    def __init__(
        self,
        config: AppConfig,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        accounts: AccountService,
        connections: ConnectionRegistry,
        rooms: RoomService,
        world: WorldDefinition,
    ) -> None:
        self._config = config
        self._hub = hub
        self._profiles = profiles
        self._accounts = accounts
        self._connections = connections
        self._rooms = rooms
        self._world = world
        self._invites: dict[str, GuestInviteRecord] = {}

    def rebind(self, world: WorldDefinition, rooms: RoomService) -> None:
        """Point a preserved in-memory invite set at a reloaded world graph."""

        self._world = world
        self._rooms = rooms

    async def create(self, account: AccountRecord, *, public_base_url: str) -> GuestInviteLink:
        """Create a guest link from the inviter's current room."""

        if account.is_guest:
            raise GuestInviteError(
                "Guest accounts cannot invite other guests.",
                code="guests_cannot_invite",
                status_code=403,
            )
        live = await self._connections.get(account.id)
        room_id = live.room_id if live is not None and live.room_id in self._world.rooms else None
        if room_id is None:
            room_id = self._rooms.current_room_for_account(account.id)
        if room_id not in self._world.rooms:
            room_id = self._world.entry_room_id

        token = secrets.token_urlsafe(GUEST_TOKEN_BYTES)
        now = utc_now()
        expires = now + GUEST_INVITE_TTL
        instance_id = self._config.mc_instance_id or ""
        self._invites[token] = GuestInviteRecord(
            inviter_account_id=account.id,
            world_id=self._world.id,
            instance_id=instance_id,
            room_id=room_id,
            expires_at=expires,
        )
        self._prune(now)
        room = self._world.rooms[room_id]
        query = urlencode({
            "world": self._world.id,
            "instance": instance_id,
            "inviter": account.username_display,
        })
        return GuestInviteLink(
            token=token,
            url=f"{public_base_url.rstrip('/')}/guest/{token}?{query}",
            world_id=self._world.id,
            instance_id=instance_id,
            room_id=room_id,
            room_label=room.label,
            inviter_username=account.username_display,
            expires_at=expires.isoformat(),
        )

    async def redeem(
        self,
        token: str,
        context: FingerprintContext,
        *,
        existing_account: AccountRecord | None,
    ) -> GuestRedeemResult:
        """Resolve an invite to an existing member or a reusable device guest."""

        if not GUEST_TOKEN_PATTERN.fullmatch(token or ""):
            raise GuestInviteError("This invite link is not valid.", code="invalid_invite", status_code=404)
        record = self._invites.get(token)
        if record is None:
            raise GuestInviteError("This invite link is not valid.", code="invalid_invite", status_code=404)
        if record.expires_at <= utc_now():
            self._invites.pop(token, None)
            raise GuestInviteError(
                "This invite link has expired.",
                code="expired_invite",
                status_code=410,
            )
        expected_instance = self._config.mc_instance_id or ""
        if record.world_id != self._world.id or record.instance_id != expected_instance:
            raise GuestInviteError(
                "This invite belongs to a different world.",
                code="invite_world_mismatch",
                status_code=404,
            )
        if not GUEST_DEVICE_ID_PATTERN.fullmatch(context.device_id or ""):
            raise GuestInviteError("Device information is missing.", code="invalid_device", status_code=400)

        room_id = await self._target_room(record.inviter_account_id, record.room_id)

        if existing_account is not None:
            account = existing_account
        else:
            fingerprint = self._fingerprint(context)
            account = self._profiles.find_guest_by_fingerprint(fingerprint)
            if account is None:
                account = self._create_guest(fingerprint, room_id)

        with self._hub.transaction() as connection:
            self._profiles.set_remembered_room(connection, account.id, self._world.id, room_id)
        if self._config.mc_instance_id:
            self._profiles.remember_instance(account.id, self._config.mc_instance_id)

        session, _ = self._profiles.issue_session(account.id)
        return GuestRedeemResult(
            session=session,
            redirect_url=self._redirect_url(),
        )

    def _prune(self, now: datetime) -> None:
        counts: dict[str, int] = {}
        for token, record in list(self._invites.items()):
            if record.expires_at <= now:
                self._invites.pop(token, None)
                continue
            count = counts.get(record.inviter_account_id, 0) + 1
            counts[record.inviter_account_id] = count
            if count > GUEST_INVITES_PER_ACCOUNT:
                self._invites.pop(token, None)

    async def _target_room(self, inviter_account_id: str, invite_room_id: str) -> str:
        live = await self._connections.get(inviter_account_id)
        candidates = (
            live.room_id if live is not None else None,
            invite_room_id,
            self._world.entry_room_id,
        )
        for candidate in candidates:
            if candidate in self._world.rooms:
                return candidate
        return self._world.entry_room_id

    def _create_guest(self, fingerprint: str, room_id: str) -> AccountRecord:
        constants = self._config.gameplay_options.constants
        starting_counters = {
            "health": constants.base_max_health,
            "max_health": constants.base_max_health,
            "cleanliness": constants.base_max_cleanliness,
            "max_cleanliness": constants.base_max_cleanliness,
        }
        stickers = self._accounts.list_stickers()
        last_error: Exception | None = None
        for _ in range(8):
            display_name = self._guest_name()
            try:
                return self._profiles.create_account(
                    display_name,
                    secrets.token_urlsafe(24),
                    self._world.id,
                    room_id,
                    starting_energy=constants.max_energy_per_level[0],
                    starting_counters=starting_counters,
                    is_guest=True,
                    guest_fingerprint=fingerprint,
                    sticker=secrets.choice(stickers),
                    initial_sticker_complete=True,
                )
            except AccountLimitError as exc:
                raise GuestInviteError(
                    "This instance has reached its guest account limit.",
                    code="account_limit_reached",
                    status_code=409,
                ) from exc
            except sqlite3.IntegrityError as exc:
                last_error = exc
                existing = self._profiles.find_guest_by_fingerprint(fingerprint)
                if existing is not None:
                    return existing
            except ValueError as exc:
                last_error = exc
        raise GuestInviteError(
            "A guest account could not be created.",
            code="guest_creation_failed",
            status_code=409,
        ) from last_error

    @staticmethod
    def _guest_name() -> str:
        return (
            f"{secrets.choice(GUEST_ADJECTIVES)}"
            f"{secrets.choice(GUEST_NOUNS)}"
            f"{secrets.randbelow(900) + 100}"
        )

    @staticmethod
    def _fingerprint(context: FingerprintContext) -> str:
        parts = (
            "guest-v1",
            context.device_id[:128],
            context.user_agent.strip()[:512],
            context.accept_language.strip()[:128],
            context.client_host.strip()[:128],
        )
        return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    def _redirect_url(self) -> str:
        base_path = self._config.base_path
        return f"{base_path}/" if base_path else "/"
