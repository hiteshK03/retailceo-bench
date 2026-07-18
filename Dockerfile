# Retail CEO Office — CPU-only Hugging Face Docker Space.
# The React + PixiJS SPA is prebuilt and committed at office/frontend/dist,
# so there is no Node build stage at image build time.
FROM python:3.11-slim

WORKDIR /app

# Runtime deps only (scripted path): fastapi, uvicorn, pydantic, websockets.
# No anthropic/openai/torch.
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bench package, scripted policies, the office backend, and the
# prebuilt frontend bundle. .dockerignore keeps node_modules / caches out.
COPY . .

EXPOSE 7860

# WORKDIR is on sys.path, so `office_api` and `retailceo` import as top-level.
CMD ["uvicorn", "office_api.app:app", "--host", "0.0.0.0", "--port", "7860", "--ws-ping-interval", "300", "--ws-ping-timeout", "300"]
