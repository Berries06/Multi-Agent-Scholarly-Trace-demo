FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN addgroup --system yanhai \
    && adduser --system --ingroup yanhai --home /app yanhai

COPY --chown=yanhai:yanhai . /app
RUN mkdir -p /app/outputs && chown -R yanhai:yanhai /app/outputs

USER yanhai
EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/ready', timeout=2))['status']=='ready'"

# Fail-closed: binding to 0.0.0.0 also requires YANHAI_API_TOKEN or the
# explicit local-only override used by docker-compose.yml.
CMD ["python", "-m", "yanhai.server", "--host", "0.0.0.0", "--port", "8765"]
