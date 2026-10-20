FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src
WORKDIR /app
RUN addgroup --system yanhai \
    && adduser --system --ingroup yanhai --home /app yanhai
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY --chown=yanhai:yanhai data/ ./data/
COPY --chown=yanhai:yanhai config/ ./config/
COPY --chown=yanhai:yanhai tests/experiments/ ./tests/experiments/
COPY --from=frontend-build --chown=yanhai:yanhai /build/frontend/dist ./frontend/dist
RUN mkdir -p /app/outputs /app/secret && chown -R yanhai:yanhai /app/outputs /app/secret
USER yanhai
EXPOSE 8766
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8766/api/ready', timeout=2))['status']=='ready'"
CMD ["python", "-m", "uvicorn", "yanhai.api:app", "--host", "0.0.0.0", "--port", "8766"]
