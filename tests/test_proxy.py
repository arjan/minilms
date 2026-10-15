import asyncio

from aiohttp import web
import pytest

from minilms.proxy import StreamProxy, first_url_in_playlist


def test_first_url_in_playlist():
    assert first_url_in_playlist("#EXTM3U\n#EXTINF:-1,x\nhttp://a/b\n") == "http://a/b"
    assert first_url_in_playlist("[playlist]\nFile1=https://c/d\nTitle1=x\n") == "https://c/d"
    assert first_url_in_playlist("nothing here") is None


@pytest.fixture
async def upstream(aiohttp_server):
    audio = [b"A" * 4, b"B" * 4]
    meta = b"StreamTitle='Song';".ljust(32, b"\x00")

    async def stream(request):
        assert request.headers.get("Icy-MetaData") == "1"
        resp = web.StreamResponse(
            headers={"Content-Type": "audio/mpeg; charset=x", "icy-metaint": "4"}
        )
        await resp.prepare(request)
        await resp.write(audio[0] + bytes([2]) + meta + audio[1] + b"\x00")
        return resp

    async def playlist(request):
        url = str(request.url.with_path("/stream"))
        return web.Response(text=f"[playlist]\nFile1={url}\n", content_type="audio/x-scpls")

    app = web.Application()
    app.router.add_get("/stream", stream)
    app.router.add_get("/radio.pls", playlist)
    return await aiohttp_server(app)


async def test_resolves_playlist_and_strips_metadata(upstream, aiohttp_server):
    titles = []
    proxy = StreamProxy(on_title=lambda sid, title: titles.append((sid, title)))
    await proxy.start()
    try:
        url, mime = await proxy.resolve(str(upstream.make_url("/radio.pls")))
        assert url == str(upstream.make_url("/stream"))
        assert mime == "audio/mpeg"
        proxy.register("st", url)
        server = await aiohttp_server(proxy.make_app())

        # The Radio speaks HTTP/1.0 and cannot handle chunked encoding.
        reader, writer = await asyncio.open_connection(server.host, server.port)
        writer.write(b"GET /stream/st HTTP/1.0\r\nHost: x\r\n\r\n")
        raw = await reader.read()
        writer.close()
        head, body = raw.split(b"\r\n\r\n", 1)
        assert head.startswith(b"HTTP/1.0 200") or head.startswith(b"HTTP/1.1 200")
        assert b"chunked" not in head.lower()
        assert b"icy-metaint" not in head.lower()
        assert body == b"AAAABBBB"
        assert titles == [("st", "Song")]
    finally:
        await proxy.stop()


async def test_unknown_stream_is_404(aiohttp_client):
    proxy = StreamProxy(on_title=lambda *_: None)
    client = await aiohttp_client(proxy.make_app())
    assert (await client.get("/stream/nope")).status == 404


def test_adhoc_registry_reuses_and_bounds():
    proxy = StreamProxy(on_title=lambda *_: None)
    first = proxy.register_adhoc("http://x/0")
    assert proxy.register_adhoc("http://x/0") == first
    for i in range(1, 20):
        proxy.register_adhoc(f"http://x/{i}")
    assert proxy.target(first) is None
