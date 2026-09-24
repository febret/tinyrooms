"""World-side outbound client: register, heartbeat, and graceful deregister.

The world server keeps serving players when mission control is unreachable; only
management is degraded.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import logging
import time
from typing import TYPE_CHECKING

import httpx

from server.protocol import PROTOCOL_VERSION
from server.version import BUILD_VERSION


if TYPE_CHECKING:
    from server.app import RuntimeState


LOGGER = logging.getLogger("tinyrooms.mc")
MAX_REGISTER_ATTEMPTS = 6


def _log(event: str, **fields: object) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}, separators=(",", ":")))


def _world_endpoint(host: str, port: int) -> str:
    advertised = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"https://{advertised}:{port}"


class McClient:
    """Registers this world server with mission control and heartbeats."""

    def __init__(self, runtime: RuntimeState, *, client: httpx.AsyncClient | None = None) -> None:
        self._runtime = runtime
        self._client = client
        self._owns_client = client is None
        self._endpoint = runtime.config.mc_endpoint or ""
        self._token = runtime.config.mc_token or ""
        self._instance_id: str | None = None
        self._heartbeat_seconds = 5.0
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def instance_id(self) -> str | None:
        return self._instance_id

    def _base_url(self) -> str:
        return f"https://{self._endpoint}"

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            verify: object = True
            if self._runtime.config.mc_insecure_tls:
                verify = False
            elif self._runtime.config.mc_ca_file is not None:
                verify = str(self._runtime.config.mc_ca_file)
            self._client = httpx.AsyncClient(verify=verify, timeout=5.0)
        return self._client

    def registration_payload(self) -> dict[str, object]:
        """Build the register request body."""

        config = self._runtime.config
        return {
            "instance_name": config.mc_name or f"{self._runtime.world.id}@{config.host}:{config.port}",
            "endpoint": _world_endpoint(config.host, config.port),
            "version": BUILD_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "world": {"id": self._runtime.world.id, "label": self._runtime.world.label},
            "started_at": datetime.fromtimestamp(self._runtime.started_at, tz=UTC).isoformat(),
        }

    async def register(self) -> dict[str, object]:
        """POST a registration and store the assigned instance id."""

        client = self._client_or_create()
        response = await client.post(
            f"{self._base_url()}/api/mc/register",
            json=self.registration_payload(),
            headers={"X-MC-Token": self._token},
        )
        response.raise_for_status()
        data = response.json()
        self._instance_id = str(data.get("instance_id") or "")
        heartbeat = data.get("heartbeat_seconds")
        if isinstance(heartbeat, (int, float)) and heartbeat > 0:
            self._heartbeat_seconds = float(heartbeat)
        _log("mc.registered", instance_id=self._instance_id)
        return data

    def heartbeat_payload(self) -> dict[str, object]:
        """Build the heartbeat request body."""

        return {
            "instance_id": self._instance_id,
            "uptime_seconds": round(time.time() - self._runtime.started_at, 2),
            "users_online": len(self._runtime.connections.list_all()),
            "world_id": self._runtime.world.id,
        }

    async def heartbeat(self) -> dict[str, object] | None:
        """POST one heartbeat; no-op until registered.

        A rejection for an unknown instance (for example after a mission-control
        restart) clears the stored id so the run loop re-registers.
        """

        if not self._instance_id:
            return None
        client = self._client_or_create()
        response = await client.post(
            f"{self._base_url()}/api/mc/heartbeat",
            json=self.heartbeat_payload(),
            headers={"X-MC-Token": self._token},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("ok") is False:
            _log("mc.heartbeat_rejected", instance_id=self._instance_id, code=data.get("code"))
            self._instance_id = None
        return data

    async def register_with_backoff(self) -> bool:
        """Attempt registration with bounded exponential backoff."""

        delay = 1.0
        for attempt in range(1, MAX_REGISTER_ATTEMPTS + 1):
            try:
                await self.register()
                return True
            except Exception as exc:  # noqa: BLE001 - never break gameplay
                _log("mc.register_failed", attempt=attempt, error=type(exc).__name__)
                if attempt == MAX_REGISTER_ATTEMPTS:
                    return False
                if await self._pause(delay):
                    return False
                delay = min(delay * 2, 30.0)
        return False

    async def _pause(self, timeout: float) -> bool:
        """Wait up to *timeout* seconds; return True if stop was requested."""

        try:
            await asyncio.wait_for(self._stop.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def run(self) -> None:
        """Register (re-registering on failure), then heartbeat until stopped."""

        while not self._stop.is_set():
            if not self._instance_id:
                if not await self.register_with_backoff():
                    if await self._pause(self._heartbeat_seconds):
                        return
                    continue
            if await self._pause(self._heartbeat_seconds):
                return
            try:
                await self.heartbeat()
            except Exception as exc:  # noqa: BLE001 - never break gameplay
                _log("mc.heartbeat_failed", error=type(exc).__name__)

    def start(self) -> None:
        """Start the background register/heartbeat loop."""

        if self._task is None:
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        """Stop the loop and best-effort deregister."""

        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass
            self._task = None
        if self._client is not None and self._instance_id:
            try:
                await self._client.post(
                    f"{self._base_url()}/api/mc/deregister",
                    json={"instance_id": self._instance_id},
                    headers={"X-MC-Token": self._token},
                )
            except Exception:  # noqa: BLE001 - best effort only
                pass
        if self._owns_client and self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
