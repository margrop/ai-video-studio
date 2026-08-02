FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIVS_STORAGE_ROOT=/data/.aivs

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY apps ./apps
COPY packages ./packages
COPY providers ./providers
COPY schemas ./schemas
COPY templates ./templates

RUN python -m pip install --no-cache-dir .

VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
