"""HTTP proxy between internet radio stations and the players.

The Squeezebox Radio cannot open HTTPS streams and cannot parse ICY metadata,
so every stream goes through here: the proxy fetches the upstream (http or
https), strips the metadata, reports titles, and serves plain audio over
HTTP/1.0.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
import logging
import secrets

from aiohttp import ClientSession, ClientTimeout, web

from .icy import IcyStripper

LOGGER = logging.getLogger(__name__)

USER_AGENT = "minilms/0.1"
PLAYLIST_TYPES = {
    "audio/x-mpegurl",
    "audio/mpegurl",
    "application/vnd.apple.mpegurl",
    "audio/x-scpls",
    "application/pls+xml",
}
UPSTREAM_TIMEOUT = ClientTimeout(total=None, sock_connect=10, sock_read=30)
MAX_ADHOC = 16

TitleCallback = Callable[[str, str], None]


def _content_type(headers) -> str:
    return headers.get("Content-Type", "").split(";")[0].strip().lower()


def first_url_in_playlist(body: str) -> str | None:
    """Return the first http(s) entry of an M3U or PLS playlist."""
    for line in body.splitlines():
        line = line.strip()
        if line.lower().startswith("file") and "=" in line:  # PLS: File1=http://...
            line = line.split("=", 1)[1].strip()
        if line.startswith(("http://", "https://")):
            return line
    return None


class StreamProxy:
    def __init__(self, on_title: TitleCallback) -> None:
        self._on_title = on_title
        self._targets: dict[str, str] = {}
        self._adhoc: OrderedDict[str, str] = OrderedDict()
        self._session: ClientSession | None = None

    async def start(self) -> None:
        self._session = ClientSession(
            timeout=UPSTREAM_TIMEOUT, headers={"User-Agent": USER_AGENT}
        )

    async def stop(self) -> None:
        if self._session:
            await self._session.close()

    def register(self, stream_id: str, url: str) -> None:
        """Map a stream id to an already resolved audio URL (see resolve)."""
        self._targets[stream_id] = url

    def register_adhoc(self, url: str) -> str:
        """Register a one-off URL (e.g. from Home Assistant) and return its id."""
        for stream_id, known in self._adhoc.items():
            if known == url:
                return stream_id
        stream_id = f"adhoc-{secrets.token_hex(4)}"
        self._adhoc[stream_id] = url
        while len(self._adhoc) > MAX_ADHOC:
            self._adhoc.popitem(last=False)
        return stream_id

    def target(self, stream_id: str) -> str | None:
        return self._targets.get(stream_id) or self._adhoc.get(stream_id)

    async def resolve(self, url: str) -> tuple[str, str | None]:
        """Follow a playlist URL to the audio stream; return (url, mime type)."""
        assert self._session is not None
        for _ in range(3):
            async with self._session.get(url, headers={"Icy-MetaData": "1"}) as resp:
                resp.raise_for_status()
                ctype = _content_type(resp.headers)
                if ctype not in PLAYLIST_TYPES and not url.lower().endswith((".m3u", ".pls")):
                    return url, ctype or None
                body = await resp.content.read(64 * 1024)
            next_url = first_url_in_playlist(body.decode("utf-8", "replace"))
            if next_url is None:
                raise ValueError(f"no stream URL in playlist {url}")
            url = next_url
        raise ValueError(f"playlist nesting too deep at {url}")

    async def fetch_bytes(self, url: str, limit: int = 2 * 1024 * 1024) -> bytes:
        assert self._session is not None
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.content.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"{url} is larger than {limit} bytes")
        return data

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/stream/{stream_id}", self._handle_stream)

    def make_app(self) -> web.Application:
        app = web.Application()
        self.add_routes(app)
        return app

    async def _handle_stream(self, request: web.Request) -> web.StreamResponse:
        stream_id = request.match_info["stream_id"]
        url = self.target(stream_id)
        if url is None:
            raise web.HTTPNotFound()
        assert self._session is not None
        LOGGER.info("streaming %s from %s to %s", stream_id, url, request.remote)
        async with self._session.get(url, headers={"Icy-MetaData": "1"}) as upstream:
            if upstream.status != 200:
                LOGGER.warning("upstream %s answered %s", url, upstream.status)
                raise web.HTTPBadGateway()
            metaint = int(upstream.headers.get("icy-metaint", "0") or 0)
            stripper = IcyStripper(metaint) if metaint > 0 else None
            response = web.StreamResponse(
                headers={"Content-Type": _content_type(upstream.headers) or "audio/mpeg"}
            )
            response.force_close()
            await response.prepare(request)
            try:
                async for chunk in upstream.content.iter_any():
                    if stripper:
                        chunk, titles = stripper.feed(chunk)
                        for title in titles:
                            self._on_title(stream_id, title)
                    if chunk:
                        await response.write(chunk)
            except (ConnectionResetError, ConnectionError):
                LOGGER.info("player closed stream %s", stream_id)
        return response
