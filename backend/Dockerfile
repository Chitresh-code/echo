# The browser app is built here; the api image gets only the static files it produces.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH=/app/backend/.venv/bin:$PATH
# Built from the repo root so the user guide in docs/ and the web app can be copied in beside the backend.
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# The api holds the provider keys, so it runs as an unprivileged user. /data is created here so
# the named volume mounted over it starts out owned by that user.
RUN useradd --uid 10001 --no-create-home echo-api && mkdir /data && chown echo-api /data
COPY backend/ ./
COPY docs/ /app/docs/
COPY --from=web /web/dist /app/web/dist

FROM base AS test
RUN uv sync --locked --no-install-project
USER echo-api
# The code is owned by root, so pytest cannot write its cache next to it.
CMD ["pytest", "-p", "no:cacheprovider"]

FROM base AS app
USER echo-api
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
