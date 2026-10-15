from minilms.icy import IcyStripper, parse_stream_title


def icy_stream(metaint: int, blocks: list[bytes], titles: list[str | None]) -> bytes:
    out = bytearray()
    for block, title in zip(blocks, titles, strict=True):
        assert len(block) == metaint
        out += block
        if title is None:
            out += b"\x00"
        else:
            meta = f"StreamTitle='{title}';".encode()
            meta += b"\x00" * (-len(meta) % 16)
            out += bytes([len(meta) // 16]) + meta
    return bytes(out)


def test_parse_stream_title():
    assert parse_stream_title(b"StreamTitle='A - B';StreamUrl='';\x00\x00") == "A - B"
    assert parse_stream_title(b"StreamUrl='x';") is None
    assert parse_stream_title("StreamTitle='Café';".encode("latin-1")) == "Café"


def test_strips_metadata_in_one_chunk():
    blocks = [b"a" * 8, b"b" * 8, b"c" * 8]
    data = icy_stream(8, blocks, ["One", None, "Two"])
    audio, titles = IcyStripper(8).feed(data)
    assert audio == b"".join(blocks)
    assert titles == ["One", "Two"]


def test_strips_metadata_byte_by_byte():
    blocks = [b"x" * 5, b"y" * 5]
    data = icy_stream(5, blocks, ["Long title that spans several sixteen byte units", "Z"])
    stripper = IcyStripper(5)
    audio, titles = bytearray(), []
    for i in range(len(data)):
        chunk, new = stripper.feed(data[i : i + 1])
        audio += chunk
        titles += new
    assert bytes(audio) == b"".join(blocks)
    assert titles == ["Long title that spans several sixteen byte units", "Z"]
