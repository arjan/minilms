"""Per-player state that survives a restart: volume, power, last stream."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)


@dataclass
class PlayerState:
    volume: int | None = None
    powered: bool = False
    station_id: str | None = None


class StateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._players: dict[str, PlayerState] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._players = {pid: PlayerState(**data) for pid, data in raw.items()}
        except FileNotFoundError:
            pass
        except (ValueError, TypeError) as err:
            LOGGER.warning("ignoring unreadable state file %s: %s", self._path, err)

    def get(self, player_id: str) -> PlayerState:
        return self._players.setdefault(player_id, PlayerState())

    def update(self, player_id: str, **changes) -> None:
        state = self.get(player_id)
        if all(getattr(state, key) == value for key, value in changes.items()):
            return
        for key, value in changes.items():
            setattr(state, key, value)
        self._save()

    def _save(self) -> None:
        # Losing state is an inconvenience; it must never break playback.
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({pid: asdict(s) for pid, s in self._players.items()}, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        except OSError as err:
            LOGGER.warning("cannot save state to %s: %s", self._path, err)
