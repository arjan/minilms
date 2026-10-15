"""Serve everything on port 9000, like LMS does.

aioslimproto builds its JSON-RPC/CometD web app inside SlimProtoCLI.start()
and gives no hook for extra routes. Squeezebox players fetch artwork from the
server's port 9000, so this subclass builds the web app itself: aioslimproto's
two handlers plus our routes. It touches private attributes of SlimProtoCLI,
which is safe only while aioslimproto stays pinned.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

from aiohttp import web
from aioslimproto import SlimServer
from aioslimproto.cli import SlimCLICommandHandler, SlimProtoCLI

LOGGER = logging.getLogger(__name__)


class MiniCLI(SlimProtoCLI):
    def __init__(
        self,
        server: SlimServer,
        port: int,
        command_handler: SlimCLICommandHandler,
        add_routes: Callable[[web.Application], None],
    ) -> None:
        # cli_port_json=None stops the base class from starting its own web app.
        super().__init__(server, cli_port=None, cli_port_json=None, command_handler=command_handler)
        self._port = port
        self._add_routes = add_routes

    async def start(self) -> None:
        await super().start()  # event subscriptions and the periodic task
        self.cli_port_json = self._port  # read by discovery and serverstatus
        app = web.Application(logger=self.logger)
        app.router.add_route("*", "/jsonrpc.js", self._handle_jsonrpc_client)
        app.router.add_route("*", "/cometd", self._handle_cometd_client)
        self._add_routes(app)
        app.router.add_route("*", "/{tail:.*}", _not_found)
        self._webapp = app
        self._apprunner = web.AppRunner(app, access_log=None, shutdown_timeout=10)
        await self._apprunner.setup()
        self._tcp_site = web.TCPSite(self._apprunner, host=None, port=self._port)
        await self._tcp_site.start()


async def _not_found(request: web.Request) -> web.Response:
    # Logged so we learn what players ask for that we don't serve yet.
    LOGGER.info("404 %s %s from %s", request.method, request.path_qs, request.remote)
    raise web.HTTPNotFound()
