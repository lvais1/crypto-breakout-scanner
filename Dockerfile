FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system scanner \
    && useradd --system --gid scanner --home-dir /app scanner

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install . \
    && mkdir -p /app/data \
    && chown -R scanner:scanner /app

USER scanner

CMD ["breakout-scanner", "run"]
