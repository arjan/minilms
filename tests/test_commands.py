from types import SimpleNamespace
from unittest.mock import AsyncMock

from aioslimproto.cli import SlimCLICommand
import pytest

from minilms.commands import RADIO_MENU_ID, CommandHandler
from minilms.config import parse_config


@pytest.fixture
def handler():
    config = parse_config(
        {
            "stations": [
                {"id": "a", "name": "A", "url": "http://a", "preset": 2},
                {"id": "b", "name": "B", "url": "http://b", "icon": "http://b.png"},
            ]
        }
    )
    app = SimpleNamespace(
        config=config,
        server_uuid="uuid-1",
        artwork_url=lambda s: f"http://srv:9000/artwork/{s.id}" if s.icon else "",
        play_station=AsyncMock(),
        play_preset=AsyncMock(),
        play_url=AsyncMock(),
        server=SimpleNamespace(
            cli=SimpleNamespace(
                _handle_serverstatus=AsyncMock(return_value={"uuid": "aioslimproto", "version": "7"})
            )
        ),
    )
    return CommandHandler(app)


def cmd(command, *args, player="00:04:20:aa:bb:cc", **kwargs):
    return SlimCLICommand(player_id=player, command=command, args=list(args), kwargs=kwargs)


async def test_home_menu_has_lms_style_radio_entry(handler):
    result = await handler(cmd("menu", 0, 100, direct=1))
    assert result["count"] == 1
    (entry,) = result["item_loop"]
    assert entry["id"] == RADIO_MENU_ID == "radios"
    assert entry["node"] == "home"
    assert entry["actions"]["go"] == {"cmd": ["radios"], "params": {"menu": "radio"}}


async def test_radios_menu_lists_stations_with_artwork(handler):
    result = await handler(cmd("radios", 0, 100, menu="radio"))
    assert result["count"] == 2
    assert result["window"]["windowStyle"] == "icon_list"
    a, b = result["item_loop"]
    assert a["actions"]["go"]["cmd"] == ["minilms", "play"]
    assert a["actions"]["go"]["params"] == {"station": "a"}
    assert "icon" not in a
    assert b["icon"] == "http://srv:9000/artwork/b"


async def test_radios_paging(handler):
    result = await handler(cmd("radios", 1, 1, menu="radio"))
    assert [i["text"] for i in result["item_loop"]] == ["B"]
    assert result["count"] == 2


async def test_radios_without_menu_is_empty_for_home_assistant(handler):
    assert await handler(cmd("radios", 0, 100)) == {"count": 0, "radioss_loop": []}


async def test_play_from_menu(handler):
    await handler(cmd("minilms", "play", station="b"))
    handler.app.play_station.assert_awaited_once_with("00:04:20:aa:bb:cc", "b")


async def test_preset_button(handler):
    await handler(cmd("button", "preset_2.single"))
    handler.app.play_preset.assert_awaited_once_with("00:04:20:aa:bb:cc", 2)
    with pytest.raises(NotImplementedError):
        await handler(cmd("button", "volup"))


async def test_playlist_play_url_from_home_assistant(handler):
    await handler(cmd("playlist", "load", "https://x/y", "Title"))
    handler.app.play_url.assert_awaited_once_with("00:04:20:aa:bb:cc", "https://x/y", "Title")
    with pytest.raises(NotImplementedError):
        await handler(cmd("playlist", "index", "+1"))


async def test_serverstatus_overrides_identity(handler):
    result = await handler(cmd("serverstatus", "-", "-", player=None))
    assert result == {"uuid": "uuid-1", "version": "9.0.0"}


async def test_unknown_command_falls_through(handler):
    with pytest.raises(NotImplementedError):
        await handler(cmd("status", "-", 1))
