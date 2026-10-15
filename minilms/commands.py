"""CLI / JSON-RPC / CometD commands that aioslimproto does not answer itself.

aioslimproto calls this handler first; raising NotImplementedError hands the
command to its built-in handlers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aioslimproto.cli import SlimCLICommand

if TYPE_CHECKING:
    from .app import MiniLMS

LOGGER = logging.getLogger(__name__)

RADIO_MENU_ID = "radios"
SERVER_VERSION = "9.0.0"


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class CommandHandler:
    def __init__(self, app: MiniLMS) -> None:
        self.app = app

    async def __call__(self, cmd: SlimCLICommand) -> Any:
        method = getattr(self, f"cmd_{cmd.command}", None)
        if method is None:
            raise NotImplementedError(cmd.command)
        return await method(cmd)

    def home_menu(self) -> list[dict[str, Any]]:
        # Same id and action as LMS's own entry: the player skin shows its
        # built-in radio icon for id "radios", and "go" opens a browse window
        # (with artwork) from the `radios ... menu:radio` command below.
        return [
            {
                "id": RADIO_MENU_ID,
                "text": "Internet Radio",
                "node": "home",
                "weight": 20,
                "actions": {"go": {"cmd": ["radios"], "params": {"menu": "radio"}}},
            }
        ]

    def station_items(self) -> list[dict[str, Any]]:
        items = []
        for station in self.app.config.stations:
            play = {
                "player": 0,
                "cmd": ["minilms", "play"],
                "params": {"station": station.id},
                "nextWindow": "nowPlaying",
            }
            item: dict[str, Any] = {
                "text": station.name,
                "style": "itemplay",
                "nextWindow": "nowPlaying",
                "actions": {"go": play, "play": play},
            }
            if icon := self.app.artwork_url(station):
                item["icon"] = icon
            items.append(item)
        return items

    async def cmd_menu(self, cmd: SlimCLICommand) -> dict[str, Any]:
        offset = _int(cmd.args[0] if cmd.args else 0, 0)
        limit = _int(cmd.args[1] if len(cmd.args) > 1 else 100, 100)
        items = self.home_menu()
        page = items[offset : offset + limit]
        return {"item_loop": page, "offset": offset, "count": len(items)}

    async def cmd_minilms(self, cmd: SlimCLICommand) -> None:
        if cmd.args[:1] != ["play"] or not cmd.player_id:
            raise NotImplementedError("minilms")
        await self.app.play_station(cmd.player_id, str(cmd.kwargs.get("station", "")))

    async def cmd_button(self, cmd: SlimCLICommand) -> None:
        button = str(cmd.args[0]) if cmd.args else ""
        if cmd.player_id and button.startswith("preset_") and button.endswith(".single"):
            number = _int(button[len("preset_") :].split(".", 1)[0], 0)
            await self.app.play_preset(cmd.player_id, number)
            return
        raise NotImplementedError(f"button {button}")

    async def cmd_playlist(self, cmd: SlimCLICommand) -> None:
        # pysqueezebox's async_load_url sends: playlist <play|load> <url>
        if (
            cmd.player_id
            and len(cmd.args) >= 2
            and cmd.args[0] in ("play", "load")
            and str(cmd.args[1]).startswith(("http://", "https://"))
        ):
            title = str(cmd.args[2]) if len(cmd.args) > 2 else None
            await self.app.play_url(cmd.player_id, str(cmd.args[1]), title)
            return
        raise NotImplementedError("playlist")

    async def cmd_serverstatus(self, cmd: SlimCLICommand) -> dict[str, Any]:
        # Private aioslimproto method; safe while the version stays pinned.
        result = await self.app.server.cli._handle_serverstatus(  # noqa: SLF001
            cmd.player_id or "", *cmd.args, **cmd.kwargs
        )
        result["version"] = SERVER_VERSION
        result["uuid"] = self.app.server_uuid
        return result

    async def cmd_alarms(self, cmd: SlimCLICommand) -> dict[str, Any]:
        return {"count": 0, "fade": "0", "alarms_loop": []}

    async def cmd_favorites(self, cmd: SlimCLICommand) -> dict[str, Any]:
        return {"count": 0, "loop_loop": []}

    async def cmd_apps(self, cmd: SlimCLICommand) -> dict[str, Any]:
        return {"count": 0, "appss_loop": []}

    async def cmd_radios(self, cmd: SlimCLICommand) -> dict[str, Any]:
        if "menu" not in cmd.kwargs:
            # Plain CLI form (Home Assistant's media browser): no radio apps.
            return {"count": 0, "radioss_loop": []}
        offset = _int(cmd.args[0] if cmd.args else 0, 0)
        limit = _int(cmd.args[1] if len(cmd.args) > 1 else 100, 100)
        items = self.station_items()
        return {
            "item_loop": items[offset : offset + limit],
            "offset": offset,
            "count": len(items),
            "window": {"windowStyle": "icon_list", "text": "Internet Radio"},
        }
