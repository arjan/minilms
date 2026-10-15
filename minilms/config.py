"""Load and validate the YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from urllib.parse import urlparse

import yaml

MAX_PRESETS = 10
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ConfigError(ValueError):
    """Raised when the configuration file is invalid."""


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    url: str
    icon: str = ""
    preset: int | None = None


@dataclass(frozen=True)
class Config:
    name: str = "MiniLMS"
    # Advertised IP; None lets aioslimproto pick the primary interface.
    ip_address: str | None = None
    # Volume (0-100) for a player minilms has not seen before.
    default_volume: int = 30
    state_file: Path = Path("state.json")
    stations: list[Station] = field(default_factory=list)
    # Player id (MAC) -> display name; some players never report their name.
    player_names: dict[str, str] = field(default_factory=dict)

    def station(self, station_id: str) -> Station | None:
        return next((s for s in self.stations if s.id == station_id), None)

    def presets(self) -> list[Station | None]:
        """Stations by preset slot; index 0 is preset 1. Unassigned slots are None."""
        slots: list[Station | None] = [None] * MAX_PRESETS
        for station in self.stations:
            if station.preset is not None:
                slots[station.preset - 1] = station
        while slots and slots[-1] is None:
            slots.pop()
        return slots


def _parse_station(raw: object, index: int) -> Station:
    if not isinstance(raw, dict):
        raise ConfigError(f"stations[{index}]: expected a mapping")
    try:
        station = Station(
            id=str(raw["id"]),
            name=str(raw["name"]),
            url=str(raw["url"]),
            icon=str(raw.get("icon") or ""),
            preset=int(raw["preset"]) if raw.get("preset") is not None else None,
        )
    except KeyError as err:
        raise ConfigError(f"stations[{index}]: missing {err.args[0]!r}") from None
    if not _ID_RE.match(station.id):
        raise ConfigError(f"stations[{index}]: id {station.id!r} must match {_ID_RE.pattern}")
    if urlparse(station.url).scheme not in ("http", "https"):
        raise ConfigError(f"stations[{index}]: url must be http or https")
    if station.preset is not None and not 1 <= station.preset <= MAX_PRESETS:
        raise ConfigError(f"stations[{index}]: preset must be 1-{MAX_PRESETS}")
    return station


def parse_config(data: object) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("top level must be a mapping")
    server = data.get("server") or {}
    raw_stations = data.get("stations") or []
    if not isinstance(server, dict) or not isinstance(raw_stations, list):
        raise ConfigError("'server' must be a mapping and 'stations' a list")
    stations = [_parse_station(raw, i) for i, raw in enumerate(raw_stations)]
    players = data.get("players") or {}
    if not isinstance(players, dict):
        raise ConfigError("'players' must be a mapping of player id to settings")
    player_names = {
        str(pid).lower(): str(settings["name"])
        for pid, settings in players.items()
        if isinstance(settings, dict) and settings.get("name")
    }

    default_volume = int(server.get("default_volume", 30))
    if not 0 <= default_volume <= 100:
        raise ConfigError("server.default_volume must be 0-100")

    seen_ids: set[str] = set()
    seen_presets: set[int] = set()
    for station in stations:
        if station.id in seen_ids:
            raise ConfigError(f"duplicate station id {station.id!r}")
        seen_ids.add(station.id)
        if station.preset is not None:
            if station.preset in seen_presets:
                raise ConfigError(f"preset {station.preset} is assigned twice")
            seen_presets.add(station.preset)

    return Config(
        name=str(server.get("name", "MiniLMS")),
        ip_address=server.get("ip_address"),
        default_volume=default_volume,
        state_file=Path(server.get("state_file", "state.json")),
        stations=stations,
        player_names=player_names,
    )


def load_config(path: Path) -> Config:
    with path.open(encoding="utf-8") as fh:
        return parse_config(yaml.safe_load(fh))
