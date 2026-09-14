FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mcp_hub ./mcp_hub
ENV MCP_HUB_HOST=0.0.0.0
ENV MCP_HUB_PORT=8790
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
EXPOSE 8790
CMD ["python", "-m", "mcp_hub"]
