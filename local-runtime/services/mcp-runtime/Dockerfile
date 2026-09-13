FROM node:20-bookworm-slim AS node

FROM python:3.12-slim

WORKDIR /app

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && chmod +x /usr/local/lib/node_modules/npm/bin/npm-cli.js \
                /usr/local/lib/node_modules/npm/bin/npx-cli.js \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @azure-devops/mcp@2.9.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_runtime ./mcp_runtime

ENV MCP_RUNTIME_HOST=0.0.0.0
ENV MCP_RUNTIME_PORT=8787
ENV MCP_TEMPLATES_DIR=/templates
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8787

CMD ["python", "-m", "mcp_runtime"]
