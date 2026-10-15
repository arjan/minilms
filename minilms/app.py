"""Wire aioslimproto, the stream proxy, stations and persisted state together."""

from __future__ import annotations

import logging
from urllib.parse import unquote, urlparse
import uuid

from aiohttp import web
from aioslimproto import SlimServer
from aioslimproto.client import SlimClient
from aioslimproto.models import ButtonCode, EventType, MediaMetadata, Preset, SlimEvent

from .artwork import ArtworkCache, parse_size
from .commands import CommandHandler
from .config import Config, Station
from .proxy import StreamProxy
from .state import StateStore
from .web import MiniCLI

LOGGER = logging.getLogger(__name__)

HTTP_PORT = 9000  # hardware players only look for the server on 9000
HARDWARE_PRESETS = {
    ButtonCode.PRESET_1: 1,
    ButtonCode.PRESET_2: 2,
    ButtonCode.PRESET_3: 3,
    ButtonCode.PRESET_4: 4,
    ButtonCode.PRESET_5: 5,
    ButtonCode.PRESET_6: 6,
}


class MiniLMS:
    def __init__(self, config: Config) -> None:
        self.config = config
        # Stable across restarts, so Home Assistant keeps recognising the server.
        self.server_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"minilms.{config.name}"))
        self.state = StateStore(config.state_file)
        self.proxy = StreamProxy(on_title=self._on_title)
        self.artwork = ArtworkCache(fetch=self.proxy.fetch_bytes)
        self.server = SlimServer(cli_port=None, ip_address=config.ip_address, name=config.name)
        self.server.cli = MiniCLI(self.server, HTTP_PORT, CommandHandler(self), self._add_routes)
        self._streams: dict[str, str] = {}  # player id -> stream id
        self._titles: dict[str, str] = {}  # stream id -> last ICY title

    async def start(self) -> None:
        await self.proxy.start()
        self.server.subscribe(
            self._on_event,
            (
                EventType.PLAYER_CONNECTED,
                EventType.PLAYER_NAME_RECEIVED,
                EventType.PLAYER_UPDATED,
                EventType.PLAYER_BTN_EVENT,
                EventType.PLAYER_CLI_EVENT,
            ),
        )
        await self.server.start()
        LOGGER.info(
            "minilms %r on %s: slimproto 3483, http %s, %d stations",
            self.config.name,
            self.server.ip_address,
            HTTP_PORT,
            len(self.config.stations),
        )

    async def stop(self) -> None:
        await self.server.stop()
        await self.proxy.stop()

    def _add_routes(self, app: web.Application) -> None:
        self.proxy.add_routes(app)
        app.router.add_get("/artwork/{station_id}", self._handle_artwork)
        app.router.add_get("/imageproxy/{rest:.+}", self._handle_imageproxy)

    def artwork_url(self, station: Station) -> str:
        if not station.icon:
            return ""
        return f"http://{self.server.ip_address}:{HTTP_PORT}/artwork/{station.id}"

    async def _serve_artwork(self, station: Station | None, spec: str) -> web.Response:
        if station is None or not station.icon:
            raise web.HTTPNotFound()
        width, height = parse_size(spec)
        try:
            body = await self.artwork.get(station.icon, width, height)
        except Exception as err:  # noqa: BLE001 - a broken logo must not break anything else
            LOGGER.warning("artwork for %s failed: %s", station.id, err)
            raise web.HTTPNotFound() from None
        return web.Response(body=body, content_type="image/png")

    async def _handle_artwork(self, request: web.Request) -> web.Response:
        station = self.config.station(request.match_info["station_id"])
        return await self._serve_artwork(station, request.query.get("size", ""))

    async def _handle_imageproxy(self, request: web.Request) -> web.Response:
        # LMS form: /imageproxy/<url-encoded url>/image_<W>x<H>_m.png. Split on the
        # last slash, so it works whether or not aiohttp decoded the %2F's.
        raw_url, _, spec = request.match_info["rest"].rpartition("/")
        url = unquote(raw_url)
        path = urlparse(url).path
        station = None
        if path.startswith("/artwork/"):
            station = self.config.station(path.removeprefix("/artwork/"))
        if station is None:
            station = next((s for s in self.config.stations if s.icon and s.icon == url), None)
        LOGGER.debug("imageproxy %s -> %s", url, station.id if station else None)
        return await self._serve_artwork(station, spec)

    def reload(self, config: Config) -> None:
        self.config = config
        self.artwork.clear()
        for player in self.server.players:
            self._apply_name(player)
            self._apply_presets(player)
        LOGGER.info("reloaded config: %d stations", len(config.stations))

    def _stream_url(self, stream_id: str) -> str:
        return f"http://{self.server.ip_address}:{HTTP_PORT}/stream/{stream_id}"

    def _apply_presets(self, player: SlimClient) -> None:
        player.presets = [
            Preset(uri=s.url, text=s.name, icon=self.artwork_url(s)) if s else Preset(uri="", text="", icon="")
            for s in self.config.presets()
        ]

    async def play_station(self, player_id: str, station_id: str) -> None:
        station = self.config.station(station_id)
        if station is None:
            LOGGER.warning("unknown station %r", station_id)
            return
        await self._play(player_id, station.id, station.url, station.name, station)

    async def play_preset(self, player_id: str, number: int) -> None:
        presets = self.config.presets()
        if 1 <= number <= len(presets) and (station := presets[number - 1]):
            await self.play_station(player_id, station.id)
        else:
            LOGGER.info("preset %s is not assigned", number)

    async def play_url(self, player_id: str, url: str, title: str | None) -> None:
        station = next((s for s in self.config.stations if s.url == url), None)
        if station:
            await self.play_station(player_id, station.id)
            return
        stream_id = self.proxy.register_adhoc(url)
        await self._play(player_id, stream_id, url, title or url, None)

    async def _play(
        self, player_id: str, stream_id: str, url: str, name: str, station: Station | None
    ) -> None:
        player = self.server.get_player(player_id)
        if player is None:
            LOGGER.warning("unknown player %r", player_id)
            return
        try:
            audio_url, mime_type = await self.proxy.resolve(url)
        except Exception as err:  # noqa: BLE001 - any upstream failure means: not playable
            LOGGER.warning("cannot open %s: %s", url, err)
            return
        self.proxy.register(stream_id, audio_url)
        self._streams[player_id] = stream_id
        metadata = MediaMetadata(title=name, album=name)
        if station and station.icon:
            metadata["image_url"] = self.artwork_url(station)
        await player.play_url(self._stream_url(stream_id), mime_type=mime_type, metadata=metadata)
        self.state.update(player_id, station_id=station.id if station else None, powered=True)

    def _on_title(self, stream_id: str, title: str) -> None:
        LOGGER.info("now playing on %s: %s", stream_id, title)
        self._titles[stream_id] = title
        for player in self.server.players:
            self._apply_title(player)

    def _apply_title(self, player: SlimClient) -> None:
        """Copy the last ICY title onto the player's current item.

        The first title often arrives while the player is still buffering, before
        current_media exists, so PLAYER_UPDATED retries this too.
        """
        stream_id = self._streams.get(player.player_id)
        media = player.current_media
        title = self._titles.get(stream_id) if stream_id else None
        if not title or not media or not media.url.endswith(f"/stream/{stream_id}"):
            return
        if media.metadata.get("title") != title:
            media.metadata["title"] = title
            player.signal_update()

    async def _on_event(self, event: SlimEvent) -> None:
        player = self.server.get_player(event.player_id)
        if player is None:
            return
        if event.type == EventType.PLAYER_CONNECTED:
            await self._on_connected(player)
        elif event.type == EventType.PLAYER_NAME_RECEIVED:
            # The Radio answers the name request after connecting; keep ours.
            self._apply_name(player)
        elif event.type == EventType.PLAYER_UPDATED and player.connected:
            self.state.update(player.player_id, volume=player.volume_level, powered=player.powered)
            self._apply_title(player)
        elif event.type == EventType.PLAYER_BTN_EVENT:
            button = (event.data or {}).get("button")
            if button in HARDWARE_PRESETS:
                await self.play_preset(player.player_id, HARDWARE_PRESETS[button])
            else:
                LOGGER.debug("unhandled button %s on %s", button, player.name)
        elif event.type == EventType.PLAYER_CLI_EVENT:
            # Commands nobody answered; the spike uses these to find gaps.
            LOGGER.info("unhandled command from %s: %s", player.name, event.data)

    def _apply_name(self, player: SlimClient) -> None:
        """Use the configured name, else the model name for an unusable one.

        aioslimproto names a player that reports nothing "<type>: <mac>", and the
        Squeezebox Radio reports a stored, truncated name of that same form. Sets
        a private attribute; safe while aioslimproto stays pinned.
        """
        name = self.config.player_names.get(player.player_id)
        if not name:
            reported = player._device_name  # noqa: SLF001
            if reported and not reported.startswith(f"{player.device_type}:"):
                return
            name = player.device_model
        player._device_name = name  # noqa: SLF001

    async def _on_connected(self, player: SlimClient) -> None:
        self._apply_name(player)
        LOGGER.info("player connected: %s (%s)", player.name, player.player_id)
        self._apply_presets(player)
        saved = self.state.get(player.player_id)
        volume = saved.volume if saved.volume is not None else self.config.default_volume
        await player.volume_set(volume)
        if saved.powered and saved.station_id:
            await self.play_station(player.player_id, saved.station_id)
