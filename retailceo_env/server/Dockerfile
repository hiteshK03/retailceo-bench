# RetailCEO OpenEnv environment server (CPU-only).
#
# Build from the REPO ROOT so the retailceo/ core package is in context:
#   docker build -f retailceo_env/server/Dockerfile -t retailceo-env:latest .
#   docker run -p 8000:8000 -e RETAILCEO_DIFFICULTY=hard retailceo-env:latest
FROM python:3.11-slim

WORKDIR /app

# Core simulator + its package metadata (pydantic only).
COPY pyproject.toml /app/pyproject.toml
COPY retailceo /app/retailceo

# The OpenEnv env package (models, client, server).
COPY retailceo_env /app/retailceo_env

RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir "openenv>=0.4.1" "uvicorn[standard]>=0.27.0"

EXPOSE 8000

# Import as a package so relative imports in server/ resolve.
CMD ["uvicorn", "retailceo_env.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
