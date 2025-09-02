# ===== Base Python + deps GIS =====
FROM python:3.12-bullseye AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# OS libs: PostGIS clients (GDAL/GEOS/PROJ), Postgres, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev binutils \
    libpq-dev build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Pour Django GIS (GDAL include paths)
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# Option A: requirements.txt
COPY requirements.txt /app/

RUN pip install --no-cache-dir --upgrade pip \
 && pip uninstall -y django-channels || true \
 && pip uninstall -y channels-redis channels_redis channels daphne || true \
 && pip install --no-cache-dir -r requirements.txt


# Option B (si vous utilisez Poetry) :
# COPY pyproject.toml poetry.lock* /app/
# RUN pip install poetry && poetry config virtualenvs.create false \
#     && poetry install --only main

# Copie code
COPY . /app

# Crée un user non root
RUN #useradd -m appuser && chown -R appuser:appuser /app
#USER appuser

# Pré-compilation pyc (petit plus perf)
RUN python -m compileall -q .

# Entrypoint: migrations + collectstatic puis lance daphne
COPY entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000
CMD ["/app/docker/entrypoint.sh", "daphne", "-b", "0.0.0.0", "-p", "8000", "tratra.asgi:application"]