# Multi-stage build: deps -> test / artifacts / data / runtime.
# Every stage copies explicit paths only.

FROM python:3.12-slim AS deps
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements.txt \
    && pip install --no-index --find-links /wheels -r requirements.txt

# Lint and tests run here, in the shipped environment. No calibration step, so a code bug
# can only fail in the test stages of the pipeline, never while building this image.
FROM deps AS test
COPY requirements-dev.txt pyproject.toml ./
RUN pip install -r requirements-dev.txt
COPY src ./src
COPY config ./config
COPY data/real ./data/real
COPY tests ./tests
RUN pip install --no-deps . && rm -rf build src/*.egg-info && mkdir /reports

# Same WORKDIR and paths as `test`, so the calibration outputs are byte-identical.
FROM deps AS artifacts
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-deps . && rm -rf build src/*.egg-info \
    && python -m quakeloc.calibrate --seed 42 --out /artifacts

# ObsPy has no linux/arm64 wheel, so on Apple Silicon it compiles from source.
FROM deps AS data
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-data.txt pyproject.toml ./
RUN pip install -r requirements-data.txt
COPY src ./src
COPY config ./config
RUN pip install --no-deps . && rm -rf build src/*.egg-info
ENTRYPOINT ["python", "-m", "quakeloc.data.fetch"]

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    QUAKELOC_ARTIFACTS=/artifacts QUAKELOC_CONFIG=/app/config QUAKELOC_SNAPSHOT=/app/data/real
WORKDIR /app
COPY --from=deps /wheels /wheels
COPY requirements.txt pyproject.toml /build/
COPY src /build/src
RUN pip install --no-index --find-links /wheels -r /build/requirements.txt \
    && pip install --no-deps /build \
    && rm -rf /wheels /build \
    && useradd -u 10001 -r app
COPY --from=artifacts /artifacts /artifacts
COPY config ./config
COPY data/real ./data/real
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
# Build metadata comes last, so it never invalidates the cache of the layers above.
ARG GIT_SHA=unknown
ARG BUILD_NUMBER=unknown
ARG CREATED=unknown
ENV GIT_SHA=${GIT_SHA} BUILD_NUMBER=${BUILD_NUMBER}
LABEL org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/a169n/applied_5" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.title="quakeloc"
CMD ["uvicorn", "quakeloc.api:app", "--host", "0.0.0.0", "--port", "8000"]
