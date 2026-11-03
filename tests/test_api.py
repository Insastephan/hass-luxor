"""Tests for the protocol client, independent of Home Assistant entities."""
import asyncio

import pytest

from custom_components.luxor.api import (
    ControllerType,
    LuxorClient,
    LuxorConnectionError,
    LuxorStatusError,
    controller_type_from_name,
    parse_groups,
)

from .fake_controller import FakeController

FAST = {"send_interval": 0.2, "timeout": 1.0, "batch_window": 0.05}


def make(kind="luxor2", **kwargs):
    controller = FakeController(kind)
    return controller, LuxorClient(controller, "192.0.2.1", **{**FAST, **kwargs})


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("luxor-12", ControllerType.ZD),
        ("luxor", ControllerType.ZD),
        ("lxzdc-34", ControllerType.ZDC),
        ("lxtwo-275610", ControllerType.LUXOR2),
        ("lxtwo", ControllerType.LUXOR2),
        ("something", ControllerType.UNKNOWN),
    ],
)
def test_controller_type_from_name(name, expected):
    assert controller_type_from_name(name) is expected


@pytest.mark.parametrize(
    ("kind", "has_color", "max_themes"),
    [("zd", False, 26), ("zdc", True, 26), ("luxor2", True, 40)],
)
async def test_info_and_groups_for_every_family(kind, has_color, max_themes):
    controller, client = make(kind)
    info = await client.async_get_info()
    assert info.has_color is has_color
    assert info.max_themes == max_themes

    groups = await client.async_get_groups()
    assert set(groups) == {1, 2, 3}
    assert groups[3].intensity == 40
    assert groups[3].name == "Hedge"
    assert client.known_groups == {1, 2, 3}


async def test_unknown_controller_probes_for_colors():
    controller = FakeController("zd", name="custom-name")
    client = LuxorClient(controller, "192.0.2.1", **FAST)
    info = await client.async_get_info()
    assert info.type is ControllerType.UNKNOWN
    assert info.has_color is False  # ColorListGet answered "Command Not Found"


def test_parse_groups_special_colors():
    groups = parse_groups(
        {
            "Status": 0,
            "GroupList": [
                {"Name": "DMX", "Grp": 1, "Inten": 50, "Colr": 65535},
                {"Name": "Wheel", "Grp": 2, "Inten": 50, "Colr": 253},
                {"Name": "Bad", "Grp": "x", "Inten": 10},
            ],
        }
    )
    assert groups[1].is_dmx and not groups[1].is_color
    assert groups[2].is_color_wheel and groups[2].is_color
    assert 0 not in groups and len(groups) == 2


async def test_colors_drop_unused_slots():
    controller, client = make("luxor2")
    assert await client.async_get_colors() == {5: (300, 100)}


async def test_switching_commands_are_spaced():
    controller, client = make("luxor2", coalesce_extinguish=False)
    await client.async_get_groups()
    await asyncio.gather(
        client.async_set_group_intensity(1, 100),
        client.async_set_group_intensity(2, 50),
        client.async_set_group_intensity(3, 0),
    )
    times = controller.times("IlluminateGroup")
    assert len(times) == 3
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap >= 0.19 for gap in gaps), gaps
    assert [g["intensity"] for g in controller.groups.values()] == [100, 50, 0]


async def test_reads_are_not_delayed_by_spacing():
    controller, client = make("luxor2")
    await client.async_illuminate_theme(0)
    start = asyncio.get_running_loop().time()
    await client.async_get_groups()
    assert asyncio.get_running_loop().time() - start < 0.15


async def test_last_write_wins_per_group():
    controller, client = make("luxor2", coalesce_extinguish=False)
    await asyncio.gather(
        client.async_set_group_intensity(1, 10),
        client.async_set_group_intensity(1, 20),
        client.async_set_group_intensity(1, 30),
    )
    assert controller.commands("IlluminateGroup") == [
        ("IlluminateGroup", {"GroupNumber": 1, "Intensity": 30})
    ]
    assert controller.groups[1]["intensity"] == 30


async def test_all_off_becomes_one_extinguish_all():
    controller, client = make("luxor2")
    await client.async_get_groups()
    await asyncio.gather(*(client.async_set_group_intensity(g, 0) for g in (1, 2, 3)))
    assert [c for c, _ in controller.commands("IlluminateGroup", "ExtinguishAll")] == [
        "ExtinguishAll"
    ]


async def test_partial_off_is_not_coalesced():
    controller, client = make("luxor2")
    await client.async_get_groups()
    await asyncio.gather(*(client.async_set_group_intensity(g, 0) for g in (1, 2)))
    assert [c for c, _ in controller.commands("IlluminateGroup", "ExtinguishAll")] == [
        "IlluminateGroup",
        "IlluminateGroup",
    ]


