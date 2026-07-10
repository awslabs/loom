FROM public.ecr.aws/docker/library/python:3.13-slim

RUN groupadd --system appuser && useradd --system --gid appuser appuser

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/
COPY backend/etc/models.json backend/etc/runtime_pricing.json backend/etc/providers.json ./etc/

# Agent source for build_agent_artifact (deployment.py resolves via parents[3] -> /)
COPY agents/strands_agent/src/ /agents/strands_agent/src/
COPY agents/strands_agent/requirements.txt /agents/strands_agent/requirements.txt

EXPOSE 8000

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
