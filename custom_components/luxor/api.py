"""Minimal, robust client for the FXLuminaire Luxor HTTP/JSON protocol.

Implements the behaviour required by the "Luxor Wi-Fi Module Protocol"
(Rev. 31):

* The controller is a slow master/slave device. All requests are serialized
  through one queue per controller.
* Requests that send data to the lights (IlluminateGroup, IlluminateTheme,
  ExtinguishAll, ...) may only be sent once per second (section 2.6).
* The controller answers with ``Connection: close``; connections are never
  reused (section 2.2).
* A request that is not answered is retried; after the configured number of
  attempts an error is raised (section 2.6).
* Every response carries a ``Status``; anything but 0 is an error and the
  payload must be ignored (sections 2.5 and 17).

Group intensity changes are queued per group: if a group already has a
pending change, the newest value replaces the older one ("last write wins").
When every known group is asked to switch off within a short window, a single
``ExtinguishAll`` is sent instead of one command per group.

This module deliberately has no Home Assistant imports so it can be tested
in isolation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_SEND_INTERVAL = 1.0
DEFAULT_TIMEOUT = 3.0
DEFAULT_ATTEMPTS = 3
DEFAULT_BATCH_WINDOW = 0.25

# Commands that make the controller send data to the fixtures. The protocol
# allows these only once per second. GroupListEdit is included because it can
# change the color of a group that is currently lit.
SEND_COMMANDS = frozenset(
    {
        "IlluminateGroup",
        "IlluminateTheme",
        "ExtinguishAll",
        "IlluminateAll",
        "GroupListEdit",
        "TestGroupSet",
        "TestGroupClear",
        "FlashLights",
    }
)

STATUS_COMMAND_NOT_FOUND = 1
STATUS_MESSAGES = {
    0: "OK",
    1: "Command Not Found",
    101: "Bad JSON Format",
    102: "JSON item missing from message",
    103: "JSON item is not an integer",
    151: "Color Value Out of Range",
    201: "Item not found",
    202: "Duplicate item",
    203: "Table Full",
    204: "Too Many Names",
    205: "Duplicate Group Number",
    206: "Illegal Name",
    241: "Item does not exist",
    242: "Bad Group Number",
    243: "Bad Schedule Number",
    244: "Bad Schedule Data",
    251: "Bad theme Index",
    252: "Theme Changes Restricted",
}

COLOR_LIST_SIZE = 250
COLOR_WHEEL_FIRST = 251
COLOR_WHEEL_LAST = 260
COLOR_DMX = 65535
UNUSED_COLOR = (360, 100)


class LuxorError(Exception):
    """Base error for the Luxor client."""


class LuxorConnectionError(LuxorError):
    """The controller could not be reached or did not answer."""


class LuxorStatusError(LuxorError):
    """The controller answered with a non-zero status code."""

    def __init__(self, command: str, status: Any) -> None:
        self.command = command
        self.status = status
        message = STATUS_MESSAGES.get(status, "Unknown status")
        super().__init__(f"Luxor {command} failed: status {status} ({message})")


class ControllerType(str, Enum):
    """Controller families described by the protocol."""

    ZD = "zd"  # monochrome, names "luxor-NNN"
    ZDC = "zdc"  # color, names "lxzdc-NNN"
    LUXOR2 = "luxor2"  # names "lxtwo-NNNN"
    UNKNOWN = "unknown"


MODEL_NAMES = {
    ControllerType.ZD: "Luxor ZD",
    ControllerType.ZDC: "Luxor ZDC",
    ControllerType.LUXOR2: "Luxor 2",
    ControllerType.UNKNOWN: "Luxor",
}


def controller_type_from_name(name: str) -> ControllerType:
    """Derive the controller family from its reported name (section 12.1)."""
    lowered = (name or "").lower()
    if lowered.startswith("lxtwo"):
        return ControllerType.LUXOR2
    if lowered.startswith("lxzdc"):
        return ControllerType.ZDC
    if lowered.startswith("luxor"):
        return ControllerType.ZD
    return ControllerType.UNKNOWN


@dataclass
class ControllerInfo:
    """Static information about a controller."""

    name: str
    type: ControllerType
    has_color: bool
    max_themes: int
    connection_type: str | None = None

    @property
    def model(self) -> str:
        return MODEL_NAMES[self.type]


@dataclass
class LuxorGroup:
    """One group (a set of fixtures switched together)."""

    number: int
    name: str
    intensity: int
    color: int = 0

    @property
    def is_dmx(self) -> bool:
        """Luxor 2 reports 65535 while a group is under DMX control."""
        return self.color == COLOR_DMX

    @property
    def is_color_wheel(self) -> bool:
        return COLOR_WHEEL_FIRST <= self.color <= COLOR_WHEEL_LAST

    @property
    def is_color(self) -> bool:
        return self.color != 0 and not self.is_dmx


@dataclass
class LuxorTheme:
    """One theme (called a scene in Home Assistant)."""

    index: int
    name: str
    on: bool


@dataclass
class ThemeList:
    themes: dict[int, LuxorTheme] = field(default_factory=dict)
    restricted: bool = False


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_groups(data: dict) -> dict[int, LuxorGroup]:
    """Parse GroupListGet for all controller families (section 5.5).

    ZD controllers use ``GroupNumber``/``Intensity``; ZDC and Luxor 2 use
    ``Grp``/``Inten``/``Colr``. Both forms are accepted.
    """
    groups: dict[int, LuxorGroup] = {}
    for item in data.get("GroupList") or []:
        if not isinstance(item, dict):
            continue
        number = _int(item.get("Grp", item.get("GroupNumber")), -1)
        if number < 1:
            continue
        groups[number] = LuxorGroup(
            number=number,
            name=str(item.get("Name") or f"Group {number}"),
            intensity=max(0, min(100, _int(item.get("Inten", item.get("Intensity"))))),
            color=_int(item.get("Colr", item.get("Color"))),
        )
    return groups


def parse_themes(data: dict) -> ThemeList:
    """Parse ThemeListGet (section 6.5)."""
    themes: dict[int, LuxorTheme] = {}
    for item in data.get("ThemeList") or []:
        if not isinstance(item, dict):
            continue
        index = _int(item.get("ThemeIndex"), -1)
        if index < 0:
            continue
        themes[index] = LuxorTheme(
            index=index,
            name=str(item.get("Name") or f"Theme {index}"),
            on=_int(item.get("OnOff")) == 1,
        )
    return ThemeList(themes=themes, restricted=_int(data.get("Restricted")) == 1)


def parse_colors(data: dict) -> dict[int, tuple[int, int]]:
    """Parse ColorListGet, dropping unused slots (section 9.2)."""
    colors: dict[int, tuple[int, int]] = {}
    for item in data.get("ColorList") or []:
        if not isinstance(item, dict):
            continue
        slot = _int(item.get("C"), -1)
        hue_sat = (_int(item.get("Hue"), 360), _int(item.get("Sat"), 100))
        if slot >= 1 and hue_sat != UNUSED_COLOR:
            colors[slot] = hue_sat
    return colors


class LuxorClient:
    """Serialized, rate-limited access to one Luxor controller."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        send_interval: float = DEFAULT_SEND_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        attempts: int = DEFAULT_ATTEMPTS,
        coalesce_extinguish: bool = True,
        batch_window: float = DEFAULT_BATCH_WINDOW,
    ) -> None:
        host = host.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        self._base_url = host
        self._session = session
        self._send_interval = max(0.0, send_interval)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._attempts = max(1, attempts)
        self._coalesce_extinguish = coalesce_extinguish
        self._batch_window = max(0.0, batch_window)

        self._lock = asyncio.Lock()
        self._last_send: float | None = None

        # Intensity changes waiting to be sent, per group (last write wins).
        self._pending: dict[int, int] = {}
        # Values currently being sent; still shown as the expected state.
        self._inflight: dict[int, int] = {}
        self._waiters: dict[int, list[asyncio.Future]] = {}
        self._worker: asyncio.Task | None = None
        self._closed = False

        self.known_groups: set[int] = set()

    @property
    def host(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------ core

    async def request(self, command: str, payload: dict | None = None) -> dict:
        """Send one command and return the decoded, status-checked response."""
        async with self._lock:
            return await self._request_locked(command, payload)

    async def _request_locked(self, command: str, payload: dict | None) -> dict:
        is_send = command in SEND_COMMANDS
        if is_send and self._last_send is not None:
            wait = self._last_send + self._send_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)

        url = f"{self._base_url}/{command}.json"
        last_error: Exception | None = None
        data: Any = None
        try:
            for attempt in range(1, self._attempts + 1):
                try:
                    async with self._session.post(
                        url,
                        json=payload or {},
                        timeout=self._timeout,
                        headers={"Connection": "close"},
                    ) as resp:
                        resp.raise_for_status()
                        data = await resp.json(content_type=None)
                    break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                    last_error = err
                    _LOGGER.debug(
                        "Luxor %s attempt %s/%s failed: %r",
                        command,
                        attempt,
                        self._attempts,
                        err,
                    )
                    if attempt < self._attempts:
                        await asyncio.sleep(0.2 * attempt)
            else:
                raise LuxorConnectionError(
                    f"Luxor {command}: no answer from {self._base_url} after "
                    f"{self._attempts} attempts ({last_error!r})"
                ) from last_error
        finally:
            if is_send:
                # Count failed attempts too: the controller may have acted.
                self._last_send = time.monotonic()

        if not isinstance(data, dict):
            raise LuxorConnectionError(f"Luxor {command}: unexpected answer {data!r}")
        status = data.get("Status", 0)
        if status != 0:
            raise LuxorStatusError(command, status)
        return data

    # -------------------------------------------------------------- reading

    async def async_get_info(self) -> ControllerInfo:
        """Identify the controller and its capabilities."""
        data = await self.request("ControllerName")
        name = str(data.get("Controller") or "luxor")
        ctype = controller_type_from_name(name)
        if ctype in (ControllerType.ZDC, ControllerType.LUXOR2):
            has_color = True
        elif ctype is ControllerType.ZD:
            has_color = False
        else:
            has_color = await self._probe_colors()
        return ControllerInfo(
            name=name,
            type=ctype,
            has_color=has_color,
            max_themes=40 if ctype is ControllerType.LUXOR2 else 26,
            connection_type=data.get("ConnType"),
        )

    async def _probe_colors(self) -> bool:
        try:
            await self.request("ColorListGet")
        except LuxorStatusError as err:
            if err.status == STATUS_COMMAND_NOT_FOUND:
                return False
            raise
        return True

    async def async_get_groups(self) -> dict[int, LuxorGroup]:
        groups = parse_groups(await self.request("GroupListGet"))
        self.known_groups = set(groups)
        return groups

    async def async_get_themes(self) -> ThemeList:
        return parse_themes(await self.request("ThemeListGet"))

    async def async_get_colors(self) -> dict[int, tuple[int, int]]:
        return parse_colors(await self.request("ColorListGet"))

    # -------------------------------------------------------------- writing

    async def async_set_color_slot(self, slot: int, hue: int, sat: int) -> None:
        await self.request("ColorListSet", {"C": slot, "Hue": hue, "Sat": sat})

    async def async_set_group_color(self, name: str, group: int, color: int) -> None:
        await self.request(
            "GroupListEdit", {"Name": name, "GroupNumber": group, "Color": color}
        )

    async def async_illuminate_theme(self, index: int, on: bool = True) -> None:
        await self.request("IlluminateTheme", {"ThemeIndex": index, "OnOff": 1 if on else 0})

    async def async_extinguish_all(self) -> None:
        await self.request("ExtinguishAll")

    async def async_illuminate_all(self) -> None:
        await self.request("IlluminateAll")

    def queue_group_intensity(self, group: int, intensity: int) -> asyncio.Future:
        """Queue an intensity change; the future resolves once it was sent.

        Must be called from the event loop. A newer change for the same group
        replaces a pending older one; all callers waiting for that group are
        released when the newest value has been sent.
        """
        if self._closed:
            raise LuxorError("Luxor client is closed")
        intensity = max(0, min(100, int(intensity)))
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[group] = intensity
        self._waiters.setdefault(group, []).append(future)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_queue())
        return future

    async def async_set_group_intensity(self, group: int, intensity: int) -> None:
        """Queue an intensity change and wait until it has been sent."""
        await self.queue_group_intensity(group, intensity)

    def expected_intensity(self, group: int) -> int | None:
        """Intensity a group is about to get, or None if nothing is queued."""
        if group in self._pending:
            return self._pending[group]
        return self._inflight.get(group)

    @property
    def busy(self) -> bool:
        """True while intensity changes are queued or being sent."""
        return bool(self._pending or self._inflight)

    async def _run_queue(self) -> None:
        if self._batch_window:
            await asyncio.sleep(self._batch_window)
        while self._pending:
            if self._should_extinguish_all():
                batch = dict(self._pending)
                self._pending.clear()
                waiters = [f for g in batch for f in self._waiters.pop(g, [])]
                await self._send(batch, waiters, "ExtinguishAll", None)
                continue
            group = next(iter(self._pending))
            intensity = self._pending.pop(group)
            waiters = self._waiters.pop(group, [])
            await self._send(
                {group: intensity},
                waiters,
                "IlluminateGroup",
                {"GroupNumber": group, "Intensity": intensity},
            )

    def _should_extinguish_all(self) -> bool:
        return (
            self._coalesce_extinguish
            and len(self._pending) > 1
            and bool(self.known_groups)
            and self.known_groups <= set(self._pending)
            and not any(self._pending.values())
        )

    async def _send(
        self,
        batch: dict[int, int],
        waiters: list[asyncio.Future],
        command: str,
        payload: dict | None,
    ) -> None:
        self._inflight.update(batch)
        error: Exception | None = None
        try:
            await self.request(command, payload)
        except Exception as err:  # noqa: BLE001 - handed to the waiting callers
            error = err
        finally:
            for group in batch:
                self._inflight.pop(group, None)
        for future in waiters:
            if future.done():
                continue
            if error is None:
                future.set_result(None)
            else:
                future.set_exception(error)

    async def async_close(self) -> None:
        """Stop the queue and fail all waiting callers."""
        self._closed = True
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        self._worker = None
        error = LuxorError("Luxor client closed")
        for futures in self._waiters.values():
            for future in futures:
                if not future.done():
                    future.set_exception(error)
        self._waiters.clear()
        self._pending.clear()
        self._inflight.clear()