async def test_coalescing_can_be_disabled():
    controller, client = make("luxor2", coalesce_extinguish=False)
    await client.async_get_groups()
    await asyncio.gather(*(client.async_set_group_intensity(g, 0) for g in (1, 2, 3)))
    assert not controller.commands("ExtinguishAll")
    assert len(controller.commands("IlluminateGroup")) == 3


async def test_expected_intensity_while_queued():
    controller, client = make("luxor2")
    future = client.queue_group_intensity(2, 70)
    assert client.expected_intensity(2) == 70
    assert client.busy
    await future
    assert not client.busy
    # Acknowledged, but not read back yet: still reported as expected value.
    assert client.expected_intensity(2) == 70
    await client.async_get_groups()
    assert client.expected_intensity(2) is None


async def test_failed_command_is_not_confirmed():
    controller, client = make("luxor2")
    controller.status["IlluminateGroup"] = 242
    with pytest.raises(LuxorStatusError):
        await client.async_set_group_intensity(2, 70)
    assert client.expected_intensity(2) is None


async def test_dropped_connection_is_retried():
    controller, client = make("luxor2")
    controller.disconnect["IlluminateGroup"] = 2
    await client.async_set_group_intensity(1, 100)
    assert len(controller.commands("IlluminateGroup")) == 3
    assert controller.groups[1]["intensity"] == 100


async def test_gives_up_after_all_attempts():
    controller, client = make("luxor2", attempts=3)
    controller.disconnect["GroupListGet"] = 10
    with pytest.raises(LuxorConnectionError):
        await client.async_get_groups()
    assert len(controller.commands("GroupListGet")) == 3


async def test_status_error_is_raised_and_not_retried():
    controller, client = make("luxor2")
    with pytest.raises(LuxorStatusError) as err:
        await client.async_set_group_intensity(42, 100)
    assert err.value.status == 242
    assert "Bad Group Number" in str(err.value)
    assert len(controller.commands("IlluminateGroup")) == 1


async def test_failure_releases_every_waiter():
    controller, client = make("luxor2")
    controller.status["IlluminateGroup"] = 242
    results = await asyncio.gather(
        client.async_set_group_intensity(1, 10),
        client.async_set_group_intensity(1, 20),
        return_exceptions=True,
    )
    assert all(isinstance(r, LuxorStatusError) for r in results)
    assert not client.busy


async def test_close_fails_pending_callers():
    controller, client = make("luxor2", batch_window=5)
    future = client.queue_group_intensity(1, 10)
    await client.async_close()
    with pytest.raises(Exception):
        await future


async def test_retry_of_switching_command_keeps_spacing():
    """A switching command without answer may have been executed, so the retry
    must respect the minimum spacing as well."""
    controller, client = make("luxor2")
    controller.disconnect["IlluminateGroup"] = 1
    await client.async_set_group_intensity(1, 100)
    times = controller.times("IlluminateGroup")
    assert len(times) == 2
    assert times[1] - times[0] >= 0.19


async def test_retry_of_read_is_quick():
    controller, client = make("luxor2", send_interval=5.0)
    controller.disconnect["GroupListGet"] = 1
    start = asyncio.get_running_loop().time()
    await client.async_get_groups()
    assert asyncio.get_running_loop().time() - start < 1.0


async def test_unreachable_controller_fails_whole_queue_fast():
    controller, client = make("luxor2", coalesce_extinguish=False, attempts=3)
    controller.disconnect["IlluminateGroup"] = 100
    results = await asyncio.gather(
        client.async_set_group_intensity(1, 100),
        client.async_set_group_intensity(2, 100),
        client.async_set_group_intensity(3, 100),
        return_exceptions=True,
    )
    assert all(isinstance(r, LuxorConnectionError) for r in results)
    # Only the first group went through its retries; the others were dropped.
    assert len(controller.commands("IlluminateGroup")) == 3
    assert not client.busy
    assert all(client.expected_intensity(g) is None for g in (1, 2, 3))


async def test_status_error_does_not_drop_the_queue():
    controller, client = make("luxor2", coalesce_extinguish=False)
    results = await asyncio.gather(
        client.async_set_group_intensity(42, 100),  # unknown group: status 242
        client.async_set_group_intensity(1, 100),
        return_exceptions=True,
    )
    assert isinstance(results[0], LuxorStatusError)
    assert results[1] is None
    assert controller.groups[1]["intensity"] == 100


async def test_answer_without_status_is_accepted(caplog):
    controller, client = make("luxor2")
    controller._cmd_ControllerName = lambda payload: {"Controller": "lxtwo-1"}
    with caplog.at_level("DEBUG", logger="custom_components.luxor.api"):
        info = await client.async_get_info()
    assert info.name == "lxtwo-1"
    assert "answer without Status" in caplog.text
