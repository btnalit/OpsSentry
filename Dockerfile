FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && useradd --create-home --shell /bin/bash opssentry \
    && chown -R opssentry:opssentry /app \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./pyproject.toml
COPY src ./src
COPY config ./config
COPY data ./data

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chown -R opssentry:opssentry /app

USER opssentry

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
