# the demo's celery app: workers, beat and the seed step all use this image
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY client/ /src/client/
# celery[redis] for the redis broker transport, your app would have it too
RUN pip install /src/client "celery[redis]" && rm -rf /src
RUN useradd --system --uid 1000 shop
USER shop
WORKDIR /app
COPY demo/shop.py .
