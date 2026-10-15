"""Strip ICY (SHOUTcast) metadata from an audio stream.

With `Icy-MetaData: 1`, a server inserts a metadata block after every
`icy-metaint` audio bytes: one length byte N, then N*16 bytes of text such as
`StreamTitle='Artist - Title';`. The player must not see those blocks.
"""

from __future__ import annotations

import re

_TITLE_RE = re.compile(rb"StreamTitle='(.*?)';", re.DOTALL)


def parse_stream_title(block: bytes) -> str | None:
    match = _TITLE_RE.search(block.rstrip(b"\0"))
    if match is None:
        return None
    raw = match.group(1)
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return raw.decode("latin-1").strip()


class IcyStripper:
    """Incremental parser: feed raw chunks, get audio bytes and new titles."""

    def __init__(self, metaint: int) -> None:
        if metaint <= 0:
            raise ValueError("metaint must be positive")
        self._metaint = metaint
        self._audio_left = metaint
        self._meta_len: int | None = None  # None: expecting audio or a length byte
        self._meta_buf = bytearray()

    def feed(self, data: bytes) -> tuple[bytes, list[str]]:
        audio = bytearray()
        titles: list[str] = []
        pos = 0
        while pos < len(data):
            if self._audio_left > 0:
                take = min(self._audio_left, len(data) - pos)
                audio += data[pos : pos + take]
                pos += take
                self._audio_left -= take
            elif self._meta_len is None:
                self._meta_len = data[pos] * 16
                pos += 1
                if self._meta_len == 0:
                    self._end_block(titles)
            else:
                take = min(self._meta_len - len(self._meta_buf), len(data) - pos)
                self._meta_buf += data[pos : pos + take]
                pos += take
                if len(self._meta_buf) == self._meta_len:
                    self._end_block(titles)
        return bytes(audio), titles

    def _end_block(self, titles: list[str]) -> None:
        if self._meta_buf and (title := parse_stream_title(bytes(self._meta_buf))):
            titles.append(title)
        self._meta_buf.clear()
        self._meta_len = None
        self._audio_left = self._metaint
