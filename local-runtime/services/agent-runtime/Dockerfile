FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_runtime ./agent_runtime

ENV AGENT_RUNTIME_HOST=0.0.0.0
ENV AGENT_RUNTIME_PORT=8766
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8766

CMD ["python", "-m", "agent_runtime"]
