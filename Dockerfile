# One image for the API, the dashboard and the tests. CPU only by default.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libglib is needed by OpenCV at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY visionhub ./visionhub
COPY usecases ./usecases
COPY dashboard ./dashboard
COPY tests ./tests
COPY conftest.py ./
COPY .streamlit ./.streamlit

# Extras to install: "dashboard,dev" by default. A team that needs a real model can
# build with e.g.  docker compose build --build-arg EXTRAS=dashboard,dev,workstation
ARG EXTRAS=dashboard,dev
# Editable install: the source folders mounted by docker-compose are used directly.
RUN pip install -e ".[${EXTRAS}]"

EXPOSE 8000 8501
CMD ["uvicorn", "visionhub.api:app", "--host", "0.0.0.0", "--port", "8000"]
