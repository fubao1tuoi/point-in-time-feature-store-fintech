# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip build \
    && python -m build --wheel --outdir /wheels


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIT_DATA_ROOT=/mnt/pit-data

# CatBoost requires the GNU OpenMP runtime. tini forwards termination signals
# correctly when the image runs as a batch job on Cloud Run.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pit \
    && useradd --uid 10001 --gid pit --create-home --shell /usr/sbin/nologin pit \
    && mkdir -p /app /mnt/pit-data \
    && chown -R pit:pit /app /mnt/pit-data

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl \
    && rm -rf /wheels

WORKDIR /app

COPY --chown=pit:pit configs ./configs
COPY --chown=pit:pit docker/entrypoint.sh /usr/local/bin/pit-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/pit-entrypoint \
    && chmod 0755 /usr/local/bin/pit-entrypoint

USER 10001:10001

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/pit-entrypoint"]
CMD ["demo-future-event-invariance"]


FROM runtime AS test

USER root
RUN python -m pip install "pytest>=8,<9" "pytest-cov>=5,<7" "ruff>=0.6,<1"

COPY --chown=pit:pit tests ./tests
COPY --chown=pit:pit pipelines ./pipelines
COPY --chown=pit:pit src ./src
COPY --chown=pit:pit pyproject.toml ./pyproject.toml

USER 10001:10001

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "pytest", "tests"]
