# nsjail is not packaged for Debian bookworm, so it is built from a pinned tag.
FROM debian:bookworm-slim AS nsjail
RUN apt-get update && apt-get install -y --no-install-recommends \
      autoconf bison flex gcc g++ git ca-certificates libprotobuf-dev libnl-route-3-dev \
      libtool make pkg-config protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch 3.4 https://github.com/google/nsjail.git /src \
    && make -C /src -j"$(nproc)" && cp /src/nsjail /nsjail

FROM node:22-bookworm-slim AS node

# The sandbox image is also every jail's root filesystem (mounted read-only), so the toolchains
# installed here are what the agent can use inside a workspace.
FROM python:3.12-slim-bookworm AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
      libprotobuf32 libnl-route-3-200 iptables iproute2 dnsmasq-base git curl ca-certificates ripgrep build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY --from=nsjail /nsjail /usr/local/bin/nsjail
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /usr/local/bin/

# The runner lives in /opt, which no jail mounts, so jails cannot read or change its code.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH=/opt/runner/.venv/bin:$PATH
WORKDIR /opt/runner
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY entrypoint.sh ./
COPY app/ ./app/
ENTRYPOINT ["/opt/runner/entrypoint.sh"]

FROM base AS test
RUN uv sync --locked --no-install-project
COPY tests/ ./tests/
COPY pytest.ini ./
CMD ["pytest", "-p", "no:cacheprovider"]

FROM base AS app
HEALTHCHECK --interval=5s --timeout=3s --retries=12 \
  CMD curl -fsS --unix-socket /run/echo/runner.sock http://runner/health || exit 1
CMD ["python", "-m", "app.main"]
