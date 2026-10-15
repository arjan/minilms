FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY minilms ./minilms
RUN uv sync --frozen --no-dev
# Default stations; mount a directory over /config to use your own.
COPY config/stations.yaml /config/stations.yaml

RUN useradd --system --uid 10001 minilms && mkdir /data && chown minilms /data
USER minilms
VOLUME /data
ENTRYPOINT ["/app/.venv/bin/minilms", "--config", "/config/stations.yaml", "--state-file", "/data/state.json"]
