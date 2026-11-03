"""A simulated Luxor controller that stands in for an aiohttp session."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    async def json(self, content_type=None) -> Any:
        return self._data


class _RequestContext:
    def __init__(self, controller: "FakeController", url: str, payload: dict) -> None:
        self._controller = controller
        self._url = url
        self._payload = payload

    async def __aenter__(self) -> FakeResponse:
        return await self._controller.handle(self._url, self._payload)

    async def __aexit__(self, *exc) -> None:
        return None


class FakeController:
    """Speaks enough of the Luxor protocol for the tests.

    ``kind`` is "zd", "zdc" or "luxor2" and selects the controller name and
    the GroupListGet field names, which differ between the families.
    """

    NAMES = {"zd": "luxor-12", "zdc": "lxzdc-34", "luxor2": "lxtwo-275610"}

    def __init__(self, kind: str = "luxor2", name: str | None = None) -> None:
        self.kind = kind
        self.name = name or self.NAMES[kind]
        self.groups: dict[int, dict[str, Any]] = {
            1: {"name": "Wall", "intensity": 0, "color": 0},
            2: {"name": "Tree", "intensity": 0, "color": 0 if kind == "zd" else 5},
            3: {"name": "Hedge", "intensity": 40, "color": 0},
        }
        self.themes = {0: {"name": "All on", "on": 0, "groups": {1: 100, 2: 80, 3: 60}}}
        self.colors = {5: (300, 100)}
        self.calls: list[tuple[float, str, dict]] = []
        # command -> number of upcoming calls that drop the connection
        self.disconnect: dict[str, int] = {}
        # command -> status code to answer with
        self.status: dict[str, int] = {}
        self.delay = 0.0

    def commands(self, *names: str) -> list[tuple[str, dict]]:
        return [(c, p) for _, c, p in self.calls if not names or c in names]

    def times(self, *names: str) -> list[float]:
        return [t for t, c, _ in self.calls if c in names]

    # aiohttp.ClientSession compatible entry point
    def post(self, url: str, json: dict | None = None, **kwargs) -> _RequestContext:
        return _RequestContext(self, url, json or {})

    async def handle(self, url: str, payload: dict) -> FakeResponse:
        command = url.rsplit("/", 1)[-1].removesuffix(".json")
        self.calls.append((time.monotonic(), command, dict(payload)))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.disconnect.get(command, 0) > 0:
            self.disconnect[command] -= 1
            raise aiohttp.ServerDisconnectedError()
        if command in self.status:
            return FakeResponse({"Status": self.status[command]})
        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            return FakeResponse({"Status": 1})
        return FakeResponse(handler(payload))

    # ---------------------------------------------------------- commands

    def _cmd_ControllerName(self, payload):
        return {"Status": 0, "Controller": self.name}

    def _cmd_GroupListGet(self, payload):
        items = []
        for number, g in self.groups.items():
            if self.kind == "zd":
                items.append(
                    {"Name": g["name"], "GroupNumber": number, "Intensity": g["intensity"]}
                )
            else:
                items.append(
                    {
                        "Name": g["name"],
                        "Grp": number,
                        "Inten": g["intensity"],
                        "Colr": g["color"],
                    }
                )
        return {"Status": 0, "GroupList": items}

    def _cmd_ThemeListGet(self, payload):
        return {
            "Status": 0,
            "Restricted": 0,
            "ThemeList": [
                {"Name": t["name"], "ThemeIndex": i, "OnOff": t["on"]}
                for i, t in self.themes.items()
            ],
        }

    def _cmd_ColorListGet(self, payload):
        if self.kind == "zd":
            return {"Status": 1}
        return {
            "Status": 0,
            "ListSize": 250,
            "ColorList": [
                {"C": c, "Hue": hs[0], "Sat": hs[1]} for c, hs in self.colors.items()
            ]
            + [{"C": 99, "Hue": 360, "Sat": 100}],
        }

    def _cmd_ColorListSet(self, payload):
        self.colors[payload["C"]] = (payload["Hue"], payload["Sat"])
        return {"Status": 0}

    def _cmd_GroupListEdit(self, payload):
        group = self.groups.get(payload["GroupNumber"])
        if group is None:
            return {"Status": 201}
        group["color"] = payload.get("Color", group["color"])
        return {"Status": 0}

    def _cmd_IlluminateGroup(self, payload):
        group = self.groups.get(payload["GroupNumber"])
        if group is None:
            return {"Status": 242}
        group["intensity"] = payload["Intensity"]
        return {"Status": 0}

    def _cmd_IlluminateTheme(self, payload):
        theme = self.themes.get(payload["ThemeIndex"])
        if theme is None:
            return {"Status": 251}
        theme["on"] = payload["OnOff"]
        for number, intensity in theme["groups"].items():
            self.groups[number]["intensity"] = intensity if payload["OnOff"] else 0
        return {"Status": 0}

    def _cmd_ExtinguishAll(self, payload):
        for group in self.groups.values():
            group["intensity"] = 0
        return {"Status": 0}
