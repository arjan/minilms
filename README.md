# MiniLMS

A radio-only server for Squeezebox players, meant to replace Lyrion Music
Server when all you play is internet radio. It has no library, no scanning
and no plugins.

It is a thin layer on top of
[aioslimproto](https://github.com/music-assistant/aioslimproto), which provides
the SlimProto server (3483), discovery, and JSON-RPC/CometD. minilms serves
everything over HTTP on 9000, like LMS, and adds:

- stations from a YAML file, shown as *Internet Radio* in the player's home
  menu, with presets 1-6 mapped to the hardware buttons;
- a stream proxy (`/stream/<id>`) that fetches HTTPS streams for players that cannot,
  follows `.pls`/`.m3u` playlists, and strips ICY metadata into a
  now-playing title;
- enough of the LMS JSON-RPC API for Home Assistant's `squeezebox`
  integration: `serverstatus` with a stable uuid, `playlist play|load <url>`,
  and empty `alarms`/`favorites`/`apps`/`radios`;
- station logos (`/artwork/<id>`, and LMS's `/imageproxy/` form), resized
  with Pillow and cached; only configured logos, so it is not an open proxy;
- volume, power and last station kept in `state.json` across restarts.

## Run

```sh
uv sync
uv run minilms --config config/stations.yaml --debug
```

MiniLMS listens on 3483 (SlimProto, TCP and UDP) and 9000 (HTTP). Players
find it by broadcast; on a Squeezebox Radio you can also pick it under
Settings → Advanced → Networking → Remote Library.

## Docker

```sh
docker compose up -d
docker compose logs -f
docker kill -s HUP minilms   # reload the station list
```

GitHub Actions runs the tests and publishes a multi-arch image (amd64, arm64)
to `ghcr.io/arjan/minilms`: `latest` from `main`, a version tag for each
`v*` git tag. `compose.yaml` uses that image; to build one yourself, run
`docker build -t minilms .`.

The container uses host networking, because players find the server by UDP
broadcast. The image includes the default `config/stations.yaml`; to use your
own, mount a directory with a `stations.yaml` at `/config`. Volume, power and
the last station per player are kept in the `minilms-data` volume.

## Configuration

`config/stations.yaml` works as shipped. It has three sections:

- `server`: `name` (shown on the players), `default_volume`
  (0-100, for players minilms has not seen before), `ip_address` (the address
  players use for streams; default: the primary interface), `state_file`.
- `players`: optional names per player id (MAC). Without one, a player that
  reports no usable name is named after its model.
- `stations`: `id`, `name`, `url` (http or https, or a `.pls`/`.m3u`
  playlist), optional `icon` and `preset` (1-10; the Radio's buttons are
  1-6). The list order is the menu order.

## Limits

- No alarms. Lyrion runs Radio alarms on the server; use a Home Assistant
  automation instead.
- No transcoding. Stations must be MP3, AAC, Ogg or FLAC.
- Playlists resolve to their first URL. TuneIn `Tune.ashx` playlists often
  start with an ad pre-roll, so put the direct stream in the config instead.
- No support for SHOUTcast v1 servers that answer `ICY 200 OK` instead of HTTP.
- No authentication, the same as LMS by default. Keep the server on the LAN.
- minilms uses private parts of aioslimproto (its web app, `serverstatus`,
  the player name), which is why the dependency is pinned exactly.

## Test

```sh
uv run pytest
```

## License

Apache License 2.0; see [LICENSE](LICENSE).
