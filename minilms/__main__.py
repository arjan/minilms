"""Entry point: `minilms --config config/stations.yaml`."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import logging
from pathlib import Path
import signal

from .app import MiniLMS
from .config import Config, ConfigError, load_config

LOGGER = logging.getLogger("minilms")


def _load(config_path: Path, state_file: Path | None) -> Config:
    config = load_config(config_path)
    return replace(config, state_file=state_file) if state_file else config


async def run(config_path: Path, state_file: Path | None) -> None:
    app = MiniLMS(_load(config_path, state_file))
    await app.start()

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def reload() -> None:
        try:
            app.reload(_load(config_path, state_file))
        except (OSError, ConfigError) as err:
            LOGGER.error("config reload failed, keeping the old one: %s", err)

    loop.add_signal_handler(signal.SIGHUP, reload)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await app.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="minilms", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/stations.yaml"))
    parser.add_argument("--state-file", type=Path, help="overrides server.state_file")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    asyncio.run(run(args.config, args.state_file))


if __name__ == "__main__":
    main()
