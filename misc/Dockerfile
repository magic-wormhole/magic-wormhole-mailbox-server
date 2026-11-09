# syntax=docker/dockerfile:1

# Build a wheel in a throwaway stage so the runtime image has no build tools
# or pip cache.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY . .
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .


FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Run as an unprivileged user and keep all mutable state in /data.
RUN groupadd --system --gid 10001 wormhole \
 && useradd --no-create-home --home-dir /data --shell /usr/sbin/nologin \
        --uid 10001 --gid wormhole wormhole \
 && install -d --owner wormhole --group wormhole /data

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index \
        --find-links=/wheels magic-wormhole-mailbox-server \
 && rm -rf /wheels \
 && python -c "import twisted.plugins; \
from twisted.plugin import getPlugins; \
from twisted.application.service import IServiceMaker; \
list(getPlugins(IServiceMaker, twisted.plugins))" \
 && PLUGIN_DIR=$(python -c "import twisted.plugins, os; \
print(os.path.dirname(twisted.plugins.__file__))") \
 && chown wormhole:wormhole "$PLUGIN_DIR/dropin.cache"

USER wormhole
WORKDIR /data

# The mailbox server speaks WebSocket on this port.
EXPOSE 4000
VOLUME ["/data"]
STOPSIGNAL SIGTERM

# Verify that the server is accepting TCP connections.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 4000), 2).close()"]

# `twist` is Twisted's application runner; it installs SIGTERM/SIGINT
# handlers and runs in the foreground, so it is the correct PID 1 here.
ENTRYPOINT ["twist", "wormhole-mailbox"]
CMD ["--channel-db=/data/relay.sqlite", \
     "--usage-db=/data/usage.sqlite", \
     "--port=tcp:4000"]
