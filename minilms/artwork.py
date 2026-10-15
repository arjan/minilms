"""Station logos, fetched once, resized for the player and cached in memory.

Players get `/artwork/<station id>` URLs. SqueezePlay may also ask for the
same image through LMS's `/imageproxy/<url-encoded url>/image_<W>x<H>_m.png`
form. Both are served only for configured stations, so this is not an open
proxy.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import io
import logging
import re

from PIL import Image

LOGGER = logging.getLogger(__name__)

MAX_SIDE = 500
DEFAULT_SIDE = 300
_SIZE_RE = re.compile(r"(\d+)x(\d+)")


def parse_size(spec: str) -> tuple[int, int]:
    """Size from an LMS resize spec such as `image_240x240_m.png`."""
    if match := _SIZE_RE.search(spec):
        width, height = (min(int(v), MAX_SIDE) for v in match.groups())
        if width > 0 and height > 0:
            return width, height
    return DEFAULT_SIDE, DEFAULT_SIDE


def render_png(data: bytes, width: int, height: int) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGBA")
        image.thumbnail((width, height))
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        return out.getvalue()


class ArtworkCache:
    def __init__(self, fetch: Callable[[str], Awaitable[bytes]]) -> None:
        self._fetch = fetch
        self._originals: dict[str, bytes] = {}
        self._rendered: dict[tuple[str, int, int], bytes] = {}

    def clear(self) -> None:
        self._originals.clear()
        self._rendered.clear()

    async def get(self, url: str, width: int, height: int) -> bytes:
        key = (url, width, height)
        if key not in self._rendered:
            if url not in self._originals:
                self._originals[url] = await self._fetch(url)
            self._rendered[key] = await asyncio.to_thread(
                render_png, self._originals[url], width, height
            )
        return self._rendered[key]
