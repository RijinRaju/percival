# The panel: api + the built web ui in one image.
#
#   docker run -p 8080:8080 -v percival:/data \
#     -e PERCIVAL_REDIS_URL=redis://your-redis:6379/0 ghcr.io/rijinraju/percival

FROM node:22-alpine AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# vite writes into ../server/percival_server/static
RUN mkdir -p ../server/percival_server && npm run build


FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY client/ client/
COPY server/ server/
COPY --from=web /src/server/percival_server/static/ server/percival_server/static/
RUN pip install ./client ./server && rm -rf /src

RUN useradd --system --uid 1000 --home-dir /data percival \
    && mkdir -p /data && chown percival /data
USER percival
WORKDIR /data

ENV PERCIVAL_HOST=0.0.0.0 \
    PERCIVAL_PORT=8080 \
    PERCIVAL_DATA_DIR=/data
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"

CMD ["percival-server"]
