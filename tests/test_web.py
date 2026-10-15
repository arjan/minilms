import socket

from aiohttp import ClientSession, web
from aioslimproto import SlimServer

from minilms.web import MiniCLI


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_one_port_serves_jsonrpc_and_our_routes():
    port = free_port()
    server = SlimServer(cli_port=None, ip_address="127.0.0.1", name="t")

    async def handler(cmd):
        raise NotImplementedError

    async def hello(request):
        return web.Response(text="hi")

    cli = MiniCLI(server, port, handler, lambda app: app.router.add_get("/hello", hello))
    await cli.start()
    try:
        assert cli.cli_port_json == port
        async with ClientSession() as session:
            body = {"id": 1, "method": "slim.request", "params": ["", ["serverstatus", "-", "-"]]}
            async with session.post(f"http://127.0.0.1:{port}/jsonrpc.js", json=body) as resp:
                assert (await resp.json())["result"]["httpport"] == port
            async with session.get(f"http://127.0.0.1:{port}/hello") as resp:
                assert await resp.text() == "hi"
            async with session.get(f"http://127.0.0.1:{port}/music/1/cover.jpg") as resp:
                assert resp.status == 404
    finally:
        await cli.stop()
