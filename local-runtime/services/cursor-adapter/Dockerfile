FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cursor_adapter ./cursor_adapter

ENV CURSOR_ADAPTER_HOST=0.0.0.0
ENV CURSOR_ADAPTER_PORT=8765
ENV CURSOR_WORKSPACE=/workspace
ENV PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["python", "-m", "cursor_adapter"]
