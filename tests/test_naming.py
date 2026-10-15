from types import SimpleNamespace

import pytest

from minilms.app import MiniLMS
from minilms.config import parse_config


def player(reported: str):
    return SimpleNamespace(
        player_id="00:04:20:aa:bb:cc",
        device_type="controller",
        device_model="Squeezebox Radio",
        _device_name=reported,
    )


@pytest.fixture
def app(tmp_path):
    return MiniLMS(parse_config({"server": {"state_file": str(tmp_path / "s.json")}}))


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("", "Squeezebox Radio"),  # nothing reported yet
        ("controller: 00:04:20:aa:bb:", "Squeezebox Radio"),  # stored placeholder
        ("Squeezebox Radi", "Squeezebox Radio"),  # stored, cut-off model name
        ("Kitchen", "Kitchen"),  # a real name stays
    ],
)
def test_unusable_names_fall_back_to_model(app, reported, expected):
    p = player(reported)
    app._apply_name(p)
    assert p._device_name == expected


def test_configured_name_wins(tmp_path):
    app = MiniLMS(
        parse_config(
            {
                "server": {"state_file": str(tmp_path / "s.json")},
                "players": {"00:04:20:aa:bb:cc": {"name": "Keuken"}},
            }
        )
    )
    p = player("Kitchen")
    app._apply_name(p)
    assert p._device_name == "Keuken"
