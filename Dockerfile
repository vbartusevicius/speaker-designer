FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.5.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends ngspice && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml poetry.lock README.md ./
ARG DEV=0
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
 && if [ "$DEV" = "1" ]; then poetry install --no-root; else poetry install --no-root --only main; fi \
 && apt-get purge -y build-essential && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
