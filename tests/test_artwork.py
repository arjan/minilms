import io
from urllib.parse import quote

from aiohttp import web
from PIL import Image
import pytest

from minilms.app import MiniLMS
from minilms.artwork import ArtworkCache, parse_size, render_png
from minilms.config import parse_config


def png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(out, format="PNG")
    return out.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def test_parse_size():
    assert parse_size("image_240x200_m.png") == (240, 200)
    assert parse_size("image_9999x9999_m.png") == (500, 500)
    assert parse_size("") == (300, 300)


def test_render_keeps_aspect_ratio():
    assert size_of(render_png(png(400, 200), 100, 100)) == (100, 50)


async def test_cache_fetches_once():
    calls = []

    async def fetch(url):
        calls.append(url)
        return png(50, 50)

    cache = ArtworkCache(fetch)
    await cache.get("http://x/logo.png", 40, 40)
    await cache.get("http://x/logo.png", 20, 20)
    assert calls == ["http://x/logo.png"]


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    config = parse_config(
        {
            "server": {"state_file": str(tmp_path / "state.json")},
            "stations": [
                {"id": "a", "name": "A", "url": "http://a", "icon": "https://cdn/a.png"},
                {"id": "b", "name": "B", "url": "http://b"},
            ],
        }
    )
    app = MiniLMS(config)
    fetched = []

    async def fetch(url):
        fetched.append(url)
        return png(400, 400)

    app.artwork._fetch = fetch
    web_app = web.Application()
    app._add_routes(web_app)
    client = await aiohttp_client(web_app)
    client.minilms, client.fetched = app, fetched
    return client


async def test_artwork_route(client):
    resp = await client.get("/artwork/a")
    assert resp.status == 200 and resp.content_type == "image/png"
    assert size_of(await resp.read()) == (300, 300)
    assert (await client.get("/artwork/b")).status == 404
    assert (await client.get("/artwork/nope")).status == 404


async def test_imageproxy_accepts_our_url_and_configured_icon_only(client):
    ours = quote(client.minilms.artwork_url(client.minilms.config.station("a")), safe="")
    resp = await client.get(f"/imageproxy/{ours}/image_120x120_m.png")
    assert resp.status == 200
    assert size_of(await resp.read()) == (120, 120)
    icon = quote("https://cdn/a.png", safe="")
    assert (await client.get(f"/imageproxy/{icon}/image_60x60_m.png")).status == 200
    evil = quote("http://169.254.169.254/latest", safe="")
    assert (await client.get(f"/imageproxy/{evil}/image_60x60_m.png")).status == 404
    assert client.fetched == ["https://cdn/a.png"]
