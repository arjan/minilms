from pathlib import Path

import pytest

from minilms.config import ConfigError, load_config, parse_config


def station(**overrides):
    return {"id": "s1", "name": "S1", "url": "https://example.org/s1", **overrides}


def test_shipped_example_loads():
    config = load_config(Path(__file__).parent.parent / "config" / "stations.yaml")
    assert len(config.stations) == 22
    assert [s.id for s in config.presets() if s] == [
        "npo-radio-1", "npo-radio-2", "npo-3fm", "sky-radio", "joe", "radio-538"
    ]


def test_presets_keep_gaps_and_trim_tail():
    config = parse_config(
        {"stations": [station(preset=3), station(id="s2", preset=1), station(id="s3")]}
    )
    assert [s.id if s else None for s in config.presets()] == ["s2", None, "s1"]


@pytest.mark.parametrize(
    ("stations", "message"),
    [
        ([station(), station()], "duplicate station id"),
        ([station(preset=1), station(id="s2", preset=1)], "assigned twice"),
        ([station(preset=11)], "preset must be"),
        ([station(url="ftp://x")], "http or https"),
        ([station(id="Bad Id")], "must match"),
        ([{"id": "s1", "name": "x"}], "missing 'url'"),
    ],
)
def test_rejects_invalid(stations, message):
    with pytest.raises(ConfigError, match=message):
        parse_config({"stations": stations})


def test_player_names_are_lowercased():
    config = parse_config({"players": {"00:04:20:AA:BB:CC": {"name": "Keuken"}}})
    assert config.player_names == {"00:04:20:aa:bb:cc": "Keuken"}


def test_state_save_failure_is_not_fatal(tmp_path, caplog):
    from minilms.state import StateStore

    store = StateStore(tmp_path / "missing-dir" / "state.json")
    store.update("p1", volume=10)  # must not raise
    assert store.get("p1").volume == 10
    assert "cannot save state" in caplog.text


def test_default_volume():
    assert parse_config({}).default_volume == 30
    with pytest.raises(ConfigError, match="default_volume"):
        parse_config({"server": {"default_volume": 150}})
