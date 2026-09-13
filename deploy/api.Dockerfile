# API image. UNTESTED (no Docker on the build machine); see docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# libgomp for LightGBM and XGBoost.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# CPU torch first, so the project install does not pull the multi-gigabyte CUDA build.
RUN pip install torch==2.9.0 --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml README.md ./
COPY ml ./ml
COPY backend ./backend
COPY configs ./configs
COPY demo_data ./demo_data
RUN pip install ".[postgres]"

RUN useradd --create-home sentinel && mkdir -p /app/data/app /app/outbox && chown -R sentinel /app
USER sentinel

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
