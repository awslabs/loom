"""Composition root — wire adapters and start the Hub."""
from mcp_hub.adapters.inbound.http_app import serve

if __name__ == "__main__":
    serve()
